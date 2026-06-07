"""Scoring dimensions for the eval harness. v1: classification accuracy.

Dimensions are pluggable (the `Dimension` Protocol), so extraction / consistency /
end-to-end / LLM-judge dimensions slot in later without changing the runner.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from evals.dataset import EvalCase
from pipeline.stages import (
    build_consistency_snapshots,
    check_consistency,
    check_requirements,
    classify_document,
    extract_document,
)

# Document-type → DocumentExtractionResult section attribute (for field-agreement).
_SECTION = {
    "PRESCRIPTION": "prescription",
    "HOSPITAL_BILL": "hospital_bill",
    "LAB_REPORT": "lab_report",
    "PHARMACY_BILL": "pharmacy_bill",
    "DENTAL_REPORT": "dental_report",
    "DISCHARGE_SUMMARY": "discharge_summary",
}

# Required document types per claim category (from DOCUMENT_REQUIREMENTS_PROMPT).
_REQUIRED = {
    "CONSULTATION": {"PRESCRIPTION", "HOSPITAL_BILL"},
    "DIAGNOSTIC": {"PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"},
    "PHARMACY": {"PRESCRIPTION", "PHARMACY_BILL"},
    "DENTAL": {"HOSPITAL_BILL"},
    "VISION": {"PRESCRIPTION", "HOSPITAL_BILL"},
    "ALTERNATIVE_MEDICINE": {"PRESCRIPTION", "HOSPITAL_BILL"},
}


def _expected_requirements(claim_category: str, actual_types: list[str]) -> str:
    """Deterministic expected outcome: PASS if all required types present, else NOT_PASS."""
    required = _REQUIRED.get(claim_category, set())
    return "PASS" if required.issubset(set(actual_types)) else "NOT_PASS"


def _latency_stats(samples: list[float]) -> dict[str, float]:
    """mean / median / p95 (ms) over per-call latencies."""
    if not samples:
        return {"mean_ms": 0.0, "median_ms": 0.0, "p95_ms": 0.0}
    ordered = sorted(samples)
    mean_ms = sum(ordered) / len(ordered)
    mid = len(ordered) // 2
    median_ms = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    p95_ms = ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]
    return {"mean_ms": round(mean_ms, 1), "median_ms": round(median_ms, 1), "p95_ms": round(p95_ms, 1)}


@dataclass
class DimensionResult:
    name: str
    score: float
    details: dict[str, Any] = field(default_factory=dict)


class Dimension(Protocol):
    name: str

    def score(self, cases: list[EvalCase]) -> DimensionResult: ...


class ClassificationDimension:
    name = "classification"

    def score(self, cases: list[EvalCase]) -> DimensionResult:
        rows: list[dict[str, Any]] = []
        confusion: dict[str, Counter] = defaultdict(Counter)
        latencies: list[float] = []
        correct = total = gate_fn = 0
        for case in cases:
            for doc in case.documents:
                t0 = time.perf_counter()
                res = classify_document(
                    {"file_id": doc.file_id, "file_name": doc.file_name, "document_text": doc.ocr_text}
                )
                latency_ms = (time.perf_counter() - t0) * 1000.0
                latencies.append(latency_ms)
                pred = res.predicted_type
                is_ok = pred == doc.actual_type
                correct += int(is_ok)
                total += 1
                confusion[doc.actual_type][pred] += 1
                if res.gate_outcome == "PENDING_REUPLOAD" and doc.actual_type != "UNKNOWN":
                    gate_fn += 1
                rows.append({
                    "case_id": case.case_id,
                    "file_id": doc.file_id,
                    "actual": doc.actual_type,
                    "predicted": pred,
                    "correct": is_ok,
                    "confidence": res.confidence_score,
                    "gate_outcome": res.gate_outcome,
                    "latency_ms": round(latency_ms, 1),
                })
        accuracy = correct / total if total else 0.0
        return DimensionResult("classification", accuracy, {
            "total": total,
            "correct": correct,
            "accuracy": accuracy,
            "gate_false_negatives": gate_fn,
            "latency": _latency_stats(latencies),
            "confusion": {k: dict(v) for k, v in confusion.items()},
            "rows": rows,
        })


class RequirementsDimension:
    """Score each model's requirements outcome (PASS vs not) against the computed rule outcome.

    `ref` and `cand` are (backend, model) tuples. Stage-isolated: uses ground-truth actual_types.
    """

    name = "requirements"

    def __init__(self, ref: tuple[str, str], cand: tuple[str, str]):
        self.ref, self.cand = ref, cand

    def _run(self, cases: list[EvalCase], backend: str, model: str) -> dict[str, Any]:
        correct = total = 0
        latencies: list[float] = []
        rows: list[dict[str, Any]] = []
        for case in cases:
            actual_types = [d.actual_type for d in case.documents]
            expected = _expected_requirements(case.claim_category, actual_types)
            t0 = time.perf_counter()
            res = check_requirements(case.claim_category, actual_types, backend=backend, model=model)
            latencies.append((time.perf_counter() - t0) * 1000.0)
            got = "PASS" if res.outcome == "PASS" else "NOT_PASS"
            is_ok = got == expected
            correct += int(is_ok)
            total += 1
            rows.append({"case_id": case.case_id, "expected": expected,
                         "outcome": res.outcome, "normalized": got, "correct": is_ok})
        return {"accuracy": (correct / total if total else 0.0), "correct": correct,
                "total": total, "latency": _latency_stats(latencies), "rows": rows}

    def score(self, cases: list[EvalCase]) -> DimensionResult:
        ref = self._run(cases, *self.ref)
        cand = self._run(cases, *self.cand)
        return DimensionResult("requirements", cand["accuracy"], {"ref": ref, "cand": cand})


def _section_fields(result, document_type: str) -> dict | None:
    """The populated typed section of an extraction result as a flat dict, or None."""
    attr = _SECTION.get(document_type)
    section = getattr(result, attr, None) if attr else None
    return section.model_dump() if section is not None else None


class ExtractionAgreementDimension:
    """Field-agreement of the candidate's extraction vs the Gemini reference (no gold labels)."""

    name = "extraction"

    def __init__(self, ref: tuple[str, str], cand: tuple[str, str]):
        self.ref, self.cand = ref, cand

    def score(self, cases: list[EvalCase]) -> DimensionResult:
        rows: list[dict[str, Any]] = []
        agreements: list[float] = []
        ref_lat: list[float] = []
        cand_lat: list[float] = []
        ref_complete = cand_complete = doc_count = 0
        for case in cases:
            for doc in case.documents:
                d = {"file_id": doc.file_id, "file_name": doc.file_name,
                     "document_type": doc.actual_type, "document_text": doc.ocr_text}
                t0 = time.perf_counter()
                r_ref = extract_document(d, backend=self.ref[0], model=self.ref[1])
                ref_lat.append((time.perf_counter() - t0) * 1000.0)
                t1 = time.perf_counter()
                r_cand = extract_document(d, backend=self.cand[0], model=self.cand[1])
                cand_lat.append((time.perf_counter() - t1) * 1000.0)
                doc_count += 1
                ref_complete += int(r_ref.missing_critical_fields == [])
                cand_complete += int(r_cand.missing_critical_fields == [])
                ref_sec = _section_fields(r_ref, doc.actual_type)
                cand_sec = _section_fields(r_cand, doc.actual_type)
                if ref_sec is None or cand_sec is None:
                    agreement = 1.0 if ref_sec == cand_sec else 0.0
                else:
                    keys = set(ref_sec) | set(cand_sec)
                    match = sum(1 for k in keys if ref_sec.get(k) == cand_sec.get(k))
                    agreement = match / len(keys) if keys else 1.0
                agreements.append(agreement)
                rows.append({"case_id": case.case_id, "file_id": doc.file_id,
                             "document_type": doc.actual_type, "field_agreement": round(agreement, 3)})
        mean_agree = sum(agreements) / len(agreements) if agreements else 0.0
        return DimensionResult("extraction", mean_agree, {
            "mean_field_agreement": mean_agree,
            "ref_completeness": (ref_complete / doc_count if doc_count else 0.0),
            "cand_completeness": (cand_complete / doc_count if doc_count else 0.0),
            "ref_latency": _latency_stats(ref_lat),
            "cand_latency": _latency_stats(cand_lat),
            "rows": rows,
        })


