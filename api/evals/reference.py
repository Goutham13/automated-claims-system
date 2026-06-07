"""Load the committed Gemini golden-set reference (per-case stage outputs)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agents.consistency_check_agent.agent import ConsistencyCheckResult
from agents.document_extraction_agent.agent import DocumentExtractionResult
from agents.document_gate_agent.agent import DocumentClassificationResult
from agents.document_requirements_agent.agent import DocumentRequirementsResult

REFERENCE_DIR = Path(__file__).resolve().parent / "reference"


@dataclass
class RefCase:
    classification: dict[str, DocumentClassificationResult]
    requirements: DocumentRequirementsResult
    extraction: dict[str, DocumentExtractionResult]
    consistency: ConsistencyCheckResult
    ref_model: str


def load_reference(reference_dir: Path | None = None) -> dict[str, RefCase]:
    """Parse evals/reference/<case_id>.json files into RefCase objects keyed by case_id."""
    base = reference_dir or REFERENCE_DIR
    out: dict[str, RefCase] = {}
    for path in sorted(base.glob("*.json")):
        data = json.loads(path.read_text())
        out[path.stem] = RefCase(
            classification={
                fid: DocumentClassificationResult.model_validate(v)
                for fid, v in data.get("classification", {}).items()
            },
            requirements=DocumentRequirementsResult.model_validate(data["requirements"]),
            extraction={
                fid: DocumentExtractionResult.model_validate(v)
                for fid, v in data.get("extraction", {}).items()
            },
            consistency=ConsistencyCheckResult.model_validate(data["consistency"]),
            ref_model=data.get("ref_model", "unknown"),
        )
    return out
