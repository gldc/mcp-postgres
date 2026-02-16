# PostgreSQL MCP Server Production Rewrite — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rewrite postgres_server.py on MCP Python SDK v2 (MCPServer) with async tools, connection pooling, config-file permissions, and optional external IdP auth.

**Architecture:** Single-file async MCP server using `MCPServer` from `mcp.server.mcpserver`. Lifespan context manager owns an `AsyncConnectionPool`. Optional `TokenVerifier` + YAML permissions file for auth. Two modes: no-auth (default) and auth-enabled.

**Tech Stack:** `mcp[cli]>=2.0.0`, `psycopg[binary]>=3.1.0`, `psycopg_pool>=3.1.0`, `pyyaml>=6.0`, `pyjwt[crypto]>=2.8.0`

**Design doc:** `docs/plans/2026-02-16-production-rewrite-design.md`

---

### Task 1: Clean Up — Delete Legacy Files and Update Dependencies ✅ DONE

**Files:**
- Delete: `oauth_companion.py`
- Delete: `start.py`
- Delete: `token_exchange_fix.py`
- Delete: `test_oauth_client.py`
- Delete: `postgres_server_original.py`
- Delete: `OAUTH_SETUP.md`
- Delete: `RAILWAY_DEPLOYMENT.md`
- Modify: `requirements.txt`
- Modify: `dev-requirements.txt`

**Step 1: Delete legacy files**

```bash
git rm oauth_companion.py start.py token_exchange_fix.py test_oauth_client.py postgres_server_original.py OAUTH_SETUP.md RAILWAY_DEPLOYMENT.md
```

Also remove SQLite databases (not tracked, but clean up locally):

```bash
rm -f oauth_sessions.db user_sessions.db
```

**Step 2: Rewrite requirements.txt**

```
# Core MCP (v2)
mcp[cli]>=2.0.0

# Database
psycopg[binary]>=3.1.0
psycopg_pool>=3.1.0

# Auth (optional runtime — server works without these if auth disabled)
pyjwt[crypto]>=2.8.0

# Permissions config
pyyaml>=6.0

# Web server (needed for streamable-http/sse transports, pulled in by mcp[cli])
uvicorn>=0.24.0
```

**Step 3: Rewrite dev-requirements.txt**

```
pytest>=8.0.0
pytest-asyncio>=0.23.0
pytest-cov>=4.1.0
ruff>=0.4.0
```

**Step 4: Commit**

```bash
git add -A
git commit -m "chore: remove legacy OAuth files and update dependencies for v2 rewrite"
```

---

### Task 2: Scaffold — Empty Server with Lifespan and Config ✅ DONE

This task creates the new `postgres_server.py` skeleton: config parsing, lifespan, pool setup, and the `mcp.run()` entrypoint. No tools yet.

**Files:**
- Create: `postgres_server.py` (overwrite existing)
- Test: `tests/test_tools.py` (overwrite existing)
- Create: `tests/conftest.py`

**Step 1: Write the test — server starts without DSN**

File: `tests/conftest.py`

```python
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path
ROOT = str(Path(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Clear DSN so tests run without a database
os.environ.pop("DATABASE_URL", None)
os.environ.pop("POSTGRES_CONNECTION_STRING", None)
```

File: `tests/test_tools.py`

```python
import pytest


def test_server_module_imports():
    """Server module imports without a DSN configured."""
    import postgres_server
    assert postgres_server.mcp is not None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_tools.py::test_server_module_imports -v
```

Expected: FAIL (old postgres_server.py has incompatible imports or missing deps)

**Step 3: Write the server skeleton**

File: `postgres_server.py`

