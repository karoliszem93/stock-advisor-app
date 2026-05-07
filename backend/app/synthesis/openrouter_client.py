"""OpenRouter API client.

OpenRouter (https://openrouter.ai) proxies one API key to ~50+ LLMs from
every major provider (OpenAI, Anthropic, Google, Meta, Mistral, etc).
The API is OpenAI Chat Completions compatible — same endpoint shape, same
JSON-mode `response_format`, same usage block.

Why use it for this project:
  - Single key for everything.
  - One-line model swap to A/B test models.
  - Generally lower per-call cost than direct providers (no minimum prepay,
    just pay-as-you-go from OpenRouter credits).
  - Free-tier models exist (rate-limited, lower quality but $0).

Default model: deepseek/deepseek-v4-pro (1.6T MoE, 1M context, strong reasoning,
~$0.003/call — better quality than gpt-4o-mini at similar price).

Other good picks for analysis:
  - google/gemini-2.5-flash-lite        ~$0.0007/call (cheapest)
  - openai/gpt-4o-mini                  ~$0.001/call (well-tested fallback)
  - deepseek/deepseek-v4-pro            ~$0.003/call (recommended default)
  - anthropic/claude-haiku-4-5          ~$0.01/call (higher quality)
  - openai/gpt-4o                       ~$0.04/call (top quality)
  - anthropic/claude-sonnet-4-6         ~$0.05/call (top quality, deeper reasoning)

Get a key: https://openrouter.ai/keys
"""

from __future__ import annotations

import json
import logging
import time

import httpx

from app.config import get_settings
from app.synthesis.llm import LLMResponse

log = logging.getLogger(__name__)

API_URL = "https://openrouter.ai/api/v1/chat/completions"


class OpenRouterError(RuntimeError):
    """Raised when the API key is missing/invalid or the response can't be parsed."""


class OpenRouterClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
    ):
        s = get_settings()
        self.api_key = api_key or s.openrouter_api_key
        self.model = model or s.openrouter_model
        self.timeout = timeout or 120

    # ------------------------------------------------------------------
    def is_available(self) -> tuple[bool, str]:
        if not self.api_key:
            return False, "no OPENROUTER_API_KEY in .env"
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
            raise OpenRouterError("no OPENROUTER_API_KEY configured")

        # OpenAI's json_object mode requires the word "json" in the prompt.
        # Some routed models (Anthropic, Gemini through OpenRouter) honor it natively;
        # others need the explicit reminder. Belt + suspenders.
        strict_system = (
            system_prompt
            + "\n\nRespond with a single valid JSON object matching the schema. No markdown, no commentary."
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

        # OpenRouter optionally accepts these headers to identify your app
        # (shows up on https://openrouter.ai/activity). Helpful for usage tracking.
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "stock-advisor",
        }

        started = time.time()
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.post(API_URL, json=body, headers=headers)
            resp.raise_for_status()
            blob = resp.json()
        except httpx.HTTPStatusError as exc:
            try:
                err = exc.response.json().get("error", {})
                msg = err.get("message", "") or exc.response.text[:200]
            except Exception:  # noqa: BLE001
                msg = exc.response.text[:200]
            raise OpenRouterError(f"HTTP {exc.response.status_code}: {msg}") from exc
        except httpx.HTTPError as exc:
            raise OpenRouterError(f"transport error: {exc!r}") from exc
        except ValueError as exc:
            raise OpenRouterError(f"invalid JSON envelope: {exc!r}") from exc

        choices = blob.get("choices") or []
        if not choices:
            raise OpenRouterError(f"empty choices in response: {blob}")
        msg = choices[0].get("message") or {}
        # `content` is None when reasoning models spend their entire budget on
        # internal chain-of-thought without producing output. Fall back to
        # `reasoning` if needed; either way coerce away from None before strip.
        text = (msg.get("content") or msg.get("reasoning") or "").strip()

        # Strip stray markdown fences (some models add them despite json mode)
        if text.startswith("```"):
            text = text.removeprefix("```json").removeprefix("```").rstrip()
            if text.endswith("```"):
                text = text.removesuffix("```").rstrip()

        parsed: dict | None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            log.warning(
                "OpenRouter (%s) returned non-JSON content (%d chars): %.200s",
                self.model, len(text), text,
            )
            parsed = None

        usage = blob.get("usage") or {}
        eval_count = (
            int(usage.get("prompt_tokens", 0))
            + int(usage.get("completion_tokens", 0))
        )

        return LLMResponse(
            text=text,
            parsed=parsed,
            eval_count=eval_count or None,
            duration_ms=int((time.time() - started) * 1000),
        )
