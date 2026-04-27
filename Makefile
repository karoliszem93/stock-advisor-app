.PHONY: help install backend frontend dev test lint clean

help:
	@echo "Targets:"
	@echo "  install   Install backend (pip) and frontend (npm) deps"
	@echo "  backend   Run FastAPI dev server on :8000"
	@echo "  frontend  Run Vite dev server on :5173"
	@echo "  dev       Run backend and frontend concurrently"
	@echo "  test      Run backend tests"
	@echo "  lint      Run ruff on backend"
	@echo "  clean     Remove caches"

install:
	cd backend && python -m venv .venv && . .venv/bin/activate && pip install -e .[dev]
	cd frontend && npm install

backend:
	cd backend && . .venv/bin/activate && uvicorn app.main:app --reload --port 8000

frontend:
	cd frontend && npm run dev

dev:
	@echo "Run 'make backend' and 'make frontend' in two terminals."

test:
	cd backend && . .venv/bin/activate && pytest -q

lint:
	cd backend && . .venv/bin/activate && ruff check app tests

clean:
	find . -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .pytest_cache -prune -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name .ruff_cache -prune -exec rm -rf {} + 2>/dev/null || true
