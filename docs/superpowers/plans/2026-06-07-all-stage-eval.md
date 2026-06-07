# All-Stage Eval Comparison Implementation Plan

> REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`).

**Goal:** Compare `qwen2.5:7b-instruct` (ollama) vs `gemini` across all four stages — accuracy for
classification/requirements (gold/computed labels), agreement-vs-Gemini for extraction/consistency —
plus per-stage latency, via a new `evals/stage_compare.py`.

**Reference spec:** `docs/superpowers/specs/2026-06-07-all-stage-eval-design.md`

---

### Task 1: Thread `backend`/`model` through llm + stages + test

**Files:** Modify `api/pipeline/llm.py`, `api/pipeline/stages.py`; Create `api/tests/test_stage_backend_arg.py`

- [ ] **Step 1: Failing test** — assert an explicit `backend="ollama"` arg routes to the ollama path even when env is unset/gemini, and stage functions forward it.
```python
import pipeline.llm as llm
import pipeline.stages as stages
from agents.document_gate_agent.agent import DocumentClassificationResult


def test_structured_call_explicit_backend(monkeypatch):
    calls = {}
    def fake_ollama(sp, payload, om, *, model=None, base_url=None, retries=1):
        calls["backend"] = "ollama"; calls["model"] = model
        return om.model_construct()
    monkeypatch.setattr(llm, "_ollama_call", fake_ollama)
    monkeypatch.delenv("PIPELINE_BACKEND", raising=False)
    out = llm.structured_llm_call("s", {"a": 1}, DocumentClassificationResult,
                                  backend="ollama", model="qwen2.5:7b-instruct")
    assert calls["backend"] == "ollama" and calls["model"] == "qwen2.5:7b-instruct"


def test_stage_forwards_backend(monkeypatch):
    seen = {}
    def fake_call(sp, payload, om, *, model=None, backend=None, client=None):
        seen["backend"] = backend; seen["model"] = model
        return om.model_construct(file_id="F1", file_name="x", predicted_type="PRESCRIPTION",
                                  confidence_score=1.0, confidence_band="HIGH",
                                  gate_outcome="PASS", ops_message="")
    monkeypatch.setattr(stages, "structured_llm_call", fake_call)
    stages.classify_document({"file_id": "F1", "file_name": "x", "document_text": "t"},
                             backend="gemini", model="gemini-3-flash-preview")
    assert seen["backend"] == "gemini" and seen["model"] == "gemini-3-flash-preview"
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement**
  - `llm.structured_llm_call(..., *, model=None, client=None, backend=None)`:
    `backend = (backend or os.getenv("PIPELINE_BACKEND", "gemini")).lower()`; dispatch as today.
    Pass `model` through to both `_gemini_call` and `_ollama_call`.
  - Each `stages.py` function gains `*, backend: str | None = None, model: str | None = None` and
    forwards them: `structured_llm_call(PROMPT, payload, OutModel, backend=backend, model=model)`.
    Defaults keep current env behavior (orchestrator unaffected).

- [ ] **Step 4: Run → passes. Full suite green** (`uv run pytest -q`).
- [ ] **Step 5: Commit** — `feat(pipeline): allow explicit backend/model per call (backward-compatible)`

---

### Task 2: `_expected_requirements` + RequirementsDimension + test

**Files:** Modify `api/evals/scorer.py`; Create `api/tests/test_evals_requirements.py`

