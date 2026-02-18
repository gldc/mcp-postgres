# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

A PostgreSQL MCP (Model Context Protocol) server that lets AI agents interact with Postgres databases. It exposes database tools (query, list tables/schemas, describe tables, foreign keys, relationships) via the FastMCP framework with async connection pooling. Optional JWT/JWKS auth with YAML-based permissions for multi-user environments.

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

# Tests
pytest -q
pytest tests/test_tools.py                          # unit tests
pytest tests/test_tools.py::test_query_no_dsn_async  # single test

# Linting
ruff check .
```

## Architecture

**Single-file async MCP server:**

- `postgres_server.py` — Uses `FastMCP` from `mcp[cli]` to register tools. Connects to Postgres via `psycopg` with `AsyncConnectionPool` from `psycopg_pool`. Supports three transports: `stdio` (local), `sse`, `streamable-http` (remote/Railway). Lifespan context manager owns the pool, config, and permissions.

**Key components:**
- `ServerConfig` — Dataclass parsed from CLI args + env vars
- `AppContext` — Lifespan-scoped context holding pool, config, permissions
- `Permissions` / `RolePermissions` — YAML-based role/schema/table/operation enforcement
- `JWKSTokenVerifier` — Optional JWT verification against external IdP JWKS endpoint

**Tools:** `query`, `list_schemas`, `list_tables`, `describe_table`, `get_foreign_keys`, `find_relationships`, `server_info`, `db_identity`

**Two modes:**
- **No-auth (default):** Shared connection pool, no permission checks
- **Auth-enabled:** JWT tokens verified via JWKS, permissions enforced per-user from `permissions.yaml`

## Key Environment Variables

| Variable | Purpose |
|---|---|
| `DATABASE_URL` / `POSTGRES_CONNECTION_STRING` | Default DB connection |
| `POSTGRES_READONLY` | `true` to restrict to SELECT-like queries |
| `POSTGRES_STATEMENT_TIMEOUT_MS` | Query timeout in ms |
| `MCP_TRANSPORT` | `stdio`, `sse`, or `streamable-http` |
| `MCP_HOST` / `MCP_PORT` | Server bind address (default 127.0.0.1:8000) |
| `MCP_POOL_MIN` / `MCP_POOL_MAX` | Connection pool sizing (default 2-10) |
| `MCP_AUTH_ISSUER` | JWT issuer URL (enables auth mode) |
| `MCP_AUTH_AUDIENCE` | Expected JWT audience |
| `MCP_AUTH_JWKS_URL` | JWKS endpoint (auto-derived from issuer if not set) |
| `MCP_PERMISSIONS_FILE` | Path to permissions.yaml |

## Testing Conventions

- Tests must pass without a database connection. All tools return friendly empty/notice results when no DSN is configured.
- `tests/conftest.py` clears DSN env vars to simulate no-DSN mode.
- `tests/test_tools.py` — Unit tests for tools, permissions, and auth.
- `tests/test_integration.py` — Integration tests (skipped unless `DATABASE_URL` is set).

## Important Operational Note

After changes to `postgres_server.py`, the MCP server must be restarted before testing (there is no hot-reload).
