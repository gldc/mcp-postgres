# Production Rewrite Design: PostgreSQL MCP Server

**Date:** 2026-02-16
**Branch:** `remote-mcp` (will become the basis for a new branch)
**Approach:** Clean rewrite on MCP Python SDK v2 (`MCPServer`)

## Context

The PostgreSQL MCP server needs to be production-ready for internal apps. The current `remote-mcp` branch introduced an OAuth companion service and Google-specific auth, but regressed many tools from the original, broke tests, and diverged from modern MCP SDK patterns. The SDK itself has moved from `FastMCP` to `MCPServer` with async-first patterns, lifespan context, and built-in token verification.

## Goals

- Single-service deployment on MCP SDK v2 (`MCPServer`)
- Async throughout with connection pooling
- Optional auth via external IdP token verification
- Config-file-driven schema/table permissions per user
- Default to shared connection with no auth (local dev / trusted network)
- Restore all tools lost in the OAuth refactor
- Deduplicate tool signatures
- Compatible with stdio, SSE, and streamable-http transports

## Architecture

### Core Server

Single file `postgres_server.py` using `from mcp.server.mcpserver import MCPServer`.

Lifespan context manager initializes an `AsyncConnectionPool` (from `psycopg_pool`) at startup and tears it down on shutdown:

```python
@dataclass
class AppContext:
    pool: AsyncConnectionPool
    config: ServerConfig
    permissions: Permissions  # optional, loaded from YAML
```

### Two Modes

**No auth (default):** Shared connection pool, no token verification. All tools available to all callers. Local dev / stdio / trusted-network mode.

**Auth enabled:** A `TokenVerifier` validates Bearer tokens from an external IdP. The verified token's `sub` claim is looked up in the permissions config to determine schema/table access. Tools check permissions before executing. Enabled when `MCP_AUTH_ISSUER` is configured.

## Tools

Consolidated tool set merging both `postgres_server.py` and `postgres_server_original.py`:

| Tool | Description |
|---|---|
| `query` | Execute SQL, return markdown or JSON. Single tool replaces all legacy query variants. `format` param picks output. |
| `list_schemas` | List schemas with filters (system/temp/name pattern). JSON with pagination. |
| `list_tables` | List tables in a schema with filters (name pattern, table types). JSON with pagination. |
| `describe_table` | Column details for a table. |
| `get_foreign_keys` | FK constraints for a table. |
| `find_relationships` | Explicit FKs + implied relationships (the `_id` pattern heuristic). |
| `db_identity` | Current DB/user/host/version info. |
| `server_info` | Server config and capabilities. |

### Removed

- Legacy duplicate signatures (`run_query`, `run_query_json`, `query_json`, `run_query_auth`, `run_query_json_auth`)
- `auth_info`, `health_check` as MCP tools (health check becomes HTTP endpoint)
- `list_table_resources`/`read_table_resource` tools (replaced by MCP resources)

### MCP Resources

- `table://{schema}/{table}` via `@mcp.resource()`, returns table rows as JSON

### MCP Prompts

- `write_safe_select` — guidelines for safe SELECT queries
- `explain_plan_tips` — tips for reading EXPLAIN output

Registered natively with `@mcp.prompt()` (no `try/getattr` needed on MCPServer v2).

## Permissions

### Config File

YAML file (default: `permissions.yaml`, overridable via `--permissions` or `MCP_PERMISSIONS_FILE`):

```yaml
roles:
  analyst:
    schemas: ["public", "analytics"]
    tables: "*"
    operations: ["select"]

  engineer:
    schemas: ["public", "analytics", "internal"]
    tables: "*"
    operations: ["select", "insert", "update", "delete"]

  restricted:
    schemas: ["public"]
    tables: ["products", "categories"]
    operations: ["select"]

users:
  alice@company.com:
    role: engineer
  bob@company.com:
    role: analyst
  _default: restricted
```

### Enforcement

1. If auth disabled, skip all checks.
2. Extract user identity from verified token `sub` claim.
3. Look up role, resolve allowed schemas/tables/operations.
4. Check operation type (first SQL keyword) and referenced tables (regex + simple parsing).
5. Reject with clear error if disallowed.

