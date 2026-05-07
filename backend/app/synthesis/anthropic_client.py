"""Anthropic Messages API client.

Uses raw httpx (no SDK dep) to call the public Messages API.
Authentication is via the ANTHROPIC_API_KEY .env variable.

Pricing notes (as of 2026):
  - claude-haiku-4-5-20251001 ~ $1/M input, $5/M output  (recommended default)
  - claude-sonnet-4-6        ~ $3/M input, $15/M output (higher quality)
  - claude-opus-4-6          ~ $15/M input, $75/M output (top quality, slowest)

Each per-ticker analysis call uses ~3–5K input + ~1K output tokens, so
Haiku ≈ $0.01/call, Sonnet ≈ $0.05/call.
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.config import get_settings
from app.synthesis.llm import LLMResponse

log = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicError(RuntimeError):
    """Raised when the API key is missing/invalid or the response can't be parsed."""


class AnthropicClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        s = get_settings()
        self.api_key = api_key or s.anthropic_api_key
        self.model = model or s.anthropic_model
        self.timeout = timeout or 120

    # ------------------------------------------------------------------
    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "no ANTHROPIC_API_KEY in .env"
        # We don't probe the API on every call — just trust the key.
        # Real validation happens on first use.
        return True, f"OK ({self.model})"

    # ------------------------------------------------------------------
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        seed: int | None = None,  # accepted for interface compatibility, not used
    ) -> LLMResponse:
        if not self.api_key:
            raise AnthropicError("no ANTHROPIC_API_KEY configured")

        # Reinforce JSON-only response (Claude is reliable about this when asked)
        strict_system = (
            system_prompt
            + "\n\nIMPORTANT: Respond with ONLY valid JSON matching the schema above. "
              "No markdown, no code fences, no prose around the JSON. Output a single JSON object."
        )

        body: dict = {
            "model": self.model,
            "max_tokens": int(max_tokens) if max_tokens else 1024,
            "system": strict_system,
            "messages": [{"role": "user", "content": user_prompt}],
            "temperature": float(temperature),
        }

        started = time.time()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(
                    API_URL,
                    json=body,
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": API_VERSION,
                        "content-type": "application/json",
                    },
                )
            resp.raise_for_status()
            blob = resp.json()
        except httpx.HTTPStatusError as exc:
            # Surface the API error message for easier debugging
            try:
                err = exc.response.json().get("error", {})
                msg = err.get("message", "") or exc.response.text[:200]
            except Exception:  # noqa: BLE001
                msg = exc.response.text[:200]
            raise AnthropicError(f"HTTP {exc.response.status_code}: {msg}") from exc
        except httpx.HTTPError as exc:
            raise AnthropicError(f"transport error: {exc!r}") from exc
        except ValueError as exc:
            raise AnthropicError(f"invalid JSON envelope: {exc!r}") from exc

        # Concatenate all text blocks (Claude returns content as a list)
        text = "".join(
            block.get("text", "")
            for block in (blob.get("content") or [])
            if block.get("type") == "text"
        ).strip()

        # Strip markdown code fences if any slipped through
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").rstrip()
            if text.endswith("```"):
                text = text.removesuffix("```").rstrip()

        parsed: dict | None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            log.warning(
                "Anthropic returned non-JSON content (%d chars): %.200s",
                len(text), text,
            )
            parsed = None

        usage = blob.get("usage") or {}
        eval_count = int(usage.get("input_tokens", 0)) + int(usage.get("output_tokens", 0))

        return LLMResponse(
            text=text,
            parsed=parsed,
            eval_count=eval_count or None,
            duration_ms=int((time.time() - started) * 1000),
        )
