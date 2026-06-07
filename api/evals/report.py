"""Build, render, and compare eval results."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from evals.scorer import DimensionResult


def build_result(dimensions: list[DimensionResult], model: str) -> dict[str, Any]:
    return {
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dimensions": {d.name: {"score": d.score, "details": d.details} for d in dimensions},
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [f"# Eval result — model `{result['model']}`", f"_{result['created_at']}_", ""]
    for name, d in result["dimensions"].items():
        det = d["details"]
        lines.append(f"## {name}: {d['score']:.1%} ({det.get('correct')}/{det.get('total')})")
        if det.get("gate_false_negatives") is not None:
            lines.append(f"- gate false-negatives: {det['gate_false_negatives']}")
        lat = det.get("latency")
        if lat:
            lines.append(
                f"- latency: mean {lat['mean_ms']:.0f} ms · median {lat['median_ms']:.0f} ms · p95 {lat['p95_ms']:.0f} ms"
            )
        fails = [r for r in det.get("rows", []) if not r.get("correct")]
        if fails:
            lines.append("")
            lines.append("| case | file | actual | predicted |")
            lines.append("|---|---|---|---|")
            for r in fails:
                lines.append(f"| {r['case_id']} | {r['file_id']} | {r['actual']} | {r['predicted']} |")
    return "\n".join(lines)


def _rows(result: dict[str, Any]) -> dict[tuple[str, str], dict]:
    rows = result["dimensions"].get("classification", {}).get("details", {}).get("rows", [])
    return {(r["case_id"], r["file_id"]): r for r in rows}


def _latency(result: dict[str, Any]) -> dict[str, float]:
    return result["dimensions"].get("classification", {}).get("details", {}).get("latency", {}) or {}


def compare(new: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    nb, bb = _rows(new), _rows(baseline)
    regressions: list[dict] = []
    improvements: list[dict] = []
    for key, nr in nb.items():
        br = bb.get(key)
        if br is None:
            continue
        if br["correct"] and not nr["correct"]:
            regressions.append(nr)
        elif not br["correct"] and nr["correct"]:
            improvements.append(nr)
    nlat, blat = _latency(new), _latency(baseline)
    latency_delta = {
        "baseline_mean_ms": blat.get("mean_ms"),
        "new_mean_ms": nlat.get("mean_ms"),
        "baseline_median_ms": blat.get("median_ms"),
        "new_median_ms": nlat.get("median_ms"),
    }
    return {
        "baseline_model": baseline["model"],
        "new_model": new["model"],
        "regressions": regressions,
        "improvements": improvements,
        "latency_delta": latency_delta,
    }