This is a guardrail, not a security boundary. Real security comes from the Postgres user's privileges on the shared connection. This layer prevents accidental access.

`POSTGRES_READONLY` still works as a global override regardless of permissions.

Permissions loaded once at startup. Restart to update.

### Token Verification

JWT validation against a JWKS endpoint:

- `MCP_AUTH_ISSUER` — IdP issuer URL
- `MCP_AUTH_AUDIENCE` — expected audience claim
- `MCP_AUTH_JWKS_URL` — JWKS endpoint (defaults to `{issuer}/.well-known/jwks.json`)

When none are set, auth is off.

## Connection Management

`psycopg_pool.AsyncConnectionPool`:

- Configurable `min_size`/`max_size` via `MCP_POOL_MIN` (default 2) / `MCP_POOL_MAX` (default 10)
- Tools use `async with pool.connection() as conn:`
- `statement_timeout` and `application_name` set via pool `configure` callback
- Pool health validated at startup — fails fast if DSN is bad

**Graceful no-DSN mode:** Server starts without a connection string. Tools return clear errors. Introspection tools (`server_info`) still work.

## Error Handling

- DB errors return error strings, never raise exceptions that crash the MCP session
- `mask_error_details=True` in production to avoid leaking internals
- Permission denials: `"Access denied: table 'internal.secrets' is not in your allowlist."`
- SQL syntax errors: Postgres error message returned as-is (useful for LLM self-correction)

## Health Endpoint

When running on `streamable-http`, expose `/health` that checks pool connectivity. Works with Railway/load balancer health checks. Not an MCP tool.

## Testing

- **No-DSN tests** — tools return friendly errors. Zero infrastructure needed for CI.
- **Permission tests** — unit tests for YAML config parser and SQL enforcement logic. No DB needed.
- **Integration tests** — `@pytest.mark.integration`, skipped unless `DATABASE_URL` is set. Real query execution, pooling, schema introspection.
- **Auth tests** — mock `TokenVerifier` to test auth-enabled code paths without a real IdP.

## File Structure (After)

```
postgres_server.py          # the server (rewritten)
permissions.yaml.example    # example permissions config
requirements.txt            # updated
tests/
  test_tools.py             # no-DSN + permission unit tests
  test_integration.py       # real DB tests
  conftest.py               # shared fixtures
README.md                   # updated
CLAUDE.md                   # updated
smithery.yaml               # updated
railway.toml                # simplified (single service)
```

## Files Deleted

- `oauth_companion.py`
- `start.py`
- `token_exchange_fix.py`
- `test_oauth_client.py`
- `postgres_server_original.py`
- `OAUTH_SETUP.md`
- `RAILWAY_DEPLOYMENT.md` (content folded into README)
- `oauth_sessions.db`, `user_sessions.db`

## Dependency Changes

**Add:** `pyyaml`, `pyjwt[crypto]`, `psycopg_pool`
**Remove:** `authlib`, `python-jose`, `itsdangerous`, `fastapi`, `python-multipart`
**Update:** `mcp[cli]>=2.0.0`

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `DATABASE_URL` / `POSTGRES_CONNECTION_STRING` | Connection DSN | none |
| `POSTGRES_READONLY` | Global read-only mode | `false` |
| `POSTGRES_STATEMENT_TIMEOUT_MS` | Query timeout | none |
| `MCP_TRANSPORT` | `stdio`, `sse`, `streamable-http` | `stdio` |
| `MCP_POOL_MIN` | Min pool connections | `2` |
| `MCP_POOL_MAX` | Max pool connections | `10` |
| `MCP_PERMISSIONS_FILE` | Path to permissions YAML | none |
| `MCP_AUTH_ISSUER` | IdP issuer URL (enables auth) | none |
| `MCP_AUTH_AUDIENCE` | Expected JWT audience | none |
| `MCP_AUTH_JWKS_URL` | JWKS endpoint | `{issuer}/.well-known/jwks.json` |
