# OCR Pre-Stage (self-hosted Qwen-VL)

The pre-stage runs before the Gemini orchestrator and extracts text from claim
documents so **no images are ever sent to a Gemini agent**.

## Local development (Ollama)

1. Install Ollama: https://ollama.com
2. Pull and run the VLM (7B recommended; use `:3b` if 16 GB RAM is tight):
   ```
   ollama run qwen2.5vl:7b
   ```
   Ollama serves an OpenAI-compatible API at http://localhost:11434.
3. Configure the API (defaults shown):
   ```
   OCR_BASE_URL=http://localhost:11434
   OCR_MODEL=qwen2.5vl:7b
   OCR_MAX_PDF_PAGES=10
   ```

## Production

Point `OCR_BASE_URL` at a Qwen-VL endpoint hosted inside your own GCP project
(Cloud Run + L4 GPU / GKE / Vertex). No code change — endpoint is config only.
A deployed Cloud Run backend cannot reach `localhost`.