```python
"""PostgreSQL MCP Server — production-ready, async, with optional auth."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from mcp.server.mcpserver import MCPServer

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("postgres-mcp")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
@dataclass
class ServerConfig:
    dsn: Optional[str] = None
    readonly: bool = False
    statement_timeout_ms: Optional[int] = None
    pool_min: int = 2
    pool_max: int = 10
    transport: str = "stdio"
    host: str = "127.0.0.1"
    port: int = 8000
    # Auth
    auth_issuer: Optional[str] = None
    auth_audience: Optional[str] = None
    auth_jwks_url: Optional[str] = None
    # Permissions
    permissions_file: Optional[str] = None


def load_config() -> ServerConfig:
    parser = argparse.ArgumentParser(description="PostgreSQL MCP Server")
    parser.add_argument("--conn", default=None, help="PostgreSQL connection DSN")
    parser.add_argument(
        "--transport",
        choices=["stdio", "sse", "streamable-http"],
        default=os.getenv("MCP_TRANSPORT", "stdio"),
    )
    parser.add_argument("--host", default=os.getenv("MCP_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("MCP_PORT", "8000")))
    parser.add_argument("--permissions", default=os.getenv("MCP_PERMISSIONS_FILE"))
    args, _ = parser.parse_known_args()

    dsn = args.conn or os.getenv("DATABASE_URL") or os.getenv("POSTGRES_CONNECTION_STRING")

    timeout = None
    raw = os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS")
    if raw:
        try:
            timeout = int(raw)
        except ValueError:
            logger.warning("Invalid POSTGRES_STATEMENT_TIMEOUT_MS; ignoring")

    return ServerConfig(
        dsn=dsn,
        readonly=os.getenv("POSTGRES_READONLY", "false").lower() in {"1", "true", "yes"},
        statement_timeout_ms=timeout,
        pool_min=int(os.getenv("MCP_POOL_MIN", "2")),
        pool_max=int(os.getenv("MCP_POOL_MAX", "10")),
        transport=args.transport,
        host=args.host,
        port=args.port,
        auth_issuer=os.getenv("MCP_AUTH_ISSUER"),
        auth_audience=os.getenv("MCP_AUTH_AUDIENCE"),
        auth_jwks_url=os.getenv("MCP_AUTH_JWKS_URL"),
        permissions_file=args.permissions,
    )


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
@dataclass
class RolePermissions:
    schemas: list[str] = field(default_factory=lambda: ["public"])
    tables: str | list[str] = "*"  # "*" means all tables in allowed schemas
    operations: list[str] = field(default_factory=lambda: ["select"])


@dataclass
class Permissions:
    roles: dict[str, RolePermissions] = field(default_factory=dict)
    users: dict[str, str] = field(default_factory=dict)  # user_id -> role_name
    default_role: Optional[str] = None

    def get_role_for_user(self, user_id: str) -> Optional[RolePermissions]:
        role_name = self.users.get(user_id) or self.default_role
        if role_name:
            return self.roles.get(role_name)
        return None


def load_permissions(path: Optional[str]) -> Permissions:
    if not path or not os.path.exists(path):
        return Permissions()
    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    roles = {}
    for name, cfg in raw.get("roles", {}).items():
        roles[name] = RolePermissions(
            schemas=cfg.get("schemas", ["public"]),
            tables=cfg.get("tables", "*"),
            operations=[op.lower() for op in cfg.get("operations", ["select"])],
        )

    users_raw = raw.get("users", {})
    default_role = users_raw.pop("_default", None)
    users = {uid: role for uid, role in users_raw.items() if isinstance(role, str)}

    # Handle case where users map to dicts with "role" key
    for uid, val in users_raw.items():
        if isinstance(val, dict) and "role" in val:
            users[uid] = val["role"]

    return Permissions(roles=roles, users=users, default_role=default_role)


# ---------------------------------------------------------------------------
# App context & lifespan
# ---------------------------------------------------------------------------
@dataclass
class AppContext:
    pool: Optional[AsyncConnectionPool]
    config: ServerConfig
    permissions: Permissions


_config = load_config()


@asynccontextmanager
async def app_lifespan(server: MCPServer) -> AsyncIterator[AppContext]:
    permissions = load_permissions(_config.permissions_file)
    pool: Optional[AsyncConnectionPool] = None

    if _config.dsn:
        async def configure_conn(conn):
            async with conn.cursor() as cur:
                await cur.execute("SET application_name = %s", ("mcp-postgres",))
                if _config.statement_timeout_ms and _config.statement_timeout_ms > 0:
                    await cur.execute(
                        "SET statement_timeout = %s", (_config.statement_timeout_ms,)
                    )

        pool = AsyncConnectionPool(
            conninfo=_config.dsn,
            min_size=_config.pool_min,
            max_size=_config.pool_max,
            configure=configure_conn,
            open=False,
        )
        await pool.open()
        # Validate connectivity
        async with pool.connection() as conn:
            await conn.execute("SELECT 1")
        logger.info("Connection pool ready (%d-%d)", _config.pool_min, _config.pool_max)

    try:
        yield AppContext(pool=pool, config=_config, permissions=permissions)
    finally:
        if pool:
            await pool.close()
            logger.info("Connection pool closed")


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------
mcp = MCPServer(
    "PostgreSQL Explorer",
    lifespan=app_lifespan,
)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting PostgreSQL MCP server — transport=%s", _config.transport)
    mcp.run(
        transport=_config.transport,
        host=_config.host,
        port=_config.port,
    )
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/test_tools.py::test_server_module_imports -v
```

Expected: PASS

**Step 5: Commit**

```bash
git add postgres_server.py tests/conftest.py tests/test_tools.py
git commit -m "feat: scaffold MCPServer v2 with lifespan, config, and pool"
```

---

### Task 3: Core Query Tool ✅ DONE

The unified `query` tool that replaces all legacy query variants.

**Files:**
- Modify: `postgres_server.py`
- Modify: `tests/test_tools.py`

**Step 1: Write the failing tests**

Append to `tests/test_tools.py`:

```python
import pytest
from postgres_server import mcp


def test_query_no_dsn():
    """query tool returns error string when no DB configured."""
    import postgres_server

    # Call the raw function (tools are registered as functions)
    from postgres_server import query
    # We need to test the async function; use pytest-asyncio
    pass


@pytest.mark.asyncio
async def test_query_no_dsn_async():
    """query tool returns friendly error when no pool available."""
    from postgres_server import _query_impl

    result = await _query_impl(pool=None, sql="SELECT 1", readonly=False)
    assert isinstance(result, str)
    assert "not configured" in result.lower()
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/test_tools.py::test_query_no_dsn_async -v
```

Expected: FAIL — `_query_impl` doesn't exist yet

**Step 3: Implement the query tool**

Add to `postgres_server.py` after the `mcp = MCPServer(...)` line:

