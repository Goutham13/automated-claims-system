"""CLI: run eval dimensions, write a model-tagged result, optionally baseline/compare.

Run from api/ (needs the classifier backend, e.g. Vertex, configured):

    python -m evals.run                          # run + write result + print markdown
    python -m evals.run --baseline               # also save as results/baseline.json
    python -m evals.run --compare results/baseline.json
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from evals.dataset import load_cases
from evals.report import build_result, compare, render_markdown
from evals.scorer import ClassificationDimension

RESULTS = Path(__file__).resolve().parent / "results"


def write_result(result: dict, results_dir: Path, *, baseline: bool = False) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    model = result.get("model", "model").replace("/", "_").replace(":", "_")
    path = results_dir / f"{stamp}_{model}.json"
    path.write_text(json.dumps(result, indent=2))
    if baseline:
        (results_dir / "baseline.json").write_text(json.dumps(result, indent=2))
    return path


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--baseline", action="store_true", help="save this run as baseline.json")
    ap.add_argument("--compare", metavar="BASELINE_JSON", help="diff this run against a baseline")
    args = ap.parse_args()

    model = os.getenv("PIPELINE_MODEL", "gemini-3-flash-preview")
    cases = load_cases()
    result = build_result([ClassificationDimension().score(cases)], model)

    path = write_result(result, RESULTS, baseline=args.baseline)
    print(render_markdown(result))
    print(f"\nWrote {path}")

    if args.compare:
        baseline = json.loads(Path(args.compare).read_text())
        diff = compare(result, baseline)
        print(f"\n## Compare vs {diff['baseline_model']}")
        print(f"Regressions: {len(diff['regressions'])} | Improvements: {len(diff['improvements'])}")
        for r in diff["regressions"]:
            print(f"  REGRESSED {r['case_id']}/{r['file_id']}: {r['actual']} -> {r['predicted']}")
        for r in diff["improvements"]:
            print(f"  IMPROVED  {r['case_id']}/{r['file_id']}: {r['actual']} -> {r['predicted']}")


if __name__ == "__main__":
    main()
