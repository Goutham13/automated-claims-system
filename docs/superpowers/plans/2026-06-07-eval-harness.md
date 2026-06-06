# Eval Harness (Classification-First) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A stage-isolated, classification-first eval harness that scores `classify_document` against `test_cases.json` ground truth, with captured OCR fixtures, a model-tagged JSON result, and a baseline/compare workflow for safe Gemini→Qwen swaps.

**Architecture:** New `api/evals/` package — `dataset.py` (load cases + resolve doc files + join fixtures), `capture.py` (one-time Qwen OCR → committed text fixtures), `scorer.py` (pluggable `Dimension` + `ClassificationDimension`), `report.py` (result/markdown/compare), `run.py` (CLI). Scoring calls the real stage via `pipeline/llm.py`, so model = `PIPELINE_MODEL` env.

**Tech Stack:** Python 3.11+, Pydantic/dataclasses, pytest. Reuses `ocr.service` and `pipeline.stages`.

**Reference spec:** `docs/superpowers/specs/2026-06-07-eval-harness-design.md`

**Verified data facts:**
- `test_cases.json` → `{test_cases: [{case_id, case_name, input:{claim_category, documents:[{file_id, actual_type, file_name?}]}, expected}]}` (12 cases).
- Every doc has `file_id` + `actual_type`. `file_name` present only TC001–003. TC004–012 disk files are prefixed by `file_id` (e.g. `F007_prescription.jpg`).
- Mock images live at `mock_claim_documents/<case_id>/` (`.jpg` + `.pdf` per doc).

---

### Task 1: Package scaffold + `dataset.py` + test

**Files:** Create `api/evals/__init__.py`, `api/evals/dataset.py`, `api/tests/test_evals_dataset.py`

- [ ] **Step 1: Failing test** — `api/tests/test_evals_dataset.py`
```python
import json
from pathlib import Path

from evals import dataset


def test_resolve_by_file_name_then_file_id(tmp_path, monkeypatch):
    case_dir = tmp_path / "mock_claim_documents" / "TC001"
    case_dir.mkdir(parents=True)
    (case_dir / "rx.jpg").write_bytes(b"x")
    (case_dir / "F008_bill.jpg").write_bytes(b"x")
    monkeypatch.setattr(dataset, "MOCK_DIR", tmp_path / "mock_claim_documents")
    # by file_name
    p = dataset.resolve_doc_file("TC001", {"file_id": "F001", "file_name": "rx.jpg"})
    assert p and p.name == "rx.jpg"
    # by file_id prefix (no file_name)
    p2 = dataset.resolve_doc_file("TC001", {"file_id": "F008"})
    assert p2 and p2.name == "F008_bill.jpg"
    # missing
    assert dataset.resolve_doc_file("TC001", {"file_id": "F999"}) is None


def test_load_cases_joins_fixture_text(tmp_path, monkeypatch):
    tc = {"version": 1, "test_cases": [{
        "case_id": "TC001", "case_name": "Case", "description": "",
        "input": {"claim_category": "CONSULTATION",
                  "documents": [{"file_id": "F001", "actual_type": "PRESCRIPTION", "file_name": "rx.jpg"}]},
        "expected": {"decision": None}}]}
    (tmp_path / "test_cases.json").write_text(json.dumps(tc))
    fx = tmp_path / "evals" / "fixtures" / "TC001"
    fx.mkdir(parents=True)
    (fx / "F001.txt").write_text("PRESCRIPTION TEXT")
    monkeypatch.setattr(dataset, "TEST_CASES", tmp_path / "test_cases.json")
    monkeypatch.setattr(dataset, "FIXTURES", tmp_path / "evals" / "fixtures")
    cases = dataset.load_cases()
    assert len(cases) == 1
    doc = cases[0].documents[0]
    assert doc.actual_type == "PRESCRIPTION"
    assert doc.ocr_text == "PRESCRIPTION TEXT"
```

- [ ] **Step 2: Run → fails** (`cd api && uv run pytest tests/test_evals_dataset.py -q`).

