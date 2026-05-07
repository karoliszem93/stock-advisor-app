"""OpenAI Chat Completions API client.

Uses raw httpx (no openai-sdk dep) to call /v1/chat/completions with
JSON-mode response_format. Authentication via OPENAI_API_KEY .env var.

Pricing notes (mid-2026 ballpark; verify on platform.openai.com):
  - gpt-4o-mini    ~ $0.15/M input, $0.60/M output  (recommended default)
  - gpt-4o         ~ $2.50/M input, $10/M output    (higher quality)
  - gpt-4.1-mini   variable                          (newer, often cheaper)

Each per-ticker analysis call uses ~3–5K input + ~1K output tokens, so
gpt-4o-mini ≈ $0.001–0.002 per call.
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.config import get_settings
from app.synthesis.llm import LLMResponse

log = logging.getLogger(__name__)

API_URL = "https://api.openai.com/v1/chat/completions"


class OpenAIError(RuntimeError):
    """Raised when the API key is missing/invalid or the response can't be parsed."""


class OpenAIClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        s = get_settings()
        self.api_key = api_key or s.openai_api_key
        self.model = model or s.openai_model
        self.timeout = timeout or 120

    # ------------------------------------------------------------------
    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "no OPENAI_API_KEY in .env"
        return True, f"OK ({self.model})"

    # ------------------------------------------------------------------
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        seed: int | None = None,
    ) -> LLMResponse:
        if not self.api_key:
            raise OpenAIError("no OPENAI_API_KEY configured")

        # OpenAI's json_object mode requires the word "json" somewhere in the
        # prompt. Our system prompt already mentions JSON, but we reinforce.
        strict_system = (
            system_prompt
            + "\n\nRespond with a single JSON object matching the schema. No markdown, no commentary."
        )

        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": strict_system},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": float(temperature),
        }
        if max_tokens:
            body["max_tokens"] = int(max_tokens)
        if seed is not None:
            body["seed"] = int(seed)

        started = time.time()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    API_URL,
                    json=body,
                    headers={
                        "Authorization": f"Bearer {self.api_key}",
                        "Content-Type": "application/json",
                    },
                )
            resp.raise_for_status()
            blob = resp.json()
        except httpx.HTTPStatusError as exc:
            try:
                err = exc.response.json().get("error", {})
                msg = err.get("message", "") or exc.response.text[:200]
            except Exception:  # noqa: BLE001
                msg = exc.response.text[:200]
            raise OpenAIError(f"HTTP {exc.response.status_code}: {msg}") from exc
        except httpx.HTTPError as exc:
            raise OpenAIError(f"transport error: {exc!r}") from exc
        except ValueError as exc:
            raise OpenAIError(f"invalid JSON envelope: {exc!r}") from exc

        choices = blob.get("choices") or []
        if not choices:
            raise OpenAIError(f"empty choices in response: {blob}")
        text = (choices[0].get("message") or {}).get("content") or ""
        text = text.strip()

        # Strip stray markdown fences (rare but happens)
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").rstrip()
            if text.endswith("```"):
                text = text.removesuffix("```").rstrip()

        parsed: dict | None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            log.warning("OpenAI returned non-JSON content (%d chars): %.200s", len(text), text)
            parsed = None

        usage = blob.get("usage") or {}
        eval_count = int(usage.get("prompt_tokens", 0)) + int(usage.get("completion_tokens", 0))

        return LLMResponse(
            text=text,
            parsed=parsed,
            eval_count=eval_count or None,
            duration_ms=int((time.time() - started) * 1000),
        )
