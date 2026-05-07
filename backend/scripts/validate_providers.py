#!/usr/bin/env python3
"""Validate every configured data provider's API key with a small, free request.

Run from the backend directory:
    cd ~/Documents/STOCK/stock-advisor-app/backend
    python3 scripts/validate_providers.py

Uses only the Python standard library — no pip install needed. Reads keys
from ./.env (relative to backend/), tests each provider, prints concise
pass/fail per provider, and exits 0 if all configured providers passed.
"""

from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ---- .env loading -----------------------------------------------------------

def load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        print(f"FATAL: {path} not found. Run from backend/ directory.")
        sys.exit(2)
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


# ---- HTTP helper ------------------------------------------------------------

def http_json(url: str, headers: dict | None = None, timeout: int = 15) -> tuple[int, dict | list | None, str]:
    """Return (status, json_or_none, raw_text)."""
    req = urllib.request.Request(url, headers=headers or {})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.status, json.loads(raw), raw
            except json.JSONDecodeError:
                return resp.status, None, raw
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        try:
            return e.code, json.loads(body), body
        except json.JSONDecodeError:
            return e.code, None, body
    except (urllib.error.URLError, OSError) as e:
        return 0, None, f"network: {e!r}"


# ---- per-provider checks ----------------------------------------------------

def check_yfinance() -> tuple[bool, str]:
    """yfinance has no key, but we sanity-check Yahoo's chart endpoint reachability."""
    url = "https://query1.finance.yahoo.com/v8/finance/chart/AAPL?range=5d&interval=1d"
    status, data, raw = http_json(url, headers={"User-Agent": "stock-advisor-validator/0.1"})
    if status == 200 and data and "chart" in data:
        return True, "Yahoo chart reachable"
    return False, f"status={status} body={raw[:140]}"


def check_edgar(env: dict) -> tuple[bool, str]:
    """SEC EDGAR — no key, requires identifying User-Agent."""
    ua = env.get("SEC_EDGAR_USER_AGENT") or "stock-advisor karolis.zem93@gmail.com"
    url = "https://www.sec.gov/files/company_tickers.json"
    status, data, raw = http_json(url, headers={"User-Agent": ua, "Accept": "application/json"})
    if status == 200 and isinstance(data, dict) and len(data) > 1000:
        return True, f"OK ({len(data)} ticker entries)"
    return False, f"status={status} body={raw[:140]}"


def check_fred(env: dict) -> tuple[bool, str]:
    key = env.get("FRED_API_KEY")
    if not key:
        return False, "no key in .env"
    url = (
        "https://api.stlouisfed.org/fred/series/observations"
        f"?series_id=DGS10&api_key={key}&file_type=json&limit=1&sort_order=desc"
    )
    status, data, raw = http_json(url)
    if status == 200 and isinstance(data, dict) and data.get("observations"):
        last = data["observations"][-1]
        return True, f"OK (DGS10={last.get('value')} on {last.get('date')})"
    if status == 200 and isinstance(data, dict) and "error_message" in str(data):
        return False, f"key rejected: {data}"
    return False, f"status={status} body={raw[:160]}"


def check_finnhub(env: dict) -> tuple[bool, str]:
    key = env.get("FINNHUB_API_KEY")
    if not key:
        return False, "no key in .env"
    url = f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}"
    status, data, raw = http_json(url)
    if status == 200 and isinstance(data, dict) and "c" in data:
        if data.get("c") == 0 and data.get("d") is None:
            return False, f"key likely invalid (zero quote): {data}"
        return True, f"OK (AAPL c={data.get('c')}, t={data.get('t')})"
    return False, f"status={status} body={raw[:160]}"


def check_fmp(env: dict) -> tuple[bool, str]:
    key = env.get("FMP_API_KEY")
    if not key:
        return False, "no key in .env"
    # New "Stable" API (post-2024 migration). The old /api/v3/profile/{ticker}
    # is paid-only for new accounts.
    url = f"https://financialmodelingprep.com/stable/profile?symbol=AAPL&apikey={key}"
    status, data, raw = http_json(url)
    if status == 200 and isinstance(data, list) and data:
        p = data[0]
        return True, f"OK ({p.get('symbol')} {p.get('companyName')} ${p.get('price')})"
    if status == 200 and isinstance(data, dict) and data:
        # Some endpoints return single-object responses
        return True, f"OK ({data.get('symbol', 'AAPL')} {data.get('companyName', '')})"
    if isinstance(data, dict) and "Error Message" in data:
        return False, f"rejected: {data['Error Message'][:120]}"
    return False, f"status={status} body={raw[:160]}"


def check_alphavantage(env: dict) -> tuple[bool, str]:
    key = env.get("ALPHAVANTAGE_API_KEY")
    if not key:
        return False, "no key in .env"
    url = (
        "https://www.alphavantage.co/query?function=GLOBAL_QUOTE&symbol=AAPL"
        f"&apikey={key}"
    )
    status, data, raw = http_json(url)
    if status == 200 and isinstance(data, dict):
        if "Global Quote" in data and data["Global Quote"]:
            q = data["Global Quote"]
            return True, f"OK (AAPL price={q.get('05. price')})"
        if "Note" in data:
            return False, f"rate-limited: {data['Note'][:120]}"
        if "Information" in data:
            return False, f"info: {data['Information'][:120]}"
        if "Error Message" in data:
            return False, f"key rejected: {data['Error Message']}"
    return False, f"status={status} body={raw[:160]}"