- [ ] **Step 3: Implement** — `api/evals/__init__.py` (`"""Stage-isolated eval harness."""`) and `api/evals/dataset.py`:
```python
"""Load eval cases: test_cases.json ground truth joined with captured OCR fixtures."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_API_DIR = Path(__file__).resolve().parents[1]          # api/
_REPO = _API_DIR.parent                                 # repo root
TEST_CASES = _REPO / "test_cases.json"
MOCK_DIR = _REPO / "mock_claim_documents"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

IMG_EXTS = (".jpg", ".jpeg", ".png")


@dataclass
class EvalDocument:
    file_id: str
    file_name: str
    actual_type: str
    ocr_text: str = ""


@dataclass
class EvalCase:
    case_id: str
    case_name: str
    claim_category: str
    documents: list[EvalDocument]


def resolve_doc_file(case_id: str, doc: dict) -> Path | None:
    """Find the image file for a document: by file_name, else by file_id prefix."""
    case_dir = MOCK_DIR / case_id
    if not case_dir.is_dir():
        return None
    fn = doc.get("file_name")
    if fn and (case_dir / fn).exists():
        return case_dir / fn
    fid = doc["file_id"]
    for p in sorted(case_dir.iterdir()):
        if p.suffix.lower() in IMG_EXTS and p.stem.startswith(fid):
            return p
    return None


def load_cases() -> list[EvalCase]:
    data = json.loads(TEST_CASES.read_text())
    cases: list[EvalCase] = []
    for c in data["test_cases"]:
        docs: list[EvalDocument] = []
        for d in c["input"]["documents"]:
            fid = d["file_id"]
            resolved = resolve_doc_file(c["case_id"], d)
            fname = d.get("file_name") or (resolved.name if resolved else fid)
            fx = FIXTURES / c["case_id"] / f"{fid}.txt"
            text = fx.read_text() if fx.exists() else ""
            docs.append(EvalDocument(fid, fname, d["actual_type"], text))
        cases.append(EvalCase(c["case_id"], c["case_name"], c["input"]["claim_category"], docs))
    return cases
```

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(evals): add dataset loader with doc-file resolution`

---

### Task 2: `capture.py` (OCR fixture capture)

**Files:** Create `api/evals/capture.py`

> Capture hits live Qwen/Ollama, so it's a manual script (no unit test); it reuses the tested `resolve_doc_file`.

- [ ] **Step 1: Implement** — `api/evals/capture.py`:
```python
"""One-time: run the self-hosted OCR over each test case's documents, save text fixtures.

Run from api/ with Ollama serving:  python -m evals.capture
"""
from __future__ import annotations

import json

from evals.dataset import FIXTURES, TEST_CASES, resolve_doc_file
from ocr.service import extract_text_for_documents

_MIME = {".pdf": "application/pdf", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}


def capture() -> None:
    data = json.loads(TEST_CASES.read_text())
    for c in data["test_cases"]:
        cid = c["case_id"]
        out = FIXTURES / cid
        out.mkdir(parents=True, exist_ok=True)
        docs = []
        for d in c["input"]["documents"]:
            p = resolve_doc_file(cid, d)
            if not p:
                print(f"[skip] {cid} {d['file_id']}: no file found")
                continue
            docs.append({
                "file_id": d["file_id"],
                "file_name": p.name,
                "mime_type": _MIME.get(p.suffix.lower(), "image/jpeg"),
                "bytes": p.read_bytes(),
            })
        batch = extract_text_for_documents(docs)
        for r in batch.results:
            (out / f"{r.file_id}.txt").write_text(r.document_text)
            print(f"[{cid}] {r.file_id}: {len(r.document_text)} chars {'ok' if r.ok else 'FAIL:'+str(r.error)}")


if __name__ == "__main__":
    capture()
```

- [ ] **Step 2: Verify import** — `cd api && uv run python -c "import evals.capture; print('ok')"`.
- [ ] **Step 3: Commit** — `feat(evals): add OCR fixture capture script`

---

### Task 3: `scorer.py` (Dimension + ClassificationDimension) + test

**Files:** Create `api/evals/scorer.py`, `api/tests/test_evals_scorer.py`

- [ ] **Step 1: Failing test** — `api/tests/test_evals_scorer.py`
```python
import evals.scorer as scorer
from evals.dataset import EvalCase, EvalDocument
from agents.document_gate_agent.agent import DocumentClassificationResult


def _doc(fid, actual):
    return EvalDocument(fid, f"{fid}.jpg", actual, ocr_text="text")