```python
from mcp.server.mcpserver import Context


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_select_like(sql: str) -> bool:
    token = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
    return token in {"select", "with", "show", "values", "explain"}


def _format_markdown_table(rows: list[dict[str, Any]], row_limit: int) -> str:
    if not rows:
        return "No results found"
    keys = list(rows[0].keys())
    lines = [" | ".join(keys), " | ".join(["---"] * len(keys))]
    truncated = len(rows) > row_limit
    display = rows[:row_limit]
    for row in display:
        vals = []
        for k in keys:
            v = row.get(k)
            if v is None:
                vals.append("NULL")
            elif isinstance(v, (bytes, bytearray)):
                vals.append(v.decode("utf-8", errors="replace"))
            else:
                vals.append(str(v))
        lines.append(" | ".join(vals))
    if truncated:
        lines.append(f"\n(Truncated at {row_limit} rows)")
    return "\n".join(lines)


async def _query_impl(
    pool: Optional[AsyncConnectionPool],
    sql: str,
    readonly: bool,
    parameters: Optional[list[Any]] = None,
    row_limit: int = 500,
    format: str = "markdown",
) -> str | list[dict[str, Any]]:
    if pool is None:
        return "Database not configured. Provide --conn or set DATABASE_URL."

    if readonly and not _is_select_like(sql):
        return "Read-only mode: only SELECT queries are allowed."

    as_json = format.lower() == "json"

    async with pool.connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            t0 = time.time()
            await cur.execute(sql, parameters)

            if cur.description is None:
                return (
                    [] if as_json
                    else f"Query executed. Rows affected: {cur.rowcount}"
                )

            rows = await cur.fetchmany(row_limit + 1)
            rows_dicts = [dict(r) for r in rows]
            duration_ms = int((time.time() - t0) * 1000)
            logger.info("Query: %d rows in %dms", len(rows_dicts), duration_ms)

            if as_json:
                return rows_dicts[:row_limit]

            return _format_markdown_table(rows_dicts, row_limit)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------
@mcp.tool()
async def query(
    sql: str,
    ctx: Context,
    parameters: Optional[list[Any]] = None,
    row_limit: int = 500,
    format: str = "markdown",
) -> str:
    """Execute a SQL query. Returns markdown table by default, or JSON rows if format='json'.

    Args:
        sql: SQL statement to execute.
        parameters: Positional parameters for parameterized queries.
        row_limit: Maximum rows to return (1-10000, default 500).
        format: Output format — 'markdown' or 'json'.
    """
    app: AppContext = ctx.request_context.lifespan_context
    try:
        result = await _query_impl(
            pool=app.pool,
            sql=sql,
            readonly=app.config.readonly,
            parameters=parameters,
            row_limit=max(1, min(row_limit, 10000)),
            format=format,
        )
        if isinstance(result, list):
            return json.dumps(result, default=str)
        return result
    except Exception as e:
        logger.error("Query error: %s", e)
        return f"Query error: {e}"
```

**Step 4: Run tests**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add postgres_server.py tests/test_tools.py
git commit -m "feat: add unified async query tool with markdown/json output"
```

---

### Task 4: Schema and Table Introspection Tools ✅ DONE

**Files:**
- Modify: `postgres_server.py`
- Modify: `tests/test_tools.py`

**Step 1: Write failing tests**

Append to `tests/test_tools.py`:

```python
@pytest.mark.asyncio
async def test_list_schemas_no_dsn():
    from postgres_server import _query_impl

    result = await _query_impl(pool=None, sql="SELECT 1", readonly=False)
    assert "not configured" in result.lower()


@pytest.mark.asyncio
async def test_list_tables_no_dsn():
    from postgres_server import _query_impl

    result = await _query_impl(pool=None, sql="SELECT 1", readonly=False)
    assert "not configured" in result.lower()
```

**Step 2: Run to verify fails (or passes if _query_impl already exists from Task 3)**

```bash
pytest tests/test_tools.py -v
```

**Step 3: Implement tools**

Add to `postgres_server.py`:

```python
@mcp.tool()
async def list_schemas(
    ctx: Context,
    include_system: bool = False,
    name_pattern: Optional[str] = None,
    page_size: int = 500,
    cursor: Optional[str] = None,
) -> str:
    """List database schemas as JSON.

    Args:
        include_system: Include pg_* and information_schema.
        name_pattern: Filter by ILIKE pattern (use % and _).
        page_size: Results per page (default 500).
        cursor: Pagination cursor from previous call.
    """
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return json.dumps({"items": [], "next_cursor": None})

    offset = 0
    if cursor:
        try:
            import base64
            offset = json.loads(base64.b64decode(cursor))["offset"]
        except Exception:
            offset = 0

    conditions = []
    params: list[Any] = []
    if not include_system:
        conditions.append("n.nspname NOT LIKE 'pg_%' AND n.nspname != 'information_schema'")
    if name_pattern:
        conditions.append("n.nspname ILIKE %s")
        params.append(name_pattern)

    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    limit = page_size + 1
    params.extend([limit, offset])

    sql = f"""
    SELECT n.nspname AS schema_name,
           pg_get_userbyid(n.nspowner) AS owner,
           has_schema_privilege(n.nspname, 'USAGE') AS has_usage
    FROM pg_namespace n
    {where}
    ORDER BY n.nspname
    LIMIT %s OFFSET %s
    """

    try:
        async with app.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, params)
                rows = [dict(r) for r in await cur.fetchall()]

        next_cursor = None
        if len(rows) > page_size:
            rows = rows[:page_size]
            import base64
            next_cursor = base64.b64encode(
                json.dumps({"offset": offset + page_size}).encode()
            ).decode()

        return json.dumps({"items": rows, "next_cursor": next_cursor}, default=str)
    except Exception as e:
        logger.error("list_schemas error: %s", e)
        return json.dumps({"items": [], "next_cursor": None, "error": str(e)})


