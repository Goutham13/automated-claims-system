"""All-stage comparison of a candidate vs the cached Gemini golden set.

Classification + requirements are scored vs labels (gold / computed rule); the cached reference's
own accuracy on those is computed from the golden set (no live reference calls). Extraction +
consistency are agreement-vs-cached-reference. Per-stage candidate latency included.

Run from api/ (needs the candidate backend; golden set must already be captured):
  REF_MODEL=gemini-3-pro-preview python -m evals.capture_reference      # once
  PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:14b python -m evals.stage_compare
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evals.dataset import load_cases
from evals.reference import load_reference
from evals.scorer import (
    ClassificationDimension,
    ConsistencyAgreementDimension,
    DimensionResult,
    ExtractionAgreementDimension,
    RequirementsDimension,
    score_cached_classification,
    score_cached_requirements,
)

RESULTS = Path(__file__).resolve().parent / "results"


def build_stage_report(
    cls_cand: DimensionResult,
    cls_ref: dict[str, Any],
    req_cand: DimensionResult,
    req_ref: dict[str, Any],
    extraction: DimensionResult,
    consistency: DimensionResult,
    ref_model: str,
    cand: tuple[str, str],
) -> dict[str, Any]:
    return {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ref_model": ref_model,
        "cand": {"backend": cand[0], "model": cand[1]},
        "stages": {
            "classification": {"metric": "accuracy_vs_truth",
                               "ref": cls_ref, "cand": cls_cand.details},
            "requirements": {"metric": "accuracy_vs_computed",
                             "ref": req_ref, "cand": req_cand.details},
            "extraction": {"metric": "field_agreement_vs_ref", **extraction.details},
            "consistency": {"metric": "outcome_agreement_vs_ref", **consistency.details},
        },
    }


def render_stage_markdown(report: dict[str, Any]) -> str:
    ref = report["ref_model"]
    cand = report["cand"]["model"]
    s = report["stages"]
    cl, rq = s["classification"], s["requirements"]
    ex, co = s["extraction"], s["consistency"]
    lines = [
        f"# All-stage comparison — `{cand}` vs cached reference `{ref}`",
        f"_{report['created_at']}_",
        "",
        "| stage | metric | reference | candidate |",
        "|---|---|---|---|",
        f"| classification | accuracy vs truth | {cl['ref']['accuracy']:.1%} | {cl['cand']['accuracy']:.1%} |",
        f"| requirements | accuracy vs computed | {rq['ref']['accuracy']:.1%} | {rq['cand']['accuracy']:.1%} |",
        f"| extraction (all fields) | agreement vs ref | — | {ex['mean_field_agreement']:.1%} (exact {ex['exact_only']:.1%}) |",
        f"| extraction (critical) | agreement vs ref | — | {ex['critical_field_agreement']:.1%} |",
        f"| consistency | outcome-agreement vs ref | — | {co['outcome_agreement']:.1%} |",
        "",
        "### Candidate latency (mean ms)",
        f"- classification: {cl['cand']['latency']['mean_ms']:.0f}",
        f"- requirements: {rq['cand']['latency']['mean_ms']:.0f}",
        f"- extraction: {ex['cand_latency']['mean_ms']:.0f}",
        f"- consistency: {co['cand_latency']['mean_ms']:.0f}",
        "",
        f"Extraction critical-field completeness: ref {ex['ref_completeness']:.1%} · cand {ex['cand_completeness']:.1%}",
    ]
    return "\n".join(lines)


def main() -> None:
    cand = (os.getenv("PIPELINE_BACKEND", "ollama"), os.getenv("PIPELINE_MODEL", "qwen2.5:14b"))
    cases = load_cases()
    reference = load_reference()
    if not reference:
        raise SystemExit("No golden set found. Run `python -m evals.capture_reference` first.")
    ref_model = next(iter(reference.values())).ref_model

    cls_cand = ClassificationDimension().score(cases, backend=cand[0], model=cand[1])
    cls_ref = score_cached_classification(cases, reference)
    req_cand = RequirementsDimension(cand).score(cases)
    req_ref = score_cached_requirements(cases, reference)
    extraction = ExtractionAgreementDimension(cand, reference).score(cases)
    consistency = ConsistencyAgreementDimension(cand, reference).score(cases)

    report = build_stage_report(cls_cand, cls_ref, req_cand, req_ref,
                                extraction, consistency, ref_model, cand)

    RESULTS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe = cand[1].replace("/", "_").replace(":", "_")
    path = RESULTS / f"stage_compare_{stamp}_{safe}.json"
    path.write_text(json.dumps(report, indent=2))
    print(render_stage_markdown(report))
    print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
