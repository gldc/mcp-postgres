# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A PostgreSQL MCP (Model Context Protocol) server that lets AI agents interact with Postgres databases. It exposes database tools (query, list tables/schemas, describe tables, foreign keys) via the FastMCP framework. An optional OAuth companion service (Google OAuth2) enables multi-user authentication with per-user database connections.

## Commands

```bash
# Setup
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -r dev-requirements.txt

# Run MCP server (stdio, local dev)
python postgres_server.py --conn "postgresql://user:pass@host:5432/db"

# Run MCP server (HTTP transport)
python postgres_server.py --transport streamable-http --host 127.0.0.1 --port 8000

# Run OAuth companion service
python oauth_companion.py --port 8001

# Railway unified launcher (uses SERVICE_ROLE env: "mcp" or "oauth")
python start.py

# Tests
pytest -q
pytest tests/test_server_tools.py          # single test file
pytest tests/test_server_tools.py::test_run_query_no_dsn  # single test

# Linting (optional)
ruff check .
black .
```

## Architecture

**Two services, one repo:**

- `postgres_server.py` — The MCP server. Uses `FastMCP` from `mcp[cli]` to register tools. Connects to Postgres via `psycopg`. Supports three transports: `stdio` (local), `sse`, `streamable-http` (remote/Railway). Has both legacy tool signatures (`query`, `query_json`) and typed Pydantic-input versions (`run_query`, `run_query_json`). Auth-aware variants (`run_query_auth`, `run_query_json_auth`) validate session tokens and fetch per-user DSNs from the OAuth companion.

- `oauth_companion.py` — FastAPI service for Google OAuth2. Handles `/auth/login`, `/auth/callback`, `/auth/status`, `/auth/logout`. Stores sessions in a local SQLite DB (`oauth_sessions.db`). Provides `/connection/set` for users to configure their Postgres DSN after authenticating. Token versioning supports logout/invalidation.

- `start.py` — Railway deployment entrypoint. Routes to either service based on `SERVICE_ROLE` env var via `os.execv`.

**Session tokens** use `itsdangerous.URLSafeTimedSerializer` with `SECRET_KEY`, 7-day expiry, and a per-user `token_version` for revocation.

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `POSTGRES_CONNECTION_STRING` / `DATABASE_URL` | Default DB connection (Railway provides `DATABASE_URL`) |
| `POSTGRES_READONLY` | `true` to restrict to SELECT-like queries |
| `POSTGRES_STATEMENT_TIMEOUT_MS` | Query timeout in ms |
| `MCP_TRANSPORT` | `stdio`, `sse`, or `streamable-http` |
| `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` | OAuth credentials |
| `SECRET_KEY` | Token signing key |
| `OAUTH_SERVICE_URL` | URL of OAuth companion (for MCP server to validate tokens) |
| `SERVICE_ROLE` | `mcp` or `oauth` (Railway launcher routing) |

## Testing Conventions

- Tests must pass without a database connection. All tools should return friendly empty/notice results when no DSN is configured.
- Tests import directly from `postgres_server` and set `CONNECTION_STRING = None` to simulate no-DSN mode.
- The test file references some tools/models (`list_schemas_json`, `ListSchemasPageInput`, etc.) that exist in `postgres_server_original.py` but were removed in the OAuth refactor of `postgres_server.py` — some tests may fail against the current server.

## Important Operational Note

After changes to `postgres_server.py`, the MCP server must be restarted before testing (there is no hot-reload).
