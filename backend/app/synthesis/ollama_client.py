"""Tiny wrapper around the local Ollama HTTP API.

We only need two things:
  - generate_json(): chat-style call that returns JSON parsed into a dict.
                     Uses Ollama's `format: json` mode so the model can't
                     return prose-around-the-JSON.
  - is_available(): probe /api/tags and confirm our model is installed.

Ollama runs at localhost by default; configurable via OLLAMA_HOST in .env.
Timeout is generous (default 180s) because 14B-class models on CPU/Apple
Silicon can take 30–120s per substantial response.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)


class OllamaError(RuntimeError):
    """Raised when the daemon is unreachable, the model is missing, or the
    response cannot be parsed."""


@dataclass
class OllamaResponse:
    text: str
    parsed: dict | None
    eval_count: int | None
    duration_ms: int | None


class OllamaClient:
    def __init__(self, host: str | None = None, model: str | None = None, timeout: int | None = None):
        s = get_settings()
        self.host = (host or s.ollama_host).rstrip("/")
        self.model = model or s.ollama_model
        self.timeout = timeout or s.ollama_timeout_seconds

    # ------------------------------------------------------------------
    def is_available(self) -> tuple[bool, str]:
        try:
            with httpx.Client(timeout=5.0) as client:
                r = client.get(f"{self.host}/api/tags")
            r.raise_for_status()
            blob = r.json()
        except (httpx.HTTPError, ValueError) as exc:
            return False, f"daemon unreachable at {self.host}: {exc!r}"

        names = [m.get("name") for m in (blob.get("models") or []) if m.get("name")]
        if self.model in names:
            return True, f"OK ({self.model} installed)"
        # Try without tag (e.g. user has "qwen2.5:14b" but config says "qwen2.5:14b-instruct")
        wanted_base = self.model.split(":")[0]
        compatible = [n for n in names if n.split(":")[0] == wanted_base]
        if compatible:
            return False, f"daemon up but '{self.model}' not installed; have: {compatible}"
        return False, f"daemon up but no '{wanted_base}' models installed; available: {names}"

    # ------------------------------------------------------------------
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        seed: int | None = None,
    ) -> OllamaResponse:
        """Send a chat request constrained to JSON output. Returns parsed dict.

        Raises OllamaError on transport/parse failure.
        """
        body: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": temperature,
            },
        }
        if seed is not None:
            body["options"]["seed"] = seed
        if max_tokens is not None:
            body["options"]["num_predict"] = int(max_tokens)

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(f"{self.host}/api/chat", json=body)
            resp.raise_for_status()
            blob = resp.json()
        except httpx.HTTPError as exc:
            raise OllamaError(f"HTTP error from {self.host}: {exc!r}") from exc
        except ValueError as exc:
            raise OllamaError(f"Non-JSON response from Ollama: {exc!r}") from exc

        text = (blob.get("message") or {}).get("content") or ""
        parsed: dict | None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            log.warning("Ollama returned non-JSON content (will retry with strict reminder): %.200s", text)
            parsed = None
            # Caller can decide to retry with a stricter reminder.

        return OllamaResponse(
            text=text,
            parsed=parsed,
            eval_count=blob.get("eval_count"),
            duration_ms=int((blob.get("total_duration") or 0) / 1_000_000) or None,
        )