class ConsistencyAgreementDimension:
    """Outcome-agreement of the candidate's consistency check vs Gemini, on identical snapshots."""

    name = "consistency"

    def __init__(self, ref: tuple[str, str], cand: tuple[str, str]):
        self.ref, self.cand = ref, cand

    def score(self, cases: list[EvalCase]) -> DimensionResult:
        rows: list[dict[str, Any]] = []
        agree = total = 0
        ref_lat: list[float] = []
        cand_lat: list[float] = []
        for case in cases:
            # Fixed input: snapshots from the reference model's extraction.
            ref_extractions = [
                extract_document(
                    {"file_id": d.file_id, "file_name": d.file_name,
                     "document_type": d.actual_type, "document_text": d.ocr_text},
                    backend=self.ref[0], model=self.ref[1])
                for d in case.documents
            ]
            snaps = build_consistency_snapshots(ref_extractions)
            t0 = time.perf_counter()
            r_ref = check_consistency(snaps, backend=self.ref[0], model=self.ref[1])
            ref_lat.append((time.perf_counter() - t0) * 1000.0)
            t1 = time.perf_counter()
            r_cand = check_consistency(snaps, backend=self.cand[0], model=self.cand[1])
            cand_lat.append((time.perf_counter() - t1) * 1000.0)
            is_match = r_ref.outcome == r_cand.outcome
            agree += int(is_match)
            total += 1
            rows.append({"case_id": case.case_id, "ref_outcome": r_ref.outcome,
                         "cand_outcome": r_cand.outcome, "match": is_match})
        rate = agree / total if total else 0.0
        return DimensionResult("consistency", rate, {
            "outcome_agreement": rate,
            "ref_latency": _latency_stats(ref_lat),
            "cand_latency": _latency_stats(cand_lat),
            "rows": rows,
        })