def _result(ptype, gate="PASS"):
    return DocumentClassificationResult(
        file_id="x", file_name="x", predicted_type=ptype, confidence_score=0.9,
        confidence_band="HIGH", gate_outcome=gate, ops_message="")


def test_classification_accuracy_and_confusion(monkeypatch):
    cases = [EvalCase("TC1", "c", "CONSULTATION",
                      [_doc("F1", "PRESCRIPTION"), _doc("F2", "HOSPITAL_BILL")])]
    preds = {"F1": _result("PRESCRIPTION"), "F2": _result("PRESCRIPTION")}  # F2 wrong
    monkeypatch.setattr(scorer, "classify_document",
                        lambda d: preds[d["file_id"]])
    res = scorer.ClassificationDimension().score(cases)
    assert res.name == "classification"
    assert res.score == 0.5
    assert res.details["correct"] == 1 and res.details["total"] == 2


def test_gate_false_negative_counted(monkeypatch):
    cases = [EvalCase("TC1", "c", "CONSULTATION", [_doc("F1", "PRESCRIPTION")])]
    monkeypatch.setattr(scorer, "classify_document",
                        lambda d: _result("UNKNOWN", gate="PENDING_REUPLOAD"))
    res = scorer.ClassificationDimension().score(cases)
    assert res.details["gate_false_negatives"] == 1
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — `api/evals/scorer.py`:
```python
"""Scoring dimensions for the eval harness. v1: classification accuracy."""
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
                    {"file_id": doc.file_id, "file_name": doc.file_name, "document_text": doc.ocr_text})
                pred = res.predicted_type
                is_ok = pred == doc.actual_type
                correct += int(is_ok)
                total += 1
                confusion[doc.actual_type][pred] += 1
                if res.gate_outcome == "PENDING_REUPLOAD" and doc.actual_type != "UNKNOWN":
                    gate_fn += 1
                rows.append({
                    "case_id": case.case_id, "file_id": doc.file_id,
                    "actual": doc.actual_type, "predicted": pred,
                    "correct": is_ok, "confidence": res.confidence_score,
                    "gate_outcome": res.gate_outcome})
        accuracy = correct / total if total else 0.0
        return DimensionResult("classification", accuracy, {
            "total": total, "correct": correct, "accuracy": accuracy,
            "gate_false_negatives": gate_fn,
            "confusion": {k: dict(v) for k, v in confusion.items()},
            "rows": rows})
```

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(evals): add classification scoring dimension`

---

### Task 4: `report.py` (result / markdown / compare) + test

**Files:** Create `api/evals/report.py`, `api/tests/test_evals_report.py`

- [ ] **Step 1: Failing test** — `api/tests/test_evals_report.py`
```python
from evals.report import build_result, compare, render_markdown
from evals.scorer import DimensionResult


def _result(model, rows):
    dr = DimensionResult("classification", sum(r["correct"] for r in rows) / len(rows),
                         {"rows": rows, "total": len(rows),
                          "correct": sum(r["correct"] for r in rows)})
    return build_result([dr], model)


def test_build_and_render():
    res = _result("gemini", [{"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION",
                              "predicted": "PRESCRIPTION", "correct": True}])
    assert res["model"] == "gemini"
    assert res["dimensions"]["classification"]["score"] == 1.0
    md = render_markdown(res)
    assert "classification" in md and "gemini" in md