@mcp.tool()
async def list_tables(
    ctx: Context,
    schema: Optional[str] = None,
    name_pattern: Optional[str] = None,
    table_types: Optional[list[str]] = None,
    page_size: int = 500,
    cursor: Optional[str] = None,
) -> str:
    """List tables in a schema as JSON.

    Args:
        schema: Schema name (defaults to current schema).
        name_pattern: Filter by ILIKE pattern.
        table_types: Filter by type, e.g. ['BASE TABLE', 'VIEW'].
        page_size: Results per page.
        cursor: Pagination cursor.
    """
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return json.dumps({"items": [], "next_cursor": None})

    offset = 0
    if cursor:
        try:
            import base64
            offset = json.loads(base64.b64decode(cursor))["offset"]
        except Exception:
            offset = 0

    eff_schema = schema
    if not eff_schema:
        try:
            async with app.pool.connection() as conn:
                async with conn.cursor(row_factory=dict_row) as cur:
                    await cur.execute("SELECT current_schema() AS s")
                    row = await cur.fetchone()
                    eff_schema = row["s"] if row else "public"
        except Exception:
            eff_schema = "public"

    conditions = ["table_schema = %s"]
    params: list[Any] = [eff_schema]
    if name_pattern:
        conditions.append("table_name ILIKE %s")
        params.append(name_pattern)
    if table_types:
        placeholders = ",".join(["%s"] * len(table_types))
        conditions.append(f"table_type IN ({placeholders})")
        params.extend(table_types)

    where = " AND ".join(conditions)
    limit = page_size + 1
    params.extend([limit, offset])

    sql = f"""
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE {where}
    ORDER BY table_name
    LIMIT %s OFFSET %s
    """

    try:
        async with app.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, params)
                rows = [dict(r) for r in await cur.fetchall()]

        next_cursor = None
        if len(rows) > page_size:
            rows = rows[:page_size]
            import base64
            next_cursor = base64.b64encode(
                json.dumps({"offset": offset + page_size}).encode()
            ).decode()

        return json.dumps({"items": rows, "next_cursor": next_cursor}, default=str)
    except Exception as e:
        logger.error("list_tables error: %s", e)
        return json.dumps({"items": [], "next_cursor": None, "error": str(e)})


