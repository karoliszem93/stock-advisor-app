"""Application configuration loaded from environment variables.

Settings are loaded once at import time and exposed via `get_settings()`.
A missing optional key (e.g. an API key not yet provisioned) is allowed —
downstream providers gate their usage on whether their key is present.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ----- runtime -----
    app_env: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    sqlite_path: str = "./data/stock-advisor.db"
    timezone: str = "Europe/Vilnius"
    schedule_hour: int = 8
    schedule_minute: int = 0

    # ----- data publishing -----
    data_repo_path: str = "../../stock-advisor-data"
    data_repo_remote: str = "origin"
    data_repo_branch: str = "main"
    github_token_file: str = "~/.config/stock-advisor/github_token"
    github_owner: str = "karoliszem93"
    github_data_repo: str = "stock-advisor-data"
    git_author_name: str = "Stock Advisor Bot"
    git_author_email: str = "karolis.zem93@gmail.com"

    # ----- llm -----
    ollama_host: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:14b-instruct"
    ollama_timeout_seconds: int = 180

    # ----- providers -----
    alphavantage_api_key: str | None = None
    finnhub_api_key: str | None = None
    fmp_api_key: str | None = None
    simfin_api_key: str | None = None
    newsapi_api_key: str | None = None
    fred_api_key: str | None = None
    reddit_client_id: str | None = None
    reddit_client_secret: str | None = None
    reddit_user_agent: str = "stock-advisor/0.1 by karoliszem93"
    sec_edgar_user_agent: str = "stock-advisor/0.1 karolis.zem93@gmail.com"

    # ----- analysis defaults -----
    base_currency: str = "EUR"
    lt_capital_gains_rate: float = 0.15
    lt_dividend_tax_rate: float = 0.15
    lt_annual_cg_exemption_eur: float = 500.0

    # ----- derived -----
    @property
    def github_token_path(self) -> Path:
        return Path(self.github_token_file).expanduser()

    @property
    def data_repo_dir(self) -> Path:
        # resolve relative to the backend/ directory (the cwd when running uvicorn)
        return Path(self.data_repo_path).expanduser().resolve()

    @property
    def db_path(self) -> Path:
        p = Path(self.sqlite_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def github_token(self) -> str | None:
        """Read the GitHub PAT from disk if available. Returns None if missing."""
        p = self.github_token_path
        if not p.exists():
            return None
        try:
            return p.read_text(encoding="utf-8").strip()
        except OSError:
            return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