def check_newsapi(env: dict) -> tuple[bool, str]:
    key = env.get("NEWSAPI_API_KEY")
    if not key:
        return False, "no key in .env"
    url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize=1&apiKey={key}"
    status, data, raw = http_json(url)
    if status == 200 and isinstance(data, dict) and data.get("status") == "ok":
        n = data.get("totalResults", 0)
        return True, f"OK ({n} top US headlines available)"
    if isinstance(data, dict) and data.get("message"):
        return False, f"status={status}: {data['message']}"
    return False, f"status={status} body={raw[:160]}"


def check_simfin(env: dict) -> tuple[bool, str]:
    key = env.get("SIMFIN_API_KEY")
    if not key:
        return False, "no key in .env"
    # SimFin v3 uses Authorization: api-key <key>
    url = "https://prod.simfin.com/api/v3/companies/general/compact?ticker=AAPL"
    status, data, raw = http_json(url, headers={"Authorization": f"api-key {key}"})
    if status == 200 and data:
        return True, f"OK (compact: {len(raw)} bytes returned)"
    if status in (401, 403):
        return False, f"auth rejected (status={status}) body={raw[:160]}"
    return False, f"status={status} body={raw[:160]}"


def check_openrouter(env: dict) -> tuple[bool, str]:
    """Verify the OpenRouter API key with a tiny request."""
    if (env.get("LLM_PROVIDER") or "").lower() != "openrouter":
        return None, "skipped — LLM_PROVIDER is not 'openrouter'"
    key = env.get("OPENROUTER_API_KEY")
    if not key:
        return False, "no key in .env"
    model = env.get("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with valid JSON only."},
            {"role": "user", "content": 'Reply with this JSON: {"reply": "PONG"}'},
        ],
        "response_format": {"type": "json_object"},
        # Reasoning models (DeepSeek V4 Pro etc.) spend tokens on internal
        # chain-of-thought before output. Generous budget so the probe lands
        # actual content rather than coming back with content=null.
        "max_tokens": 512,
    }).encode()
    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5173",
            "X-Title": "stock-advisor",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            blob = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return False, f"status={e.code} body={body_text[:200]}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, f"{e!r}"

    choices = blob.get("choices") or []
    msg = choices[0].get("message", {}) if choices else {}
    # `content` may be None for reasoning models if max_tokens was tight.
    # Fall back to `reasoning` (the model's chain-of-thought) so we still
    # confirm the API call landed.
    text = (msg.get("content") or msg.get("reasoning") or "").strip()
    usage = blob.get("usage") or {}
    return True, (
        f"OK ({model}; reply='{text[:30]}'; "
        f"tokens={usage.get('prompt_tokens')}/{usage.get('completion_tokens')})"
    )


