# Repository Guidelines

Concise guidance for contributing to the PostgreSQL MCP server in this repo.

## Project Structure & Module Organization
- Root: `postgres_server.py` (FastMCP server and tools), `README.md`, `requirements.txt`, `smithery.yaml`.
- Auth helpers: `oauth_companion.py`, `token_exchange_fix.py` (optional for OAuth flows).
- Tests: `tests/` (e.g., `tests/test_server_tools.py`).
- Local config (optional): `.env` with `POSTGRES_CONNECTION_STRING`, OAuth vars, etc.

## Build, Test, and Development Commands
- Create env: `python -m venv .venv && source .venv/bin/activate`
- Install runtime deps: `pip install -r requirements.txt`
- Install test deps: `pip install -r dev-requirements.txt`
- Run server (stdio): `python postgres_server.py`
- Run with DB: `POSTGRES_CONNECTION_STRING="postgresql://user:pass@host:5432/db" python postgres_server.py`
- Transport examples: `python postgres_server.py --transport sse --host 127.0.0.1 --port 8000`
- Run tests: `pytest -q`

## Coding Style & Naming Conventions
- Python 3.10+, PEP 8, 4‑space indent; type hints and short docstrings.
- Names: functions/vars `snake_case`; classes `PascalCase`; MCP tool names short `snake_case`.
- Logging: use the module `logger`; avoid PII.
- Optional formatting/linting: `ruff check .` then `black .`.

## Testing Guidelines
- Framework: `pytest` with files in `tests/` named `test_*.py`.
- No‑DSN behavior is required: without `POSTGRES_CONNECTION_STRING`, tools must return friendly empty/notice results (see `tests/test_server_tools.py`).
- Prefer disposable DBs or mocks for DB interactions.

## Typed Tools & Resources
- Preferred tools: `run_query(QueryInput)` and `run_query_json(QueryJSONInput)` with `row_limit` safeguards.
- Prompts (available as tools): `prompt_write_safe_select_tool`, `prompt_explain_plan_tips_tool`.
- Resource helpers: `list_table_resources`, `read_table_resource`; URIs like `table://{schema}/{table}`.

## Commit & Pull Request Guidelines
- Commits: conventional style (`feat:`, `fix:`, `chore:`, `docs:`), imperative and concise.
- PRs: include purpose/scope, before/after behavior, example commands/queries, and config changes (env vars, transport flags).
- Do not commit secrets; `.env` and credentials are ignored by `.gitignore`.

## Security & Configuration Tips
- Provide DB creds via `POSTGRES_CONNECTION_STRING`; prefer least‑privilege users and SSL (e.g., `?sslmode=require`).
- Safety toggles: `POSTGRES_READONLY=true`, `POSTGRES_STATEMENT_TIMEOUT_MS=5000`.
- Server should run safely without a DSN; keep graceful failure paths intact.