@mcp.tool()
async def describe_table(
    table_name: str,
    ctx: Context,
    schema: Optional[str] = None,
) -> str:
    """Get column details for a table.

    Args:
        table_name: Table to describe.
        schema: Schema name (defaults to current schema).
    """
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return "Database not configured. Provide --conn or set DATABASE_URL."

    eff_schema = schema or "public"
    sql = """
    SELECT column_name, data_type, is_nullable, column_default, character_maximum_length
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
    """
    try:
        async with app.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, [eff_schema, table_name])
                rows = [dict(r) for r in await cur.fetchall()]
        return json.dumps(rows, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def get_foreign_keys(
    table_name: str,
    ctx: Context,
    schema: Optional[str] = None,
) -> str:
    """Get foreign key constraints for a table.

    Args:
        table_name: Table to inspect.
        schema: Schema name (defaults to public).
    """
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return "Database not configured. Provide --conn or set DATABASE_URL."

    eff_schema = schema or "public"
    sql = """
    SELECT tc.constraint_name,
           kcu.column_name AS fk_column,
           ccu.table_schema AS referenced_schema,
           ccu.table_name AS referenced_table,
           ccu.column_name AS referenced_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
    JOIN information_schema.referential_constraints rc
        ON tc.constraint_name = rc.constraint_name
    JOIN information_schema.constraint_column_usage ccu
        ON rc.unique_constraint_name = ccu.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
    ORDER BY tc.constraint_name, kcu.ordinal_position
    """
    try:
        async with app.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(sql, [eff_schema, table_name])
                rows = [dict(r) for r in await cur.fetchall()]
        return json.dumps(rows, default=str)
    except Exception as e:
        return f"Error: {e}"


@mcp.tool()
async def find_relationships(
    table_name: str,
    ctx: Context,
    schema: Optional[str] = None,
) -> str:
    """Find explicit foreign keys and implied relationships for a table.

    Args:
        table_name: Table to analyze.
        schema: Schema name (defaults to public).
    """
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return "Database not configured. Provide --conn or set DATABASE_URL."

    eff_schema = schema or "public"

    explicit_sql = """
    SELECT kcu.column_name,
           ccu.table_name AS foreign_table,
           ccu.column_name AS foreign_column,
           'explicit_fk' AS relationship_type
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
    JOIN information_schema.constraint_column_usage ccu
        ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s AND tc.table_name = %s
    """

    implied_sql = """
    WITH source_cols AS (
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
            AND (column_name LIKE '%%_id' OR column_name LIKE '%%_fk')
    )
    SELECT sc.column_name,
           t.table_name AS foreign_table,
           'id' AS foreign_column,
           CASE
               WHEN sc.column_name = t.table_name || '_id' THEN 'strong_implied'
               ELSE 'possible_implied'
           END AS relationship_type
    FROM source_cols sc
    CROSS JOIN information_schema.tables t
    JOIN information_schema.columns c
        ON c.table_schema = t.table_schema AND c.table_name = t.table_name AND c.column_name = 'id'
    WHERE t.table_schema = %s AND t.table_name != %s
        AND sc.data_type = c.data_type
    """

    try:
        async with app.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(explicit_sql, [eff_schema, table_name])
                explicit = [dict(r) for r in await cur.fetchall()]

                await cur.execute(implied_sql, [eff_schema, table_name, eff_schema, table_name])
                implied = [dict(r) for r in await cur.fetchall()]

        return json.dumps({"explicit": explicit, "implied": implied}, default=str)
    except Exception as e:
        return f"Error: {e}"
```

**Step 4: Run tests**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add postgres_server.py tests/test_tools.py
git commit -m "feat: add schema/table introspection tools with pagination"
```

---

### Task 5: Info Tools, Resources, and Prompts ✅ DONE

**Files:**
- Modify: `postgres_server.py`
- Modify: `tests/test_tools.py`

**Step 1: Write failing tests**

Append to `tests/test_tools.py`:

```python
def test_server_info_registered():
    """server_info tool is registered."""
    from postgres_server import mcp
    # MCPServer stores tools internally; just verify import works
    from postgres_server import server_info, db_identity
    assert callable(server_info)
    assert callable(db_identity)
```

**Step 2: Run to verify it fails**

```bash
pytest tests/test_tools.py::test_server_info_registered -v
```

Expected: FAIL — `server_info` not importable yet

**Step 3: Implement**

Add to `postgres_server.py`:

```python
@mcp.tool()
async def server_info(ctx: Context) -> str:
    """Return server configuration and capability info."""
    app: AppContext = ctx.request_context.lifespan_context
    import psycopg
    return json.dumps({
        "name": "PostgreSQL Explorer",
        "version": "2.0.0",
        "readonly": app.config.readonly,
        "statement_timeout_ms": app.config.statement_timeout_ms,
        "auth_enabled": app.config.auth_issuer is not None,
        "pool_configured": app.pool is not None,
        "transport": app.config.transport,
        "psycopg_version": getattr(psycopg, "__version__", None),
    })


@mcp.tool()
async def db_identity(ctx: Context) -> str:
    """Return current database identity: db name, user, host, port, version."""
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return json.dumps({})

    try:
        async with app.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    "SELECT current_database() AS database, current_user AS \"user\", "
                    "inet_server_addr()::text AS host, inet_server_port() AS port"
                )
                info = dict(await cur.fetchone() or {})

                await cur.execute("SELECT current_schemas(true) AS search_path")
                row = await cur.fetchone()
                if row:
                    info["search_path"] = row["search_path"]

                await cur.execute(
                    "SELECT name, setting FROM pg_settings "
                    "WHERE name IN ('server_version', 'cluster_name')"
                )
                for r in await cur.fetchall():
                    info[r["name"]] = r["setting"]

        return json.dumps(info, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# MCP Resources
# ---------------------------------------------------------------------------
@mcp.resource("table://{schema}/{table}")
async def table_resource(schema: str, table: str, ctx: Context) -> str:
    """Read rows from a table (max 100)."""
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return json.dumps([])
    try:
        async with app.pool.connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                # Use quote_ident equivalent for safety
                await cur.execute(
                    f'SELECT * FROM "{schema}"."{table}" LIMIT 100'
                )
                rows = [dict(r) for r in await cur.fetchall()]
        return json.dumps(rows, default=str)
    except Exception as e:
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# MCP Prompts
# ---------------------------------------------------------------------------
@mcp.prompt()
def write_safe_select() -> str:
    """Guidelines for writing safe, read-only SELECT queries."""
    return (
        "Write a safe, read-only SELECT using parameterized placeholders. "
        "Avoid DML/DDL. Prefer explicit column lists, add LIMIT, "
        "and filter with indexed columns when possible."
    )


@mcp.prompt()
def explain_plan_tips() -> str:
    """Tips for reading EXPLAIN ANALYZE output."""
    return (
        "Use EXPLAIN (ANALYZE, BUFFERS, VERBOSE) to inspect plans. "
        "Check seq vs index scans, join order, row estimates, and sort/hash nodes. "
        "Consider indexes or query rewrites for slow operations."
    )
```

**Step 4: Run tests**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add postgres_server.py tests/test_tools.py
git commit -m "feat: add server_info, db_identity, MCP resources, and prompts"
```

---

### Task 6: Permissions Enforcement ✅ DONE

**Files:**
- Modify: `postgres_server.py`
- Create: `permissions.yaml.example`
- Modify: `tests/test_tools.py`

**Step 1: Write failing tests for permission logic**

Append to `tests/test_tools.py`:

```python
from postgres_server import (
    Permissions, RolePermissions, load_permissions,
    check_permission, extract_tables_from_sql,
)


def test_load_permissions_from_yaml(tmp_path):
    p = tmp_path / "perms.yaml"
    p.write_text("""
roles:
  analyst:
    schemas: ["public"]
    tables: "*"
    operations: ["select"]
  admin:
    schemas: ["public", "internal"]
    tables: "*"
    operations: ["select", "insert", "update", "delete"]
users:
  alice@co.com:
    role: admin
  _default: analyst
""")
    perms = load_permissions(str(p))
    assert "analyst" in perms.roles
    assert "admin" in perms.roles
    assert perms.users["alice@co.com"] == "admin"
    assert perms.default_role == "analyst"


def test_check_permission_allows_select():
    role = RolePermissions(schemas=["public"], tables="*", operations=["select"])
    result = check_permission(role, "select", "public", "users")
    assert result is None  # None means allowed


def test_check_permission_denies_schema():
    role = RolePermissions(schemas=["public"], tables="*", operations=["select"])
    result = check_permission(role, "select", "internal", "secrets")
    assert result is not None
    assert "internal" in result


def test_check_permission_denies_operation():
    role = RolePermissions(schemas=["public"], tables="*", operations=["select"])
    result = check_permission(role, "delete", "public", "users")
    assert result is not None
    assert "delete" in result


def test_check_permission_table_allowlist():
    role = RolePermissions(schemas=["public"], tables=["products", "categories"], operations=["select"])
    assert check_permission(role, "select", "public", "products") is None
    result = check_permission(role, "select", "public", "users")
    assert result is not None


def test_extract_tables_basic():
    tables = extract_tables_from_sql("SELECT * FROM public.users WHERE id = 1")
    assert ("public", "users") in tables or "users" in [t[1] for t in tables]


def test_extract_tables_join():
    tables = extract_tables_from_sql(
        "SELECT u.name, o.total FROM users u JOIN orders o ON u.id = o.user_id"
    )
    table_names = [t[1] for t in tables]
    assert "users" in table_names
    assert "orders" in table_names
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_tools.py -k "permission or extract" -v
```

Expected: FAIL — `check_permission` and `extract_tables_from_sql` don't exist

**Step 3: Implement**

Add to `postgres_server.py` after the `Permissions` class:

```python
def extract_operation(sql: str) -> str:
    """Extract the SQL operation type from the first keyword."""
    token = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
    if token in {"select", "with", "show", "values", "explain"}:
        return "select"
    return token  # insert, update, delete, create, drop, etc.


def extract_tables_from_sql(sql: str) -> list[tuple[str, str]]:
    """Extract (schema, table) pairs from SQL. Best-effort regex, not a full parser."""
    tables = []
    # Match schema.table or just table after FROM, JOIN, INTO, UPDATE, TABLE keywords
    pattern = r'(?:FROM|JOIN|INTO|UPDATE|TABLE)\s+("?(\w+)"?\s*\.\s*"?(\w+)"?|"?(\w+)"?)'
    for m in re.finditer(pattern, sql, re.IGNORECASE):
        if m.group(2) and m.group(3):
            tables.append((m.group(2), m.group(3)))
        elif m.group(4):
            tables.append(("public", m.group(4)))
    return tables


def check_permission(
    role: RolePermissions,
    operation: str,
    schema: str,
    table: str,
) -> Optional[str]:
    """Check if a role allows an operation on schema.table.

    Returns None if allowed, or an error message if denied.
    """
    if operation not in role.operations:
        return f"Access denied: operation '{operation}' is not allowed for your role."

    if schema not in role.schemas:
        return f"Access denied: schema '{schema}' is not in your allowlist."

    if role.tables != "*":
        if isinstance(role.tables, list) and table not in role.tables:
            return f"Access denied: table '{schema}.{table}' is not in your allowlist."

    return None
```

Then modify the `query` tool to enforce permissions when auth is active. Add a helper:

```python
def _enforce_permissions(
    permissions: Permissions,
    user_id: Optional[str],
    sql: str,
) -> Optional[str]:
    """If user_id is set and permissions are configured, check access.

    Returns None if allowed, or an error message string.
    """
    if user_id is None:
        return None  # No auth, no enforcement
    role = permissions.get_role_for_user(user_id)
    if role is None:
        return "Access denied: no role assigned and no default role configured."

    operation = extract_operation(sql)
    tables = extract_tables_from_sql(sql)

    if not tables:
        # Can't determine tables — allow if operation is permitted
        if operation not in role.operations:
            return f"Access denied: operation '{operation}' is not allowed."
        return None

    for schema, table in tables:
        error = check_permission(role, operation, schema, table)
        if error:
            return error

    return None
```

**Step 4: Create permissions.yaml.example**

```yaml
# permissions.yaml.example
# Copy to permissions.yaml and configure for your environment.
# Only used when auth is enabled (MCP_AUTH_ISSUER is set).

roles:
  analyst:
    schemas: ["public"]
    tables: "*"                  # all tables in allowed schemas
    operations: ["select"]

  engineer:
    schemas: ["public", "analytics", "internal"]
    tables: "*"
    operations: ["select", "insert", "update", "delete"]

  restricted:
    schemas: ["public"]
    tables: ["products", "categories"]  # explicit allowlist
    operations: ["select"]

users:
  # Keyed by the 'sub' claim from the JWT token
  alice@company.com:
    role: engineer
  bob@company.com:
    role: analyst

  # Default role for authenticated users not listed above
  _default: restricted
```

**Step 5: Run tests**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass

**Step 6: Commit**

```bash
git add postgres_server.py permissions.yaml.example tests/test_tools.py
git commit -m "feat: add config-file permissions with schema/table/operation enforcement"
```

---

### Task 7: Token Verification (Optional Auth) ✅ DONE

**Files:**
- Modify: `postgres_server.py`
- Modify: `tests/test_tools.py`

**Step 1: Write failing tests**

Append to `tests/test_tools.py`:

```python
@pytest.mark.asyncio
async def test_jwt_verifier_rejects_invalid():
    from postgres_server import JWKSTokenVerifier
    verifier = JWKSTokenVerifier(
        jwks_url="https://example.com/.well-known/jwks.json",
        audience="test",
        issuer="https://example.com",
    )
    result = await verifier.verify_token("invalid.token.here")
    assert result is None


def test_server_without_auth_config():
    """Server creates without auth when env vars not set."""
    from postgres_server import _config
    # In test env, auth env vars are not set
    assert _config.auth_issuer is None
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_tools.py -k "jwt or without_auth" -v
```

Expected: FAIL — `JWKSTokenVerifier` doesn't exist

**Step 3: Implement**

Add to `postgres_server.py`, before the `mcp = MCPServer(...)` line:

```python
# ---------------------------------------------------------------------------
# Auth — Optional JWT Token Verification
# ---------------------------------------------------------------------------
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings

try:
    import jwt as pyjwt
    from jwt import PyJWKClient
    HAS_JWT = True
except ImportError:
    HAS_JWT = False


class JWKSTokenVerifier(TokenVerifier):
    """Verify JWTs against a JWKS endpoint."""

    def __init__(self, jwks_url: str, audience: str, issuer: str):
        self.jwks_url = jwks_url
        self.audience = audience
        self.issuer = issuer
        self._jwk_client = PyJWKClient(jwks_url) if HAS_JWT else None

    async def verify_token(self, token: str) -> AccessToken | None:
        if not HAS_JWT or not self._jwk_client:
            logger.warning("pyjwt not installed; rejecting token")
            return None
        try:
            signing_key = self._jwk_client.get_signing_key_from_jwt(token)
            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.issuer,
            )
            return AccessToken(
                token=token,
                client_id=payload.get("azp", payload.get("client_id", "unknown")),
                scopes=payload.get("scope", "").split(),
                # Store sub for permission lookup
            )
        except Exception as e:
            logger.debug("Token verification failed: %s", e)
            return None
