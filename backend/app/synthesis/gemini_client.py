"""Google Gemini API client.

Uses raw httpx (no google-genai SDK dep) to call the v1beta
generateContent endpoint. Authentication via the GEMINI_API_KEY .env var.

Why Gemini for this project: free tier is generous enough that a daily
run of ~30 ticker analyses costs $0/month for casual use.

Pricing notes (mid-2026 ballpark; verify on ai.google.dev/pricing):
  - gemini-2.5-flash       Free tier covers ~250 req/day. Paid tier also
                           cheap. Recommended default.
  - gemini-2.5-flash-lite  Even cheaper, free tier ~1000 req/day.
  - gemini-2.5-pro         Higher quality, smaller free quota.

Endpoint: POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
Auth: x-goog-api-key header.

Structured-output JSON: we request responseMimeType=application/json so
the model is constrained to emit a single JSON object.
"""

from __future__ import annotations

import json
import logging
import re
import time

import httpx

from app.config import get_settings
from app.synthesis.llm import LLMResponse

log = logging.getLogger(__name__)

API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiError(RuntimeError):
    """Raised when the API key is missing/invalid or the response can't be parsed."""


def _retry_after_seconds(message: str) -> float | None:
    """Parse 'Please retry in 23.5s' from the 429 message body."""
    m = re.search(r"retry in ([\d.]+)s", message or "")
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            pass
    return None


class GeminiClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        s = get_settings()
        self.api_key = api_key or s.gemini_api_key
        self.model = model or s.gemini_model
        self.timeout = timeout or 120

    # ------------------------------------------------------------------
    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "no GEMINI_API_KEY in .env"
        return True, f"OK ({self.model})"

    # ------------------------------------------------------------------
    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        seed: int | None = None,  # accepted for interface compat; Gemini supports via generationConfig
    ) -> LLMResponse:
        if not self.api_key:
            raise GeminiError("no GEMINI_API_KEY configured")

        body: dict = {
            "system_instruction": {
                "parts": [{"text": system_prompt
                                  + "\n\nRespond with a single JSON object matching the schema. No markdown, no commentary."}],
            },
            "contents": [
                {"role": "user", "parts": [{"text": user_prompt}]},
            ],
            "generationConfig": {
                "temperature": float(temperature),
                "responseMimeType": "application/json",
                # Disable Flash 2.5's thinking tokens — they count against
                # maxOutputTokens and our response gets truncated mid-string.
                # We don't need internal reasoning for structured output.
                "thinkingConfig": {"thinkingBudget": 0},
            },
        }
        # Default to a generous 2048 if caller didn't specify; Flash structured
        # responses often need more room than 900 once the JSON is fleshed out.
        body["generationConfig"]["maxOutputTokens"] = int(max_tokens) if max_tokens else 2048
        if seed is not None:
            body["generationConfig"]["seed"] = int(seed)

        url = f"{API_BASE}/{self.model}:generateContent"
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

        started = time.time()
        # Retry policy: 503 transient errors get exponential backoff;
        # 429 quota errors honor the server's suggested retry-after.
        MAX_503_RETRIES = 3
        backoff = 4.0
        attempt_503 = 0
        attempt_429 = 0

        while True:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.post(url, json=body, headers=headers)
                resp.raise_for_status()
                blob = resp.json()
                break
            except httpx.HTTPStatusError as exc:
                code = exc.response.status_code
                try:
                    err = exc.response.json().get("error", {})
                    msg = err.get("message", "") or exc.response.text[:300]
                except Exception:  # noqa: BLE001
                    msg = exc.response.text[:300]

                if code == 503 and attempt_503 < MAX_503_RETRIES:
                    attempt_503 += 1
                    log.info("Gemini 503 (attempt %d/%d) — sleeping %.1fs",
                             attempt_503, MAX_503_RETRIES, backoff)
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                if code == 429 and attempt_429 < 1:
                    attempt_429 += 1
                    wait = _retry_after_seconds(msg) or 30.0
                    log.info("Gemini 429 quota — sleeping %.1fs then retrying", wait)
                    time.sleep(wait + 0.5)
                    continue

                raise GeminiError(f"HTTP {code}: {msg}") from exc
            except httpx.HTTPError as exc:
                raise GeminiError(f"transport error: {exc!r}") from exc
            except ValueError as exc:
                raise GeminiError(f"invalid JSON envelope: {exc!r}") from exc

        # Gemini returns candidates[].content.parts[].text — concatenate text parts
        text = ""
        for cand in (blob.get("candidates") or []):
            content = cand.get("content") or {}
            for part in (content.get("parts") or []):
                text += part.get("text", "")
        text = text.strip()

        # Strip stray markdown fences (rare with json mime type)
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").rstrip()
            if text.endswith("```"):
                text = text.removesuffix("```").rstrip()

        parsed: dict | None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            log.warning("Gemini returned non-JSON content (%d chars): %.200s", len(text), text)
            parsed = None

        usage = blob.get("usageMetadata") or {}
        eval_count = int(usage.get("totalTokenCount", 0)) or None

        return LLMResponse(
            text=text,
            parsed=parsed,
            eval_count=eval_count,
            duration_ms=int((time.time() - started) * 1000),
        )
