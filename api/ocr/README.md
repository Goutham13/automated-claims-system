# OCR Pre-Stage (self-hosted Qwen-VL)

The pre-stage runs before the Gemini orchestrator and extracts text from claim
documents so **no images are ever sent to a Gemini agent**.

## Local development (Ollama)

1. Install Ollama (use the prebuilt app/cask, NOT `brew install ollama` — the
   source formula can ship without the `llama-server` runner):
   ```
   brew install --cask ollama
   open -a Ollama
   ```
2. Pull the VLM (7B recommended on 16 GB; use `qwen2.5vl:3b` if RAM is tight):
   ```
   ollama pull qwen2.5vl:7b
   ```
   Ollama serves an OpenAI-compatible API at http://localhost:11434.

3. **Context window — required.** A rasterized document page tokenizes to
   ~4,000 tokens, which exceeds Ollama's default 4096-token context once the OCR
   system prompt is added (you'll get HTTP 400 `exceed_context_size_error`).
   Create a derived model with a larger context (same weights — no extra disk):
   ```
   printf 'FROM qwen2.5vl:7b\nPARAMETER num_ctx 8192\n' > Modelfile.ocr
   ollama create qwen2.5vl-ocr -f Modelfile.ocr
   ```
   (Alternative: start the server with `OLLAMA_CONTEXT_LENGTH=8192 ollama serve`.)

4. Configure the API:
   ```
   OCR_BASE_URL=http://localhost:11434
   OCR_MODEL=qwen2.5vl-ocr      # the 8192-context model from step 3
   OCR_MAX_PDF_PAGES=10
   OCR_RENDER_DPI=200           # lower to reduce image tokens (and accuracy)
   ```

## Production

Point `OCR_BASE_URL` at a Qwen-VL endpoint hosted inside your own GCP project
(Cloud Run + L4 GPU / GKE / Vertex). No code change — endpoint is config only.
A deployed Cloud Run backend cannot reach `localhost`.

The same context requirement applies: launch the serving framework with enough
context for a full page image plus the prompt (e.g. vLLM `--max-model-len 8192`).
