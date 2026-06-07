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
