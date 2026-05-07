"""LLM provider abstraction.

Two backends supported:
  - "anthropic"  — Claude via the Anthropic Messages API (cloud, fast, paid)
  - "ollama"     — local Ollama (free, slow on laptop CPUs)

Set LLM_PROVIDER in .env to switch. Both clients implement the same
interface so the rest of the synthesis layer doesn't care which one runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.config import get_settings


@dataclass
class LLMResponse:
    """Common response shape returned by both Ollama and Anthropic clients."""
    text: str
    parsed: dict | None
    eval_count: int | None        # tokens consumed (where reported)
    duration_ms: int | None       # client-side timing (where measurable)


class LLMClient(Protocol):
    """Protocol both AnthropicClient and OllamaClient satisfy."""
    model: str

    def is_available(self) -> tuple[bool, str]: ...

    def generate_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        seed: int | None = None,
    ) -> LLMResponse: ...


def get_llm_client() -> LLMClient:
    """Factory — returns the configured backend's client."""
    s = get_settings()
    provider = (s.llm_provider or "ollama").lower()
    if provider == "openrouter":
        from app.synthesis.openrouter_client import OpenRouterClient
        return OpenRouterClient()
    if provider == "gemini":
        from app.synthesis.gemini_client import GeminiClient
        return GeminiClient()
    if provider == "openai":
        from app.synthesis.openai_client import OpenAIClient
        return OpenAIClient()
    if provider == "anthropic":
        from app.synthesis.anthropic_client import AnthropicClient
        return AnthropicClient()
    if provider == "ollama":
        from app.synthesis.ollama_client import OllamaClient
        return OllamaClient()
    raise ValueError(
        f"Unknown LLM_PROVIDER: {provider}. "
        "Use 'openrouter', 'gemini', 'openai', 'anthropic', or 'ollama'."
    )
