"""HTTP client for a self-hosted Qwen-VL OCR endpoint (Ollama OpenAI-compatible)."""

from __future__ import annotations

import base64
import os
import time

import httpx

OCR_SYSTEM_PROMPT = """You are an OCR transcription engine for medical claim documents.

Rules (follow exactly):
- Transcribe ONLY text that is visibly present in the image.
- Do NOT guess missing, blurry, or partially obscured tokens.
- Do NOT use outside knowledge or context from other documents.
- For any illegible region, write [UNREADABLE] instead of inventing content.
- If the image is mostly blank, return little or no text — do not pad.
- Output PLAIN TEXT only. No commentary, no markdown, no explanations.
"""


class OcrUnavailableError(RuntimeError):
    """Raised when the OCR service cannot be reached (connection-level failure)."""


class OcrClient:
    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float = 120.0,
        retry_backoff: float = 2.0,
    ) -> None:
        self.base_url = (base_url or os.getenv("OCR_BASE_URL", "http://localhost:11434")).rstrip("/")
        self.model = model or os.getenv("OCR_MODEL", "qwen2.5vl:7b")
        self.timeout = timeout
        self.retry_backoff = retry_backoff

    def ocr_image(self, png_bytes: bytes) -> str:
        """Transcribe a single PNG image to text. One retry on transient failure."""
        b64 = base64.b64encode(png_bytes).decode("ascii")
        payload = {
            "model": self.model,
            "temperature": 0,
            "stream": False,
            "messages": [
                {"role": "system", "content": OCR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe this document image."},
                        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                },
            ],
        }
        url = f"{self.base_url}/v1/chat/completions"

        last_exc: Exception | None = None
        for attempt in range(2):  # initial try + one retry
            try:
                resp = httpx.post(url, json=payload, timeout=self.timeout)
                if resp.status_code >= 500:
                    last_exc = httpx.HTTPStatusError(
                        "server error", request=resp.request, response=resp
                    )
                    if attempt == 0:
                        time.sleep(self.retry_backoff)
                        continue
                    raise OcrUnavailableError(f"OCR server error {resp.status_code}")
                resp.raise_for_status()
                data = resp.json()
                return (data["choices"][0]["message"]["content"] or "").strip()
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                last_exc = exc
                if attempt == 0:
                    time.sleep(self.retry_backoff)
                    continue
                raise OcrUnavailableError(str(exc)) from exc

        raise OcrUnavailableError(str(last_exc))  # defensive; not normally reached
