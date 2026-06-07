"""All-stage comparison: a self-hosted candidate vs the Gemini reference, across all four stages.

Classification + requirements are scored vs labels (gold / computed rule outcome); extraction +
consistency are agreement-vs-Gemini (no gold labels). Per-stage latency for both models included.

Run from api/ (needs Ollama + Vertex):
  set -a; source .env; set +a
  OLLAMA_MAX_LOADED_MODELS=1 PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:7b-instruct \
    python -m evals.stage_compare
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.dataset import load_cases
from evals.scorer import (
    ClassificationDimension,
    ConsistencyAgreementDimension,
    DimensionResult,
    ExtractionAgreementDimension,
    RequirementsDimension,
)

RESULTS = Path(__file__).resolve().parent / "results"


def build_stage_report(
    classification_ref: DimensionResult,
    classification_cand: DimensionResult,
    requirements: DimensionResult,
    extraction: DimensionResult,
    consistency: DimensionResult,
    ref: tuple[str, str],
    cand: tuple[str, str],
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ref": {"backend": ref[0], "model": ref[1]},
        "cand": {"backend": cand[0], "model": cand[1]},
        "stages": {
            "classification": {
                "metric": "accuracy_vs_truth",
                "ref": classification_ref.details,
                "cand": classification_cand.details,
            },
            "requirements": {"metric": "accuracy_vs_computed", **requirements.details},
            "extraction": {"metric": "field_agreement_vs_ref", **extraction.details},
            "consistency": {"metric": "outcome_agreement_vs_ref", **consistency.details},
        },
    }


def render_stage_markdown(report: dict[str, Any]) -> str:
    ref, cand = report["ref"]["model"], report["cand"]["model"]
    s = report["stages"]
    cl_ref = s["classification"]["ref"]
    cl_cand = s["classification"]["cand"]
    rq = s["requirements"]
    ex = s["extraction"]
    co = s["consistency"]
    lines = [
        f"# All-stage comparison — `{cand}` (candidate) vs `{ref}` (reference)",
        f"_{report['created_at']}_",
        "",
        "| stage | metric | reference | candidate |",
        "|---|---|---|---|",
        f"| classification | accuracy vs truth | {cl_ref['accuracy']:.1%} | {cl_cand['accuracy']:.1%} |",
        f"| requirements | accuracy vs computed | {rq['ref']['accuracy']:.1%} | {rq['cand']['accuracy']:.1%} |",
        f"| extraction | field-agreement vs ref | — | {ex['mean_field_agreement']:.1%} |",
        f"| consistency | outcome-agreement vs ref | — | {co['outcome_agreement']:.1%} |",
        "",
        "### Latency (mean ms, reference → candidate)",
        f"- classification: {cl_ref['latency']['mean_ms']:.0f} → {cl_cand['latency']['mean_ms']:.0f}",
        f"- requirements: {rq['ref']['latency']['mean_ms']:.0f} → {rq['cand']['latency']['mean_ms']:.0f}",
        f"- extraction: {ex['ref_latency']['mean_ms']:.0f} → {ex['cand_latency']['mean_ms']:.0f}",
        f"- consistency: {co['ref_latency']['mean_ms']:.0f} → {co['cand_latency']['mean_ms']:.0f}",
        "",
        f"Extraction critical-field completeness: ref {ex['ref_completeness']:.1%} · cand {ex['cand_completeness']:.1%}",
    ]
    return "\n".join(lines)


def main() -> None:
    ref = ("gemini", os.getenv("REF_MODEL", "gemini-3-flash-preview"))
    cand = (os.getenv("PIPELINE_BACKEND", "ollama"), os.getenv("PIPELINE_MODEL", "qwen2.5:7b-instruct"))
    cases = load_cases()

    classification_ref = ClassificationDimension().score(cases, backend=ref[0], model=ref[1])
    classification_cand = ClassificationDimension().score(cases, backend=cand[0], model=cand[1])
    requirements = RequirementsDimension(ref, cand).score(cases)
    extraction = ExtractionAgreementDimension(ref, cand).score(cases)
    consistency = ConsistencyAgreementDimension(ref, cand).score(cases)

    report = build_stage_report(
        classification_ref, classification_cand, requirements, extraction, consistency, ref, cand)

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    path = RESULTS / f"stage_compare_{stamp}.json"
    path.write_text(json.dumps(report, indent=2))
    print(render_stage_markdown(report))
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