- [ ] **Step 1: Failing test**
```python
from evals.scorer import _expected_requirements, RequirementsDimension
import evals.scorer as scorer
from evals.dataset import EvalCase, EvalDocument
from agents.document_requirements_agent.agent import DocumentRequirementsResult


def _doc(fid, t): return EvalDocument(fid, f"{fid}.jpg", t, "txt")


def test_expected_requirements_rules():
    assert _expected_requirements("CONSULTATION", ["PRESCRIPTION", "HOSPITAL_BILL"]) == "PASS"
    assert _expected_requirements("CONSULTATION", ["PRESCRIPTION", "PRESCRIPTION"]) == "NOT_PASS"
    assert _expected_requirements("PHARMACY", ["PRESCRIPTION", "PHARMACY_BILL"]) == "PASS"
    assert _expected_requirements("DENTAL", ["HOSPITAL_BILL"]) == "PASS"


def test_requirements_dimension_scores_each_model(monkeypatch):
    cases = [EvalCase("TC1", "c", "CONSULTATION", [_doc("F1", "PRESCRIPTION"), _doc("F2", "HOSPITAL_BILL")])]
    def fake_req(cat, types, *, backend=None, model=None):
        # gemini correct (PASS), candidate wrong (PENDING_REUPLOAD)
        outcome = "PASS" if backend == "gemini" else "PENDING_REUPLOAD"
        return DocumentRequirementsResult(outcome=outcome, claim_category=cat, ops_message="")
    monkeypatch.setattr(scorer, "check_requirements", fake_req)
    dim = RequirementsDimension(("gemini", "gemini-x"), ("ollama", "qwen"))
    res = dim.score(cases)
    assert res.details["ref"]["accuracy"] == 1.0
    assert res.details["cand"]["accuracy"] == 0.0
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** in `scorer.py`:
```python
_REQUIRED = {
    "CONSULTATION": {"PRESCRIPTION", "HOSPITAL_BILL"},
    "DIAGNOSTIC": {"PRESCRIPTION", "LAB_REPORT", "HOSPITAL_BILL"},
    "PHARMACY": {"PRESCRIPTION", "PHARMACY_BILL"},
    "DENTAL": {"HOSPITAL_BILL"},
    "VISION": {"PRESCRIPTION", "HOSPITAL_BILL"},
    "ALTERNATIVE_MEDICINE": {"PRESCRIPTION", "HOSPITAL_BILL"},
}

def _expected_requirements(claim_category: str, actual_types: list[str]) -> str:
    required = _REQUIRED.get(claim_category, set())
    return "PASS" if required.issubset(set(actual_types)) else "NOT_PASS"
```
- Import `check_requirements` from `pipeline.stages`. `RequirementsDimension.__init__(self, ref, cand)`
  where each is a `(backend, model)` tuple. `score()`: for each case, `actual_types = [d.actual_type
  for d in case.documents]`; expected = `_expected_requirements(...)`; for each model run
  `check_requirements(category, actual_types, backend=b, model=m)`, normalize `"PASS" if outcome=="PASS"
  else "NOT_PASS"`, compare to expected; aggregate per-model `accuracy` + latency into
  `details = {"ref": {...}, "cand": {...}, "rows": [...]}`. Name = `"requirements"`.

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(evals): add requirements dimension scored vs computed rule outcome`

---

### Task 3: Extraction + Consistency agreement dimensions + test

**Files:** Modify `api/evals/scorer.py`; Create `api/tests/test_evals_agreement.py`

- [ ] **Step 1: Failing test**
```python
import evals.scorer as scorer
from evals.dataset import EvalCase, EvalDocument
from agents.document_extraction_agent.agent import (
    DocumentExtractionResult, PrescriptionFields)
from agents.consistency_check_agent.agent import ConsistencyCheckResult


def _case():
    return EvalCase("TC1", "c", "CONSULTATION", [EvalDocument("F1", "rx.jpg", "PRESCRIPTION", "t")])


def test_extraction_field_agreement(monkeypatch):
    ref = DocumentExtractionResult(file_id="F1", file_name="rx", document_type="PRESCRIPTION",
        extraction_confidence=0.9, ops_message="",
        prescription=PrescriptionFields(patient_name="Rajesh", diagnosis_primary="Fever", doctor_name="A"))
    cand = DocumentExtractionResult(file_id="F1", file_name="rx", document_type="PRESCRIPTION",
        extraction_confidence=0.9, ops_message="",
        prescription=PrescriptionFields(patient_name="Rajesh", diagnosis_primary="Cough", doctor_name="A"))
    def fake_extract(doc, *, backend=None, model=None):
        return ref if backend == "gemini" else cand
    monkeypatch.setattr(scorer, "extract_document", fake_extract)
    dim = scorer.ExtractionAgreementDimension(("gemini", "g"), ("ollama", "q"))
    res = dim.score([_case()])
    # one field differs (diagnosis_primary) out of the populated prescription fields → <1.0
    assert 0.0 < res.score < 1.0


def test_consistency_outcome_agreement(monkeypatch):
    def fake_extract(doc, *, backend=None, model=None):
        return DocumentExtractionResult(file_id="F1", file_name="rx", document_type="PRESCRIPTION",
            extraction_confidence=0.9, ops_message="")
    def fake_cons(snaps, *, claimed_amount=None, treatment_date=None, backend=None, model=None):
        out = "PASS" if backend == "gemini" else "MANUAL_REVIEW_RECOMMENDED"
        return ConsistencyCheckResult(outcome=out, confidence_score=0.9, ops_message="")
    monkeypatch.setattr(scorer, "extract_document", fake_extract)
    monkeypatch.setattr(scorer, "check_consistency", fake_cons)
    dim = scorer.ConsistencyAgreementDimension(("gemini", "g"), ("ollama", "q"))
    res = dim.score([_case()])
    assert res.score == 0.0  # outcomes disagree
```

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** in `scorer.py`:
  - `_SECTION = {"PRESCRIPTION": "prescription", "HOSPITAL_BILL": "hospital_bill", "LAB_REPORT":
    "lab_report", "PHARMACY_BILL": "pharmacy_bill", "DENTAL_REPORT": "dental_report",
    "DISCHARGE_SUMMARY": "discharge_summary"}`.
  - `ExtractionAgreementDimension(ref, cand)`: for each doc, run `extract_document(doc, backend, model)`
    for both; get the populated section attr via `_SECTION[doc.actual_type]`; if both have it, compare
    `model_dump()` field-by-field (`None==None` matches) → `matching/total`; mean across docs = score.
    Also per-model completeness = mean(`missing_critical_fields == []`). Latency per model.
  - `ConsistencyAgreementDimension(ref, cand)`: build snapshots from the **ref** model's extraction
    (`build_consistency_snapshots`), run `check_consistency(snaps, backend, model)` for both, score =
    mean(`ref.outcome == cand.outcome`). Latency per model.
  - Import `extract_document`, `check_consistency`, `build_consistency_snapshots` from `pipeline.stages`.