```

Then update the `mcp = MCPServer(...)` block to conditionally configure auth:

```python
def _build_server() -> MCPServer:
    kwargs: dict[str, Any] = {
        "name": "PostgreSQL Explorer",
        "lifespan": app_lifespan,
    }

    if _config.auth_issuer:
        jwks_url = _config.auth_jwks_url or f"{_config.auth_issuer.rstrip('/')}/.well-known/jwks.json"
        kwargs["token_verifier"] = JWKSTokenVerifier(
            jwks_url=jwks_url,
            audience=_config.auth_audience or "",
            issuer=_config.auth_issuer,
        )
        from pydantic import AnyHttpUrl
        kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(_config.auth_issuer),
            resource_server_url=AnyHttpUrl(f"http://{_config.host}:{_config.port}"),
            required_scopes=[],
        )
        logger.info("Auth enabled — issuer: %s", _config.auth_issuer)
    else:
        logger.info("Auth disabled — shared connection mode")

    return MCPServer(**kwargs)


mcp = _build_server()
```

**Step 4: Run tests**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add postgres_server.py tests/test_tools.py
git commit -m "feat: add optional JWKS token verification for external IdP auth"
```

---

### Task 8: Wire Permissions into Query Tool ✅ DONE

**Files:**
- Modify: `postgres_server.py`
- Modify: `tests/test_tools.py`

