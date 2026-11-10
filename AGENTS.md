# Agent guide

Statutory RAG service for disability rights in Uzbekistan (FastAPI, SQLite FTS5, LanceDB, OpenRouter).

## Commands

- Install: `pip install -r requirements-dev.txt`
- Lint: `ruff check .`
- Test: `pytest -q` (offline; uses a temporary store and mocked external APIs)
- Run: `python -m uvicorn src.api.app:app --host 0.0.0.0 --port 8000 --reload`

## Layout

- `src/api` - FastAPI app, routes, auth, rate limiting, cache
- `src/nlp`, `src/retrieval`, `src/generation` - query analysis, hybrid retrieval, answer generation and citation validation
- `src/ingestion`, `scripts/` - corpus building from Lex.uz and huquqplus.uz
- `src/gateway`, `src/editorial`, `src/agents` - partner API, curated Q&A, agentic pipeline
- `src/admin/static` - public page and admin dashboard (plain JS, no build step)
- `tests/` - pytest suite

## Rules

- Never write statutory text by hand; it comes from the ingestion pipeline.
- Never touch `data/store` or `data/cache` from tests.
- Lint and tests must pass before a change is done.