- [ ] **Step 4: Run → passes.**
- [ ] **Step 5: Commit** — `feat(evals): add extraction/consistency agreement-vs-gemini dimensions`

---

### Task 4: `stage_compare.py` CLI + test

**Files:** Create `api/evals/stage_compare.py`, `api/tests/test_stage_compare.py`

- [ ] **Step 1: Failing test** — test a pure render/aggregate helper `build_stage_report(dim_results, ref, cand)` → dict with the four stage entries + models; `render_stage_markdown` includes both model ids and stage names.

- [ ] **Step 2: Run → fails.**

- [ ] **Step 3: Implement** `evals/stage_compare.py`:
  - ref = `("gemini", os.getenv("REF_MODEL", "gemini-3-flash-preview"))`.
  - cand = `(os.getenv("PIPELINE_BACKEND", "ollama"), os.getenv("PIPELINE_MODEL", "qwen2.5:7b-instruct"))`.
  - load cases; run `ClassificationDimension` for ref and cand (each vs truth), `RequirementsDimension`,
    `ExtractionAgreementDimension`, `ConsistencyAgreementDimension`.
  - `build_stage_report(...)` → JSON; `render_stage_markdown(...)` → per-stage table; write
    `results/stage_compare_<timestamp>.json`; print markdown.
  - Note: `ClassificationDimension` currently takes no model args — extend its `score` to accept an
    optional `(backend, model)` (default env) so it can be run for both ref and cand. Keep existing
    callers working (default = env).

- [ ] **Step 4: Run → passes. Full suite green.**
- [ ] **Step 5: Commit** — `feat(evals): add stage_compare CLI for all-stage instruct-vs-gemini report`

---

### Task 5: Run the comparison + document (manual)

- [ ] **Step 1:** `cd api && set -a; source .env; set +a` then
  `OLLAMA_MAX_LOADED_MODELS=1 PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:7b-instruct uv run python -m evals.stage_compare`.
- [ ] **Step 2:** Append the per-stage results table to `evals/README.md`.
- [ ] **Step 3: Commit** — `docs(evals): record all-stage instruct-vs-gemini comparison`

---

## Self-Review
Spec coverage: backend threading (T1), requirements-vs-computed (T2), extraction/consistency agreement (T3), CLI report + latency (T4), run+doc (T5). Placeholders: none. Type consistency: dimensions take `(backend, model)` tuples; stage fns accept `*, backend, model`; `_SECTION`/`_REQUIRED` shared in scorer. ✓

## Execution Handoff
Inline via executing-plans. T1–T4 committable offline; T5 manual (Ollama + Vertex).
