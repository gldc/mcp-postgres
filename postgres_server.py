"""PostgreSQL MCP Server — production-ready, async, with optional auth."""

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

from mcp.server.auth.provider import AccessToken
from mcp.server.fastmcp import FastMCP, Context

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
    tables: Any = "*"  # str "*" means all tables, or list[str] for explicit allowlist
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


def extract_operation(sql: str) -> str:
    """Extract the SQL operation type from the first keyword."""
    token = sql.lstrip().split(None, 1)[0].lower() if sql.strip() else ""
    if token in {"select", "with", "show", "values", "explain"}:
        return "select"
    return token  # insert, update, delete, create, drop, etc.


def extract_tables_from_sql(sql: str) -> list[tuple[str, str]]:
    """Extract (schema, table) pairs from SQL. Best-effort regex, not a full parser."""
    tables = []
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
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
    permissions = load_permissions(_config.permissions_file)
    pool: Optional[AsyncConnectionPool] = None

    if _config.dsn:
        async def configure_conn(conn):
            await conn.set_autocommit(True)
            await conn.execute("SET application_name = 'mcp-postgres'")
            if _config.statement_timeout_ms and _config.statement_timeout_ms > 0:
                await conn.execute(
                    f"SET statement_timeout = {int(_config.statement_timeout_ms)}"
                )
            await conn.set_autocommit(False)

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
# Auth — Optional JWT Token Verification
# ---------------------------------------------------------------------------
try:
    import jwt as pyjwt
    from jwt import PyJWKClient
    HAS_JWT = True
except ImportError:
    HAS_JWT = False


class JWKSTokenVerifier:
    """Verify JWTs against a JWKS endpoint."""

    def __init__(self, jwks_url: str, audience: str, issuer: str):
        self.jwks_url = jwks_url
        self.audience = audience
        self.issuer = issuer
        self._jwk_client = PyJWKClient(jwks_url) if HAS_JWT else None

    async def verify_token(self, token: str) -> Optional[AccessToken]:
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
            )
        except Exception as e:
            logger.debug("Token verification failed: %s", e)
            return None


# ---------------------------------------------------------------------------
# Server instance
# ---------------------------------------------------------------------------
def _build_server() -> FastMCP:
    kwargs: dict[str, Any] = {
        "name": "PostgreSQL Explorer",
        "lifespan": app_lifespan,
        "host": _config.host,
        "port": _config.port,
    }

    if _config.auth_issuer:
        jwks_url = _config.auth_jwks_url or f"{_config.auth_issuer.rstrip('/')}/.well-known/jwks.json"
        kwargs["token_verifier"] = JWKSTokenVerifier(
            jwks_url=jwks_url,
            audience=_config.auth_audience or "",
            issuer=_config.auth_issuer,
        )
        from mcp.server.auth.settings import AuthSettings
        from pydantic import AnyHttpUrl
        kwargs["auth"] = AuthSettings(
            issuer_url=AnyHttpUrl(_config.auth_issuer),
            resource_server_url=AnyHttpUrl(f"http://{_config.host}:{_config.port}"),
            required_scopes=[],
        )
        logger.info("Auth enabled — issuer: %s", _config.auth_issuer)
    else:
        logger.info("Auth disabled — shared connection mode")

    return FastMCP(**kwargs)


mcp = _build_server()


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
) -> Any:
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

    # Permission check (only when auth is active)
    user_id = None
    if app.config.auth_issuer:
        meta = getattr(ctx, "request_context", None)
        auth_token = getattr(meta, "access_token", None) if meta else None
        if auth_token:
            try:
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
    import base64
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return json.dumps({"items": [], "next_cursor": None})

    offset = 0
    if cursor:
        try:
            offset = json.loads(base64.b64decode(cursor))["offset"]
        except Exception:
            offset = 0

    conditions = []
    params: list[Any] = []
    if not include_system:
        conditions.append("n.nspname NOT LIKE %s AND n.nspname != %s")
        params.extend(["pg_%", "information_schema"])
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
    import base64
    app: AppContext = ctx.request_context.lifespan_context
    if app.pool is None:
        return json.dumps({"items": [], "next_cursor": None})

    offset = 0
    if cursor:
        try:
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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info("Starting PostgreSQL MCP server — transport=%s", _config.transport)
    mcp.run(transport=_config.transport)