def check_gemini(env: dict) -> tuple[bool, str]:
    """Verify the Gemini API key with a tiny request."""
    provider = (env.get("LLM_PROVIDER") or "").lower()
    if provider != "gemini":
        return None, f"skipped — LLM_PROVIDER is '{provider}', not 'gemini'"
    key = env.get("GEMINI_API_KEY")
    if not key:
        return False, "no key in .env"
    model = env.get("GEMINI_MODEL", "gemini-2.5-flash")
    body = json.dumps({
        "system_instruction": {"parts": [{"text": "Respond with valid JSON."}]},
        "contents": [{"role": "user", "parts": [{"text": 'Reply with this JSON: {"reply": "PONG"}'}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "maxOutputTokens": 32,
        },
    }).encode()
    req = urllib.request.Request(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        data=body,
        headers={
            "x-goog-api-key": key,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            blob = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return False, f"status={e.code} body={body_text[:200]}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, f"{e!r}"
    text = ""
    for cand in (blob.get("candidates") or []):
        for part in (cand.get("content") or {}).get("parts", []):
            text += part.get("text", "")
    usage = blob.get("usageMetadata") or {}
    return True, (
        f"OK ({model}; reply='{text.strip()[:30]}'; "
        f"tokens={usage.get('promptTokenCount')}/{usage.get('candidatesTokenCount')})"
    )


def check_openai(env: dict) -> tuple[bool, str]:
    """Verify the OpenAI API key with a tiny request."""
    if (env.get("LLM_PROVIDER") or "").lower() != "openai":
        return None, "skipped — LLM_PROVIDER is not 'openai'"
    key = env.get("OPENAI_API_KEY")
    if not key:
        return False, "no key in .env"
    model = env.get("OPENAI_MODEL", "gpt-4o-mini")
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with valid JSON only."},
            {"role": "user", "content": 'Reply with this JSON: {"reply": "PONG"}'},
        ],
        "response_format": {"type": "json_object"},
        "max_tokens": 16,
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            blob = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return False, f"status={e.code} body={body_text[:200]}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, f"{e!r}"

    choices = blob.get("choices") or []
    text = (choices[0].get("message", {}).get("content", "") if choices else "")
    usage = blob.get("usage") or {}
    return True, (
        f"OK ({model}; reply='{text.strip()[:30]}'; "
        f"tokens={usage.get('prompt_tokens')}/{usage.get('completion_tokens')})"
    )


def check_anthropic(env: dict) -> tuple[bool, str]:
    """Verify the Anthropic API key with a tiny request."""
    if (env.get("LLM_PROVIDER") or "").lower() != "anthropic":
        return None, "skipped — LLM_PROVIDER is not 'anthropic'"
    key = env.get("ANTHROPIC_API_KEY")
    if not key:
        return False, "no key in .env"
    model = env.get("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    body = json.dumps({
        "model": model,
        "max_tokens": 8,
        "messages": [{"role": "user", "content": "Say only the word PONG."}],
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            blob = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        return False, f"status={e.code} body={body_text[:200]}"
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, f"{e!r}"

    text = "".join(b.get("text", "") for b in (blob.get("content") or []) if b.get("type") == "text")
    usage = blob.get("usage") or {}
    return True, f"OK ({model}; reply='{text.strip()[:30]}'; tokens={usage.get('input_tokens')}/{usage.get('output_tokens')})"


def check_ollama(env: dict) -> tuple[bool, str]:
    """Verify the Ollama daemon is running and the configured model is installed."""
    if (env.get("LLM_PROVIDER") or "ollama").lower() != "ollama":
        return None, "skipped — LLM_PROVIDER is not 'ollama'"
    host = env.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    want_model = env.get("OLLAMA_MODEL", "qwen2.5:14b")
    try:
        with urllib.request.urlopen(f"{host}/api/tags", timeout=5) as resp:
            blob = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, f"daemon unreachable at {host}: {e!r}"

    models = [m.get("name") for m in (blob.get("models") or []) if m.get("name")]
    if want_model in models:
        return True, f"OK (daemon up, {want_model} installed; {len(models)} models total)"
    if any(m.split(":")[0] == want_model.split(":")[0] for m in models):
        return False, f"daemon up but {want_model} missing; have {models}"
    return False, f"daemon up but no model installed; pull with: ollama pull {want_model}"


def check_reddit(env: dict) -> tuple[bool, str]:
    cid = env.get("REDDIT_CLIENT_ID")
    csec = env.get("REDDIT_CLIENT_SECRET")
    if not (cid and csec):
        return None, "skipped — no credentials"
    import base64
    auth = base64.b64encode(f"{cid}:{csec}".encode()).decode()
    body = "grant_type=client_credentials"
    req = urllib.request.Request(
        "https://www.reddit.com/api/v1/access_token",
        data=body.encode(),
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": env.get("REDDIT_USER_AGENT", "stock-advisor-validator/0.1"),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
            if data.get("access_token"):
                return True, "OK (token issued)"
            return False, f"unexpected: {data}"
    except urllib.error.HTTPError as e:
        return False, f"status={e.code} {e.read().decode('utf-8', errors='replace')[:160]}"
    except (urllib.error.URLError, OSError) as e:
        return False, f"network: {e!r}"


# ---- main -------------------------------------------------------------------

def main() -> int:
    env_path = Path(".env")
    env = load_env(env_path)

    checks = [
        ("yfinance",     lambda: check_yfinance()),
        ("edgar",        lambda: check_edgar(env)),
        ("fred",         lambda: check_fred(env)),
        ("finnhub",      lambda: check_finnhub(env)),
        ("fmp",          lambda: check_fmp(env)),
        ("alphavantage", lambda: check_alphavantage(env)),
        ("newsapi",      lambda: check_newsapi(env)),
        ("simfin",       lambda: check_simfin(env)),
        ("reddit",       lambda: check_reddit(env)),
        ("openrouter",   lambda: check_openrouter(env)),
        ("gemini",       lambda: check_gemini(env)),
        ("openai",       lambda: check_openai(env)),
        ("anthropic",    lambda: check_anthropic(env)),
        ("ollama",       lambda: check_ollama(env)),
    ]

    failures: list[str] = []
    skipped: list[str] = []
    print()
    for name, fn in checks:
        try:
            ok, msg = fn()
        except Exception as exc:  # noqa: BLE001
            ok, msg = False, f"crashed: {exc!r}"
        if ok is True:
            print(f"  ✅ {name:<14} {msg}")
        elif ok is None:
            print(f"  ⏭  {name:<14} {msg}")
            skipped.append(name)
        else:
            print(f"  ❌ {name:<14} {msg}")
            failures.append(name)

    print()
    if failures:
        print(f"=== {len(failures)} failure(s): {', '.join(failures)} ===")
        return 1
    if skipped:
        print(f"=== all configured providers OK ({len(skipped)} skipped: {', '.join(skipped)}) ===")
    else:
        print("=== all providers OK ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
