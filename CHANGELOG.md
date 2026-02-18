# Changelog

All notable changes to the PostgreSQL MCP Server will be documented in this file.

## [3.0.0] - 2026-02-18

### Breaking Changes

- **Complete rewrite** of `postgres_server.py` — single-file async server on FastMCP (MCP SDK v1.20+)
- Removed OAuth companion (`oauth_companion.py`, `start.py`, `token_exchange_fix.py`)
- Removed Google OAuth flow — replaced with generic JWKS/JWT IdP auth
- Environment variables renamed (see Migration section below)

### New

- **Async connection pooling** via `psycopg_pool.AsyncConnectionPool` with configurable min/max size
- **YAML-based permissions** — role/schema/table/operation enforcement loaded from `permissions.yaml`
- **Optional JWKS auth** — verify JWT tokens from any external IdP (set `MCP_AUTH_ISSUER`)
- **Pagination** on `list_schemas`, `list_tables` with base64-encoded cursors
- **Consolidated tools** — 8 tools: `query`, `list_schemas`, `list_tables`, `describe_table`, `get_foreign_keys`, `find_relationships`, `server_info`, `db_identity`
- **MCP resources** — `table://{schema}/{table}` template for reading rows
- **MCP prompts** — `write_safe_select`, `explain_plan_tips`
- **Three transports** — `stdio` (default), `sse`, `streamable-http`
- **Statement timeout** — configurable via `POSTGRES_STATEMENT_TIMEOUT_MS`
- `.mcp.json` for local Claude Code integration

### Fixed

- `list_schemas` failing due to psycopg interpreting `pg_%` literal as placeholder
- Pool `configure` callback leaving connections in INTRANS state
- `SET` commands using parameterized queries (not supported by PostgreSQL)
- `from __future__ import annotations` breaking `mcp dev` inspector
- `FastMCP.run()` receiving unsupported `host`/`port` kwargs

### Removed

- `oauth_companion.py`, `start.py`, `token_exchange_fix.py`, `test_oauth_client.py`
- `postgres_server_original.py`
- `OAUTH_SETUP.md`, `RAILWAY_DEPLOYMENT.md`
- Google OAuth dependencies (`authlib`, `python-jose`, `itsdangerous`, `fastapi`)

### Migration from v2.0

| v2.0 | v3.0 |
|------|------|
| `POSTGRES_CONNECTION_STRING` | `DATABASE_URL` (or `--conn`) |
| `--oauth-only` | `MCP_AUTH_ISSUER` + `MCP_PERMISSIONS_FILE` |
| Google OAuth | Any JWKS-compatible IdP |
| `GOOGLE_CLIENT_ID` / `SECRET` | `MCP_AUTH_ISSUER` / `MCP_AUTH_AUDIENCE` |
| Multi-file (`start.py` + companions) | Single file `postgres_server.py` |

### Dependencies

```
mcp[cli]>=1.20.0
psycopg[binary]>=3.1.0
psycopg_pool>=3.1.0
pyjwt[crypto]>=2.8.0
pyyaml>=6.0
uvicorn>=0.24.0
```

---

## [2.0.0] - 2025-01-28

### Major Features

- Google OAuth 2.0 integration with multi-tenant architecture
- Railway cloud deployment with automatic environment detection
- Session-based authentication with user-specific database connections

### Core Tools

- `query`, `list_schemas`, `list_tables`, `describe_table`
- `get_foreign_keys`, `find_relationships`, `server_info`, `db_identity`

---

## [1.x] - Previous Versions

- PostgreSQL database exploration via MCP protocol
- SQL query execution with safety controls
- Schema/table introspection, foreign key discovery
- Multiple transports (stdio, SSE, HTTP)
