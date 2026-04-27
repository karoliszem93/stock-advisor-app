# stock-advisor-app

Localhost stock investment advisor. Generates daily Buy / Avoid / Sell-short suggestions across **7 timeframes** (1w, 2w, 1m, 3m, 6m, 1y, 3y) and **4 risk profiles** (Conservative, Balanced, Growth-oriented, Aggressive) for a Trading 212 watchlist plus a curated ETF universe.

Companion repo: [`stock-advisor-data`](https://github.com/karoliszem93/stock-advisor-data) — daily snapshots, suggestions, and validations are committed there for an AI agent to read later.

## Architecture (high level)

```
┌──────────────────────────┐        ┌──────────────────┐
│ Frontend (Vite+React)    │  ◄──►  │ Backend (FastAPI)│
│ http://localhost:5173    │  /api  │ http://localhost │
│                          │        │     :8000        │
└──────────────────────────┘        └────────┬─────────┘
                                             │
                                  ┌──────────┼─────────────┐
                                  ▼          ▼             ▼
                           ┌──────────┐ ┌──────────┐ ┌──────────┐
                           │ SQLite   │ │APScheduler│ │ Ollama   │
                           │ working  │ │ 08:00 LTU │ │ LLM      │
                           │ DB       │ │ Mon-Fri   │ │ analyst  │
                           └──────────┘ └─────┬────┘ └──────────┘
                                              │
                                              ▼
                                     ┌─────────────────┐
                                     │ Daily pipeline  │
                                     │  • snapshot     │
                                     │  • analyze      │
                                     │  • synthesize   │
                                     │  • validate     │
                                     │  • commit data  │
                                     │    repo (PAT)   │
                                     └─────────────────┘
```

## Repo layout

```
stock-advisor-app/
├── backend/                   FastAPI + scheduler + analysis
│   ├── app/
│   │   ├── main.py            FastAPI entry point
│   │   ├── config.py          Settings via .env
│   │   ├── db.py              SQLAlchemy + SQLite
│   │   ├── scheduler.py       APScheduler (Europe/Vilnius)
│   │   ├── routes/            REST endpoints
│   │   ├── models/            ORM models
│   │   ├── services/          Pipeline orchestration
│   │   ├── providers/         Data providers (Phase 1)
│   │   ├── analysis/          Analysis modules (Phase 2)
│   │   ├── synthesis/         Suggestion generation (Phase 3)
│   │   ├── validation/        Validation loop (Phase 4)
│   │   └── git_publisher/     Pushes to data repo (Phase 6)
│   ├── tests/
│   ├── pyproject.toml
│   └── .env.example
└── frontend/                  Vite + React + TypeScript + Tailwind
    ├── src/
    │   ├── App.tsx
    │   ├── pages/
    │   ├── components/
    │   └── lib/api.ts
    ├── package.json
    └── vite.config.ts
```

## Quick start (development)

### Prerequisites

- Python 3.11+
- Node 20+
- [Ollama](https://ollama.com) (when the LLM synthesis layer ships in Phase 3)

### Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env       # fill in API keys as you collect them
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev                # opens http://localhost:5173
```

Frontend proxies `/api/*` to `localhost:8000`.

## Daily run

The scheduler triggers at **08:00 Europe/Vilnius, Monday–Friday**. At that time, US markets have closed the previous evening and EU/UK markets haven't opened — fresh data, actionable timing.

You can trigger a run manually from the UI or via:
```bash
curl -X POST http://localhost:8000/api/run/daily
```

## Configuration

All credentials live in `backend/.env` (gitignored). See `backend/.env.example` for the full list. The GitHub PAT used to push to `stock-advisor-data` is stored separately at `~/.config/stock-advisor/github_token` and is read at runtime by the git publisher — **never** placed in `.env` and never committed.

## Status

| Phase | Status | What |
|---|---|---|
| 0 — Scaffold | ✅ done | FastAPI + React + SQLite + APScheduler |
| 1 — Data providers | ⏳ pending | yfinance, Alpha Vantage, Finnhub, FMP, SimFin, NewsAPI, FRED, Reddit, EDGAR |
| 2 — Analysis modules | ⏳ pending | 12 modules: technical, fundamental, sentiment, etc. |
| 3 — Synthesis + LLM | ⏳ pending | Ollama-driven suggestion generation |
| 4 — Validation loop | ⏳ pending | Calibrate confidence from history |
| 5 — Frontend | ⏳ pending | Dashboard, suggestion detail, ticker view |
| 6 — Git commit pipeline | ⏳ pending | Publish to data repo |
| 7 — Backtest | ⏳ pending | 24-month retroactive run, initial weights |
| 8 — Polish | ⏳ pending | Notifications, docs, dry-run |
