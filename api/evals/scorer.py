"""Scoring dimensions for the eval harness. v1: classification accuracy.

Dimensions are pluggable (the `Dimension` Protocol), so extraction / consistency /
end-to-end / LLM-judge dimensions slot in later without changing the runner.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from evals.dataset import EvalCase
from pipeline.stages import classify_document


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
        correct = total = gate_fn = 0
        for case in cases:
            for doc in case.documents:
                res = classify_document(
                    {"file_id": doc.file_id, "file_name": doc.file_name, "document_text": doc.ocr_text}
                )
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
                })
        accuracy = correct / total if total else 0.0
        return DimensionResult("classification", accuracy, {
            "total": total,
            "correct": correct,
            "accuracy": accuracy,
            "gate_false_negatives": gate_fn,
            "confusion": {k: dict(v) for k, v in confusion.items()},
            "rows": rows,
        })