def test_compare_flags_regression_and_improvement():
    base = _result("gemini", [
        {"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION", "predicted": "PRESCRIPTION", "correct": True},
        {"case_id": "TC2", "file_id": "F2", "actual": "LAB_REPORT", "predicted": "UNKNOWN", "correct": False}])
    new = _result("qwen", [
        {"case_id": "TC1", "file_id": "F1", "actual": "PRESCRIPTION", "predicted": "UNKNOWN", "correct": False},
        {"case_id": "TC2", "file_id": "F2", "actual": "LAB_REPORT", "predicted": "LAB_REPORT", "correct": True}])
    diff = compare(new, base)
    assert any(d["file_id"] == "F1" for d in diff["regressions"])
    assert any(d["file_id"] == "F2" for d in diff["improvements"])
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — `api/evals/report.py`:
```python
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
    lines = [f"# Eval result — model `{result['model']}`", f"_ {result['created_at']} _", ""]
    for name, d in result["dimensions"].items():
        det = d["details"]
        lines.append(f"## {name}: {d['score']:.1%} ({det.get('correct')}/{det.get('total')})")
        if det.get("gate_false_negatives") is not None:
            lines.append(f"- gate false-negatives: {det['gate_false_negatives']}")
        fails = [r for r in det.get("rows", []) if not r.get("correct")]
        if fails:
            lines.append("\n| case | file | actual | predicted |")
            lines.append("|---|---|---|---|")
            for r in fails:
                lines.append(f"| {r['case_id']} | {r['file_id']} | {r['actual']} | {r['predicted']} |")
    return "\n".join(lines)


def _rows(result: dict[str, Any]) -> dict[tuple, dict]:
    rows = result["dimensions"].get("classification", {}).get("details", {}).get("rows", [])
    return {(r["case_id"], r["file_id"]): r for r in rows}


def compare(new: dict[str, Any], baseline: dict[str, Any]) -> dict[str, Any]:
    nb, bb = _rows(new), _rows(baseline)
    regressions, improvements = [], []
    for key, nr in nb.items():
        br = bb.get(key)
        if br is None:
            continue
        if br["correct"] and not nr["correct"]:
            regressions.append(nr)
        elif not br["correct"] and nr["correct"]:
            improvements.append(nr)
    return {
        "baseline_model": baseline["model"], "new_model": new["model"],
        "regressions": regressions, "improvements": improvements,
    }
```

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(evals): add result builder, markdown report, and baseline compare`

---

### Task 5: `run.py` CLI

**Files:** Create `api/evals/run.py`, `api/tests/test_evals_run.py`

- [ ] **Step 1: Failing test** — `api/tests/test_evals_run.py` (test the pure helper, not live models)
```python
import json
from evals import run as runmod


def test_write_and_load_result(tmp_path):
    result = {"model": "m", "created_at": "t", "dimensions": {}}
    p = runmod.write_result(result, tmp_path, baseline=True)
    assert p.exists()
    base = tmp_path / "baseline.json"
    assert base.exists()
    assert json.loads(base.read_text())["model"] == "m"
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** — `api/evals/run.py`:
```python
"""CLI: run eval dimensions, write a model-tagged result, optionally baseline/compare.

Run from api/ (needs Vertex for the classifier model):
  python -m evals.run                         # run + write result + print markdown
  python -m evals.run --baseline              # also save as results/baseline.json
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


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Full suite** — `cd api && uv run pytest -q` → green.
- [ ] **Step 6: Commit** — `feat(evals): add eval CLI runner with baseline/compare`

---

### Task 6: Capture fixtures, run baseline, document (manual + README)

**Files:** Create `api/evals/README.md`; generate `api/evals/fixtures/**`, `api/evals/results/baseline.json`

- [ ] **Step 1: Capture fixtures** (Ollama running): `cd api && uv run python -m evals.capture` — verify each case prints non-zero chars.
- [ ] **Step 2: Baseline run** (Vertex configured): `cd api && PIPELINE_MODEL=gemini-3-flash-preview uv run python -m evals.run --baseline` — review accuracy + confusion.
- [ ] **Step 3: Write `api/evals/README.md`** documenting capture → run → baseline → compare and the Gemini-vs-Qwen workflow.
- [ ] **Step 4: Commit** — `feat(evals): capture OCR fixtures, baseline result, and runbook`
  - (Commit the `fixtures/` text and `results/baseline.json` so the baseline is reproducible.)

---

## Self-Review

**Spec coverage:** classification accuracy (T3), captured fixtures (T2), model-tagged result + baseline/compare (T4/T5), pluggable Dimension (T3), doc-file resolution for both label shapes (T1), runbook + baseline artifact (T6). ✓
**Placeholder scan:** all code shown; no TBD. ✓
**Type consistency:** `EvalCase`/`EvalDocument` (T1) used by `scorer` (T3); `DimensionResult` (T3) consumed by `report` (T4); `build_result/compare/render_markdown` signatures consistent across T4/T5. ✓

## Execution Handoff
Inline execution via executing-plans (user: "go ahead"). Tasks 1–5 are TDD/committable without live services; Task 6 needs Ollama + Vertex and is run manually at the end.
