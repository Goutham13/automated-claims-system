# CLAUDE.md

**Start here:** read [`ROADMAP.md`](ROADMAP.md) — it has the full project context, current
architecture, what's been built, key decisions/findings, and the scoped next steps.

## Core principle
**LLMs for understanding, Python for decisions.** LLMs read/classify/extract from documents;
deterministic Python computes every financial decision. Never let an LLM compute money.

## Hard constraints (current direction)
- **Fully self-hosted, no external LLM APIs.** OCR + all understanding stages run on local **Ollama**
  (`qwen2.5vl-ocr` for OCR, `qwen2.5:14b` for stages). Do not (re)introduce Gemini/Vertex/`google-genai`/`google-adk`.
- The pipeline is a **deterministic Python orchestrator** (`api/pipeline/orchestrator.py`) — no LLM
  orchestrator, no ADK in the request path.

## Layout
- `api/` — FastAPI backend (`uv`). Pipeline in `api/pipeline/`, OCR in `api/ocr/`, stage prompts +
  schemas in `api/agents/`, eval harness in `api/evals/`.
- `ui/` — React/TanStack frontend (`npm`).
- `docs/superpowers/{specs,plans}/` — design docs and implementation plans.

## Commands
- API tests: `cd api && uv run pytest -q`
- Run API: `cd api && uv run uvicorn main:app --port 8000`
- Eval comparison: `cd api && PIPELINE_BACKEND=ollama PIPELINE_MODEL=qwen2.5:14b uv run python -m evals.stage_compare`