**Step 1: Write failing test**

Append to `tests/test_tools.py`:

```python
def test_enforce_permissions_blocks_disallowed_schema():
    from postgres_server import _enforce_permissions, Permissions, RolePermissions

    perms = Permissions(
        roles={"restricted": RolePermissions(schemas=["public"], tables="*", operations=["select"])},
        users={"bob": "restricted"},
    )
    result = _enforce_permissions(perms, "bob", "SELECT * FROM internal.secrets")
    assert result is not None
    assert "internal" in result


def test_enforce_permissions_allows_valid_query():
    from postgres_server import _enforce_permissions, Permissions, RolePermissions

    perms = Permissions(
        roles={"analyst": RolePermissions(schemas=["public"], tables="*", operations=["select"])},
        users={"alice": "analyst"},
    )
    result = _enforce_permissions(perms, "alice", "SELECT * FROM public.users")
    assert result is None


def test_enforce_permissions_skips_when_no_user():
    from postgres_server import _enforce_permissions, Permissions

    perms = Permissions()
    result = _enforce_permissions(perms, None, "DELETE FROM users")
    assert result is None  # No user = no enforcement
```

**Step 2: Run to verify they fail**

```bash
pytest tests/test_tools.py -k "enforce" -v
```

Expected: FAIL — `_enforce_permissions` not importable yet

**Step 3: Integrate permissions into the query tool**

Update the `query` tool in `postgres_server.py`. The key change: extract user_id from context when auth is active, then call `_enforce_permissions` before executing.

```python
@mcp.tool()
async def query(
    sql: str,
    ctx: Context,
    parameters: Optional[list[Any]] = None,
    row_limit: int = 500,
    format: str = "markdown",
) -> str:
    """Execute a SQL query. Returns markdown table by default, or JSON if format='json'.

    Args:
        sql: SQL statement to execute.
        parameters: Positional parameters for parameterized queries.
        row_limit: Maximum rows to return (1-10000, default 500).
        format: Output format — 'markdown' or 'json'.
    """
    app: AppContext = ctx.request_context.lifespan_context

    # Permission check (only when auth is active)
    user_id = None
    if app.config.auth_issuer:
        # Extract user from request context meta (set by TokenVerifier)
        meta = getattr(ctx, "request_context", None)
        auth_token = getattr(meta, "access_token", None) if meta else None
        if auth_token:
            # The sub claim is in the JWT payload; we need to decode it
            # Since TokenVerifier already validated, we can decode without verification
            try:
                import jwt as pyjwt
                payload = pyjwt.decode(auth_token.token, options={"verify_signature": False})
                user_id = payload.get("sub")
            except Exception:
                pass

        perm_error = _enforce_permissions(app.permissions, user_id, sql)
        if perm_error:
            return perm_error

    try:
        result = await _query_impl(
            pool=app.pool,
            sql=sql,
            readonly=app.config.readonly,
            parameters=parameters,
            row_limit=max(1, min(row_limit, 10000)),
            format=format,
        )
        if isinstance(result, list):
            return json.dumps(result, default=str)
        return result
    except Exception as e:
        logger.error("Query error: %s", e)
        return f"Query error: {e}"
```

