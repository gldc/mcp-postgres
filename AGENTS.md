# Repository Guidelines

Concise guidance for contributing to the PostgreSQL MCP server in this repo.

## Project Structure & Module Organization
- Root: `postgres_server.py` (FastMCP server and tools), `README.md`, `requirements.txt`, `smithery.yaml`.
- Tests: `tests/test_tools.py` (unit), `tests/test_integration.py` (requires DB).
- Config: `.env.example`, `permissions.yaml.example`, `railway.toml`, `smithery.yaml`.

## Build, Test, and Development Commands
- Create env: `python -m venv .venv && source .venv/bin/activate`
- Install runtime deps: `pip install -r requirements.txt`
- Install test deps: `pip install -r dev-requirements.txt`
- Run server (stdio): `python postgres_server.py --conn "postgresql://user:pass@host:5432/db"`
- Run server (HTTP): `python postgres_server.py --transport streamable-http --host 127.0.0.1 --port 8000`
- Run tests: `pytest -q`
- Lint: `ruff check .`

## Coding Style & Naming Conventions
- Python 3.10+, PEP 8, 4-space indent; type hints and short docstrings.
- Names: functions/vars `snake_case`; classes `PascalCase`; MCP tool names short `snake_case`.
- Logging: use the module `logger`; avoid PII.

## Testing Guidelines
- Framework: `pytest` + `pytest-asyncio` with files in `tests/` named `test_*.py`.
- No-DSN behavior is required: without `DATABASE_URL`, tools must return friendly empty/notice results.
- Integration tests are skipped unless `DATABASE_URL` is set.

## Tools & Resources
- Tools: `query`, `list_schemas`, `list_tables`, `describe_table`, `get_foreign_keys`, `find_relationships`, `server_info`, `db_identity`.
- Resources: `table://{schema}/{table}` — reads up to 100 rows.
- Prompts: `write_safe_select`, `explain_plan_tips`.

## Commit & Pull Request Guidelines
- Commits: conventional style (`feat:`, `fix:`, `chore:`, `docs:`), imperative and concise.
- PRs: include purpose/scope, before/after behavior, example commands/queries, and config changes.
- Do not commit secrets; `.env` and credentials are ignored by `.gitignore`.

## Security & Configuration Tips
- Provide DB creds via `DATABASE_URL`; prefer least-privilege users and SSL (e.g., `?sslmode=require`).
- Safety toggles: `POSTGRES_READONLY=true`, `POSTGRES_STATEMENT_TIMEOUT_MS=5000`.
- Auth mode: set `MCP_AUTH_ISSUER` + `MCP_PERMISSIONS_FILE` for JWT-based per-user permissions.
- Server should run safely without a DSN; keep graceful failure paths intact.