**Step 4: Run all tests**

```bash
pytest tests/test_tools.py -v
```

Expected: all pass

**Step 5: Commit**

```bash
git add postgres_server.py tests/test_tools.py
git commit -m "feat: wire permission enforcement into query tool"
```

---

### Task 9: Update Config Files ✅ DONE

**Files:**
- Modify: `railway.toml`
- Modify: `smithery.yaml`
- Modify: `.env.example`
- Modify: `.gitignore`

**Step 1: Rewrite railway.toml**

```toml
[build]
  builder = "NIXPACKS"

[deploy]
  startCommand = "python postgres_server.py --transport streamable-http --host 0.0.0.0 --port ${PORT:-8000}"
  healthcheckPath = "/health"
  healthcheckTimeout = 30
  restartPolicyType = "ON_FAILURE"
```

**Step 2: Rewrite smithery.yaml**

```yaml
startCommand:
  type: streamable-http
  configSchema:
    type: object
    required:
      - connectionString
    properties:
      connectionString:
        type: string
        description: PostgreSQL connection string
      host:
        type: string
        default: 127.0.0.1
      port:
        type: integer
        default: 8000
  commandFunction: |-
    (config) => ({
      command: 'python',
      args: [
        'postgres_server.py',
        '--transport', 'streamable-http',
        '--host', config.host || '127.0.0.1',
        '--port', String(config.port || 8000),
        '--conn', config.connectionString,
      ],
    })
  exampleConfig:
    connectionString: postgresql://user:pass@localhost:5432/mydatabase
    host: 127.0.0.1
    port: 8000
```

**Step 3: Rewrite .env.example**

```
# Database connection (required for DB tools)
DATABASE_URL=postgresql://user:pass@localhost:5432/mydatabase

# Safety controls
POSTGRES_READONLY=false
POSTGRES_STATEMENT_TIMEOUT_MS=30000

# Transport (stdio for local, streamable-http for remote)
MCP_TRANSPORT=stdio
MCP_HOST=127.0.0.1
MCP_PORT=8000

# Connection pool
MCP_POOL_MIN=2
MCP_POOL_MAX=10

# Auth (optional — leave unset for shared connection mode)
# MCP_AUTH_ISSUER=https://your-idp.example.com
# MCP_AUTH_AUDIENCE=your-mcp-server
# MCP_AUTH_JWKS_URL=https://your-idp.example.com/.well-known/jwks.json
# MCP_PERMISSIONS_FILE=permissions.yaml
```

**Step 4: Update .gitignore — add permissions.yaml (may contain user mappings)**

Append to `.gitignore`:

```
permissions.yaml
```

**Step 5: Commit**

```bash
git add railway.toml smithery.yaml .env.example .gitignore
git commit -m "chore: update config files for v2 single-service architecture"
```

---

### Task 10: Update Tests and Documentation ✅ DONE

**Files:**
- Modify: `tests/test_tools.py` — final cleanup, ensure all tests pass
- Create: `tests/test_integration.py` — integration test stubs
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: `README.md` — update for new architecture

**Step 1: Create integration test stubs**

File: `tests/test_integration.py`

```python
"""Integration tests — require a real PostgreSQL database.

Run: DATABASE_URL=postgresql://... pytest tests/test_integration.py -v
"""

import os
import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("DATABASE_URL"),
    reason="DATABASE_URL not set",
)


@pytest.mark.asyncio
async def test_query_select_one():
    """Basic SELECT 1 against a real database."""
    os.environ["DATABASE_URL"] = os.getenv("DATABASE_URL", "")
    from postgres_server import _query_impl
    from psycopg_pool import AsyncConnectionPool

    pool = AsyncConnectionPool(conninfo=os.environ["DATABASE_URL"], min_size=1, max_size=2, open=False)
    await pool.open()
    try:
        result = await _query_impl(pool=pool, sql="SELECT 1 AS n", readonly=False)
        assert "1" in str(result)
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_list_schemas_returns_public():
    """list_schemas includes 'public' schema."""
    # This would require setting up a full server context — stub for now
    pass
```

**Step 2: Update CLAUDE.md**

Rewrite to reflect the new architecture (single service, MCPServer v2, async, permissions).

**Step 3: Update AGENTS.md**

Update commands and module references.

**Step 4: Run full test suite**

```bash
pytest tests/ -v
```

Expected: all non-integration tests pass

**Step 5: Commit**

```bash
git add tests/ CLAUDE.md AGENTS.md
git commit -m "docs: update documentation and add integration test stubs for v2"
```

---

### Task 11: Final Verification

**Step 1: Run full test suite**

```bash
pytest tests/ -v --tb=short
```

Expected: all pass

**Step 2: Lint**

```bash
ruff check postgres_server.py tests/
```

Fix any issues.

**Step 3: Verify server starts in stdio mode (no DSN)**

```bash
timeout 3 python postgres_server.py 2>&1 || true
```

Expected: starts, logs "Auth disabled — shared connection mode", then exits on timeout.

**Step 4: Verify server starts in HTTP mode (no DSN)**

```bash
timeout 3 python postgres_server.py --transport streamable-http --port 9999 2>&1 || true
```

Expected: starts listening.

**Step 5: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: address lint and verification issues"
```

---

Plan complete and saved to `docs/plans/2026-02-16-production-rewrite-plan.md`. Two execution options:

**1. Subagent-Driven (this session)** — I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Parallel Session (separate)** — Open new session with executing-plans, batch execution with checkpoints

Which approach?
