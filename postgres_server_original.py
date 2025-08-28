from typing import Any, Optional, List, Dict
import psycopg
from psycopg.rows import dict_row
from mcp.server.fastmcp import FastMCP
import sys
import logging
import os
import argparse
import time
import json
import base64
from pydantic import BaseModel, Field
from typing import Literal

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('postgres-mcp-server')

mcp = FastMCP(
    "PostgreSQL Explorer",
    log_level="INFO"
)

# Connection string from --conn flag or POSTGRES_CONNECTION_STRING env var
parser = argparse.ArgumentParser(description="PostgreSQL Explorer MCP server")
parser.add_argument(
    "--conn",
    dest="conn",
    default=os.getenv("POSTGRES_CONNECTION_STRING"),
    help="PostgreSQL connection string or DSN"
)
parser.add_argument(
    "--transport",
    dest="transport",
    choices=["stdio", "sse", "streamable-http"],
    default=os.getenv("MCP_TRANSPORT", "stdio"),
    help="Transport protocol: stdio (default), sse, or streamable-http",
)
parser.add_argument(
    "--host",
    dest="host",
    default=os.getenv("MCP_HOST"),
    help="Host to bind for SSE/HTTP transports (default 127.0.0.1)",
)
parser.add_argument(
    "--port",
    dest="port",
    type=int,
    default=os.getenv("MCP_PORT"),
    help="Port to bind for SSE/HTTP transports (default 8000)",
)
parser.add_argument(
    "--mount",
    dest="mount",
    default=os.getenv("MCP_SSE_MOUNT"),
    help="Optional mount path for SSE transport (e.g., /mcp)",
)
args, _ = parser.parse_known_args()
CONNECTION_STRING: Optional[str] = args.conn

# Optional safety and performance controls via environment variables
READONLY: bool = os.getenv("POSTGRES_READONLY", "false").lower() in {"1", "true", "yes"}
STATEMENT_TIMEOUT_MS: Optional[int] = None
try:
    if os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS"):
        STATEMENT_TIMEOUT_MS = int(os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS"))
except ValueError:
    logger.warning("Invalid POSTGRES_STATEMENT_TIMEOUT_MS; ignoring")

logger.info(
    "Starting PostgreSQL MCP server – connection %s",
    ("to " + CONNECTION_STRING.split('@')[1]) if CONNECTION_STRING and '@' in CONNECTION_STRING else "(not set)"
)

def get_connection():
    if not CONNECTION_STRING:
        raise RuntimeError(
            "POSTGRES_CONNECTION_STRING is not set. Provide --conn DSN or export POSTGRES_CONNECTION_STRING."
        )
    try:
        conn = psycopg.connect(CONNECTION_STRING)
        logger.debug("Database connection established successfully")
        # Set session parameters for safety and observability
        with conn.cursor() as cur:
            try:
                cur.execute("SET application_name = %s", ("mcp-postgres",))
                if STATEMENT_TIMEOUT_MS and STATEMENT_TIMEOUT_MS > 0:
                    cur.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
                conn.commit()
            except Exception:
                conn.rollback()
        return conn
    except Exception as e:
        logger.error(f"Failed to establish database connection: {str(e)}")
        raise

@mcp.tool()
def server_info() -> Dict[str, Any]:
    """Return server and environment info useful for clients."""
    fastmcp_version = None
    try:
        import mcp.server.fastmcp as fastmcp_module  # type: ignore

        fastmcp_version = getattr(fastmcp_module, "__version__", None)
    except Exception:
        pass

    return {
        "name": "PostgreSQL Explorer",
        "readonly": READONLY,
        "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
        "fastmcp_version": fastmcp_version,
        "psycopg_version": getattr(psycopg, "__version__", None),
    }


@mcp.tool()
def db_identity() -> Dict[str, Any]:
    """Return current DB identity details: db, user, host, port, search_path, server version, cluster name."""
    conn = None
    try:
        try:
            conn = get_connection()
        except RuntimeError:
            return {}

        info: Dict[str, Any] = {}
        with conn.cursor(row_factory=dict_row) as cur:
            # Basic identity
            cur.execute(
                "SELECT current_database() AS database, current_user AS \"user\", "
                "inet_server_addr()::text AS host, inet_server_port() AS port"
            )
            row = cur.fetchone()
            if row:
                info.update(dict(row))

            # search_path
            cur.execute("SELECT current_schemas(true) AS search_path")
            row = cur.fetchone()
            if row and "search_path" in row:
                info["search_path"] = row["search_path"]

            # version and cluster name
            cur.execute(
                "SELECT name, setting FROM pg_settings WHERE name IN ('server_version','cluster_name')"
            )
            rows = cur.fetchall() or []
            for r in rows:
                if r.get("name") == "server_version":
                    info["server_version"] = r.get("setting")
                elif r.get("name") == "cluster_name":
                    info["cluster_name"] = r.get("setting")

        return info
    except Exception:
        return {}
    finally:
        if conn:
            conn.close()
            logger.debug("Database connection closed")


class QueryInput(BaseModel):
    sql: str = Field(description="SQL statement to execute")
    parameters: Optional[List[Any]] = Field(default=None, description="Positional parameters for the SQL")
    row_limit: int = Field(default=500, ge=1, le=10000, description="Max rows to return for SELECT queries")
    format: Literal["markdown", "json"] = Field(default="markdown", description="Output format for results")


class QueryJSONInput(BaseModel):
    sql: str
    parameters: Optional[List[Any]] = None
    row_limit: int = 500


def _is_select_like(sql: str) -> bool:
    token = sql.lstrip().split(" ", 1)[0].lower() if sql.strip() else ""
    return token in {"select", "with", "show", "values", "explain"}


def _exec_query(
    sql: str,
    parameters: Optional[List[Any]],
    row_limit: int,
    as_json: bool,
) -> Any:
    conn = None
    try:
        conn = get_connection()
        if READONLY and not _is_select_like(sql):
            return [] if as_json else "Read-only mode is enabled; only SELECT/CTE queries are allowed."

        with conn.cursor(row_factory=dict_row) as cur:
            t0 = time.time()
            if parameters:
                cur.execute(sql, parameters)
            else:
                cur.execute(sql)

            if cur.description is None:
                conn.commit()
                return [] if as_json else f"Query executed successfully. Rows affected: {cur.rowcount}"

            rows = cur.fetchmany(row_limit + (0 if as_json else 1))
            truncated = (not as_json) and (len(rows) > row_limit)
            if truncated:
                rows = rows[:row_limit]
            if as_json:
                return [dict(r) for r in rows]

            if not rows:
                return "No results found"

            duration_ms = int((time.time() - t0) * 1000)
            logger.info(f"Query returned {len(rows)} rows in {duration_ms}ms{' (truncated)' if truncated else ''}")
            # Markdown-like table
            keys: List[str] = list(rows[0].keys())
            result_lines = ["Results:", "--------", " | ".join(keys), " | ".join(["---"] * len(keys))]
            for row in rows:
                vals = []
                for k in keys:
                    v = row.get(k)
                    if v is None:
                        vals.append("NULL")
                    elif isinstance(v, (bytes, bytearray)):
                        vals.append(v.decode("utf-8", errors="replace"))
                    else:
                        vals.append(str(v).replace('%', '%%'))
                result_lines.append(" | ".join(vals))
            if truncated:
                result_lines.append(f"\nNote: Results truncated at {row_limit} rows. Increase row_limit to fetch more.")
            return "\n".join(result_lines)
    except Exception as e:
        return [] if as_json else f"Query error: {str(e)}\nQuery: {sql}"
    finally:
        if conn:
            conn.close()
            logger.debug("Database connection closed")


@mcp.tool()
def query(
    sql: str,
    parameters: Optional[List[Any]] = None,
    row_limit: int = 500,
    format: str = "markdown",
) -> str:
    """Execute a SQL query (legacy signature). Prefer run_query with typed input."""
    if not CONNECTION_STRING:
        return "POSTGRES_CONNECTION_STRING is not set. Provide --conn DSN or export POSTGRES_CONNECTION_STRING."
    as_json = (format.lower() == "json")
    res = _exec_query(sql, parameters, row_limit, as_json)
    if as_json and not isinstance(res, str):
        try:
            return json.dumps(res, default=str)
        except Exception as e:
            return f"JSON encoding error: {e}"
    return res  # type: ignore[return-value]


@mcp.tool()
def query_json(sql: str, parameters: Optional[List[Any]] = None, row_limit: int = 500) -> List[Dict[str, Any]]:
    """Execute a SQL query and return JSON-serializable rows (legacy signature). Prefer run_query_json with typed input."""
    if not CONNECTION_STRING:
        return []
    res = _exec_query(sql, parameters, row_limit, as_json=True)
    if isinstance(res, list):
        return res
    return []


@mcp.tool()
def run_query(input: QueryInput) -> str:
    """Execute a SQL query with typed input (preferred)."""
    if not CONNECTION_STRING:
        return "POSTGRES_CONNECTION_STRING is not set. Provide --conn DSN or export POSTGRES_CONNECTION_STRING."
    as_json = input.format == "json"
    res = _exec_query(input.sql, input.parameters, input.row_limit, as_json)
    if as_json and not isinstance(res, str):
        try:
            return json.dumps(res, default=str)
        except Exception as e:
            return f"JSON encoding error: {e}"
    return res  # type: ignore[return-value]


@mcp.tool()
def run_query_json(input: QueryJSONInput) -> List[Dict[str, Any]]:
    """Execute a SQL query and return JSON rows with typed input (preferred)."""
    if not CONNECTION_STRING:
        return []
    res = _exec_query(input.sql, input.parameters, input.row_limit, as_json=True)
    return res if isinstance(res, list) else []


# Table resources (best-effort): register MCP resources if supported; also expose tools as fallback
def _list_tables(schema: str = 'public') -> List[str]:
    res = _exec_query(
        sql=(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s ORDER BY table_name"
        ),
        parameters=[schema],
        row_limit=10000,
        as_json=True,
    )
    if isinstance(res, list):
        return [r.get('table_name') for r in res if isinstance(r, dict) and 'table_name' in r]
    return []


def _read_table(schema: str, table: str, row_limit: int = 100) -> List[Dict[str, Any]]:
    return _exec_query(
        sql=f"SELECT * FROM {schema}.\"{table}\"",
        parameters=None,
        row_limit=row_limit,
        as_json=True,
    ) or []


@mcp.tool()
def list_table_resources(schema: str = 'public') -> List[str]:
    """List resource URIs for tables in a schema (fallback for clients without resource support)."""
    return [f"table://{schema}/{t}" for t in _list_tables(schema)]


@mcp.tool()
def read_table_resource(schema: str, table: str, row_limit: int = 100) -> List[Dict[str, Any]]:
    """Read rows from a table resource (fallback)."""
    return _read_table(schema, table, row_limit)


# Try to register proper MCP resources if available in FastMCP
try:
    resource_decorator = getattr(mcp, "resource")
    if callable(resource_decorator):
        @resource_decorator("table://{schema}/{table}")
        def table_resource(schema: str, table: str, row_limit: int = 100):
            """Resource reader for table rows."""
            rows = _read_table(schema, table, row_limit)
            # Return as JSON string to be universally consumable
            return json.dumps(rows, default=str)
except Exception as e:
    logger.debug(f"Resource registration skipped: {e}")


# Prompts: best-effort FastMCP prompt registration with tool fallbacks
PROMPT_SAFE_SELECT = (
    "Write a safe, read-only SELECT using placeholders. Avoid DML/DDL. "
    "Prefer explicit column lists, add LIMIT, and filter with indexed columns when possible."
)
PROMPT_EXPLAIN_TIPS = (
    "Use EXPLAIN (ANALYZE, BUFFERS, VERBOSE) to inspect plans. "
    "Check seq vs index scans, join order, row estimates, and sort/hash nodes. Consider indexes or query rewrites."
)

try:
    prompt_decorator = getattr(mcp, "prompt")
    if callable(prompt_decorator):
        @prompt_decorator("write_safe_select")
        def prompt_write_safe_select():
            return PROMPT_SAFE_SELECT

        @prompt_decorator("explain_plan_tips")
        def prompt_explain_plan_tips():
            return PROMPT_EXPLAIN_TIPS
except Exception as e:
    logger.debug(f"Prompt registration skipped: {e}")


@mcp.tool()
def prompt_write_safe_select_tool() -> str:
    """Prompt: guidelines for writing safe SELECT queries."""
    return PROMPT_SAFE_SELECT


@mcp.tool()
def prompt_explain_plan_tips_tool() -> str:
    """Prompt: tips for reading EXPLAIN ANALYZE output."""
    return PROMPT_EXPLAIN_TIPS


class ListSchemasInput(BaseModel):
    include_system: bool = Field(default=False, description="Include pg_* and information_schema")
    include_temp: bool = Field(default=False, description="Include temporary schemas (pg_temp_*)")
    require_usage: bool = Field(default=True, description="Only list schemas with USAGE privilege")
    row_limit: int = Field(default=10000, ge=1, le=100000, description="Maximum number of schemas to return")
    name_like: Optional[str] = Field(default=None, description="Filter schema names by LIKE pattern (use % and _). '*' and '?' will be translated.")
    case_sensitive: bool = Field(default=False, description="When true, use LIKE instead of ILIKE for name_like")


@mcp.tool()
def list_schemas_json(input: ListSchemasInput) -> List[Dict[str, Any]]:
    """List schemas with filters and return JSON rows."""
    # Build dynamic WHERE conditions based on inputs
    conditions = []
    params: List[Any] = []

    if not input.include_system:
        conditions.append("NOT (n.nspname = 'information_schema' OR n.nspname LIKE 'pg_%')")
    if not input.include_temp:
        conditions.append("n.nspname NOT LIKE 'pg_temp_%'")
    if input.require_usage:
        conditions.append("has_schema.priv")

    # Name filter
    if input.name_like:
        pattern = input.name_like.replace('*', '%').replace('?', '_')
        op = 'LIKE' if input.case_sensitive else 'ILIKE'
        conditions.append(f"n.nspname {op} %s")
        params.append(pattern)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    limit_clause = " LIMIT %s"
    params.append(input.row_limit)

    sql = f"""
    WITH has_schema AS (
        SELECT n.oid AS oid, has_schema_privilege(n.nspname, 'USAGE') AS priv
        FROM pg_namespace n
    )
    SELECT 
        n.nspname AS schema_name,
        pg_get_userbyid(n.nspowner) AS owner,
        (n.nspname = 'information_schema' OR n.nspname LIKE 'pg_%') AS is_system,
        (n.nspname LIKE 'pg_temp_%') AS is_temporary,
        has_schema.priv AS has_usage
    FROM pg_namespace n
    JOIN has_schema ON has_schema.oid = n.oid
    {where_clause}
    ORDER BY n.nspname
    {limit_clause}
    """

    res = _exec_query(sql, params, input.row_limit, as_json=True)
    return res if isinstance(res, list) else []


class ListSchemasPageInput(BaseModel):
    include_system: bool = False
    include_temp: bool = False
    require_usage: bool = True
    page_size: int = Field(default=500, ge=1, le=10000)
    cursor: Optional[str] = None
    name_like: Optional[str] = None
    case_sensitive: bool = False


@mcp.tool()
def list_schemas_json_page(input: ListSchemasPageInput) -> Dict[str, Any]:
    """List schemas with pagination and filters. Returns { items: [...], next_cursor: str|null }"""
    # Decode cursor (simple base64-encoded JSON {"offset": int})
    offset = 0
    if input.cursor:
        try:
            payload = json.loads(base64.b64decode(input.cursor).decode('utf-8'))
            offset = int(payload.get('offset', 0))
        except Exception:
            offset = 0

    # Build conditions
    conditions = []
    params: List[Any] = []

    if not input.include_system:
        conditions.append("NOT (n.nspname = 'information_schema' OR n.nspname LIKE 'pg_%')")
    if not input.include_temp:
        conditions.append("n.nspname NOT LIKE 'pg_temp_%'")
    if input.require_usage:
        conditions.append("has_schema.priv")
    if input.name_like:
        pattern = input.name_like.replace('*', '%').replace('?', '_')
        op = 'LIKE' if input.case_sensitive else 'ILIKE'
        conditions.append(f"n.nspname {op} %s")
        params.append(pattern)

    where_clause = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Fetch one extra to determine if there is a next page
    limit = input.page_size + 1
    sql = f"""
    WITH has_schema AS (
        SELECT n.oid AS oid, has_schema_privilege(n.nspname, 'USAGE') AS priv
        FROM pg_namespace n
    )
    SELECT 
        n.nspname AS schema_name,
        pg_get_userbyid(n.nspowner) AS owner,
        (n.nspname = 'information_schema' OR n.nspname LIKE 'pg_%') AS is_system,
        (n.nspname LIKE 'pg_temp_%') AS is_temporary,
        has_schema.priv AS has_usage
    FROM pg_namespace n
    JOIN has_schema ON has_schema.oid = n.oid
    {where_clause}
    ORDER BY n.nspname
    LIMIT %s OFFSET %s
    """
    params_with_pagination = params + [limit, offset]
    rows = _exec_query(sql, params_with_pagination, limit, as_json=True)
    items: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    if isinstance(rows, list):
        if len(rows) > input.page_size:
            items = rows[: input.page_size]
            next_cursor = base64.b64encode(json.dumps({"offset": offset + input.page_size}).encode('utf-8')).decode('utf-8')
        else:
            items = rows

    return {"items": items, "next_cursor": next_cursor}


class ListTablesInput(BaseModel):
    db_schema: Optional[str] = Field(default=None, description="Schema to list tables from; defaults to current_schema()")
    name_like: Optional[str] = Field(default=None, description="Filter table_name by pattern; '*' and '?' translate to SQL wildcards")
    case_sensitive: bool = Field(default=False, description="Use LIKE (true) or ILIKE (false) for name_like")
    table_types: Optional[List[str]] = Field(
        default=None,
        description="Limit to specific information_schema table_type values (e.g., 'BASE TABLE','VIEW')",
    )
    row_limit: int = Field(default=10000, ge=1, le=100000)


@mcp.tool()
def list_tables_json(input: ListTablesInput) -> List[Dict[str, Any]]:
    """List tables in a schema with optional filters and return JSON rows."""
    eff_schema = input.db_schema or _get_current_schema()

    conditions = ["table_schema = %s"]
    params: List[Any] = [eff_schema]

    if input.name_like:
        pattern = input.name_like.replace('*', '%').replace('?', '_')
        op = 'LIKE' if input.case_sensitive else 'ILIKE'
        conditions.append(f"table_name {op} %s")
        params.append(pattern)

    if input.table_types:
        placeholders = ",".join(["%s"] * len(input.table_types))
        conditions.append(f"table_type IN ({placeholders})")
        params.extend(input.table_types)

    where_clause = " AND ".join(conditions)

    sql = f"""
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE {where_clause}
    ORDER BY table_name
    LIMIT %s
    """
    params.append(input.row_limit)

    res = _exec_query(sql, params, input.row_limit, as_json=True)
    return res if isinstance(res, list) else []


class ListTablesPageInput(BaseModel):
    db_schema: Optional[str] = None
    name_like: Optional[str] = None
    case_sensitive: bool = False
    table_types: Optional[List[str]] = None
    page_size: int = Field(default=500, ge=1, le=10000)
    cursor: Optional[str] = None


@mcp.tool()
def list_tables_json_page(input: ListTablesPageInput) -> Dict[str, Any]:
    """List tables with pagination and filters. Returns { items, next_cursor }."""
    eff_schema = input.db_schema or _get_current_schema()

    # Decode cursor
    offset = 0
    if input.cursor:
        try:
            payload = json.loads(base64.b64decode(input.cursor).decode('utf-8'))
            offset = int(payload.get('offset', 0))
        except Exception:
            offset = 0

    conditions = ["table_schema = %s"]
    params: List[Any] = [eff_schema]

    if input.name_like:
        pattern = input.name_like.replace('*', '%').replace('?', '_')
        op = 'LIKE' if input.case_sensitive else 'ILIKE'
        conditions.append(f"table_name {op} %s")
        params.append(pattern)

    if input.table_types:
        placeholders = ",".join(["%s"] * len(input.table_types))
        conditions.append(f"table_type IN ({placeholders})")
        params.extend(input.table_types)

    where_clause = " AND ".join(conditions)
    limit = input.page_size + 1

    sql = f"""
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE {where_clause}
    ORDER BY table_name
    LIMIT %s OFFSET %s
    """
    params_with_pagination = params + [limit, offset]
    rows = _exec_query(sql, params_with_pagination, limit, as_json=True)

    items: List[Dict[str, Any]] = []
    next_cursor: Optional[str] = None
    if isinstance(rows, list):
        if len(rows) > input.page_size:
            items = rows[: input.page_size]
            next_cursor = base64.b64encode(json.dumps({"offset": offset + input.page_size}).encode('utf-8')).decode('utf-8')
        else:
            items = rows

    return {"items": items, "next_cursor": next_cursor}

@mcp.tool()
def list_schemas() -> str:
    """List all schemas in the database."""
    logger.info("Listing database schemas")
    # Increase row limit to avoid truncation in large catalogs
    return query(
        "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name",
        None,
        10000,
    )

def _get_current_schema() -> str:
    try:
        res = _exec_query("SELECT current_schema() AS schema", None, 1, as_json=True)
        if isinstance(res, list) and res:
            schema = res[0].get("schema")
            if isinstance(schema, str) and schema:
                return schema
    except Exception:
        pass
    return "public"


@mcp.tool()
def list_tables(db_schema: Optional[str] = None) -> str:
    """List all tables in a specific schema.
    
    Args:
        db_schema: The schema name to list tables from (defaults to 'public')
    """
    eff_schema = db_schema or _get_current_schema()
    logger.info(f"Listing tables in schema: {eff_schema}")
    sql = """
    SELECT table_name, table_type
    FROM information_schema.tables
    WHERE table_schema = %s
    ORDER BY table_name
    """
    return query(sql, [eff_schema])

@mcp.tool()
def describe_table(table_name: str, db_schema: Optional[str] = None) -> str:
    """Get detailed information about a table.
    
    Args:
        table_name: The name of the table to describe
        db_schema: The schema name (defaults to 'public')
    """
    eff_schema = db_schema or _get_current_schema()
    logger.info(f"Describing table: {eff_schema}.{table_name}")
    sql = """
    SELECT 
        column_name,
        data_type,
        is_nullable,
        column_default,
        character_maximum_length
    FROM information_schema.columns
    WHERE table_schema = %s AND table_name = %s
    ORDER BY ordinal_position
    """
    return query(sql, [eff_schema, table_name])

@mcp.tool()
def get_foreign_keys(table_name: str, db_schema: Optional[str] = None) -> str:
    """Get foreign key information for a table.
    
    Args:
        table_name: The name of the table to get foreign keys from
        db_schema: The schema name (defaults to 'public')
    """
    eff_schema = db_schema or _get_current_schema()
    logger.info(f"Getting foreign keys for table: {eff_schema}.{table_name}")
    sql = """
    SELECT 
        tc.constraint_name,
        kcu.column_name as fk_column,
        ccu.table_schema as referenced_schema,
        ccu.table_name as referenced_table,
        ccu.column_name as referenced_column
    FROM information_schema.table_constraints tc
    JOIN information_schema.key_column_usage kcu
        ON tc.constraint_name = kcu.constraint_name
        AND tc.table_schema = kcu.table_schema
    JOIN information_schema.referential_constraints rc
        ON tc.constraint_name = rc.constraint_name
    JOIN information_schema.constraint_column_usage ccu
        ON rc.unique_constraint_name = ccu.constraint_name
    WHERE tc.constraint_type = 'FOREIGN KEY'
        AND tc.table_schema = %s
        AND tc.table_name = %s
    ORDER BY tc.constraint_name, kcu.ordinal_position
    """
    return query(sql, [eff_schema, table_name])

@mcp.tool()
def find_relationships(table_name: str, db_schema: Optional[str] = None) -> str:
    """Find both explicit and implied relationships for a table.
    
    Args:
        table_name: The name of the table to analyze relationships for
        db_schema: The schema name (defaults to 'public')
    """
    eff_schema = db_schema or _get_current_schema()
    logger.info(f"Finding relationships for table: {eff_schema}.{table_name}")
    try:
        # First get explicit foreign key relationships
        fk_sql = """
        SELECT 
            kcu.column_name,
            ccu.table_name as foreign_table,
            ccu.column_name as foreign_column,
            'Explicit FK' as relationship_type,
            1 as confidence_level
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu 
            ON tc.constraint_name = kcu.constraint_name
            AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
            ON ccu.constraint_name = tc.constraint_name
            AND ccu.table_schema = tc.table_schema
        WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = %s
            AND tc.table_name = %s
        """
        
        logger.debug("Querying explicit foreign key relationships")
        explicit_results = query(fk_sql, [eff_schema, table_name])
        
        # Then look for implied relationships based on common patterns
        logger.debug("Querying implied relationships")
        implied_sql = """
        WITH source_columns AS (
            -- Get all ID-like columns from our table
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = %s 
            AND table_name = %s
            AND (
                column_name LIKE '%%id' 
                OR column_name LIKE '%%_id'
                OR column_name LIKE '%%_fk'
            )
        ),
        potential_references AS (
            -- Find tables that might be referenced by our ID columns
            SELECT DISTINCT
                sc.column_name as source_column,
                sc.data_type as source_type,
                t.table_name as target_table,
                c.column_name as target_column,
                c.data_type as target_type,
                CASE
                    -- Highest confidence: column matches table_id pattern and types match
                    WHEN sc.column_name = t.table_name || '_id' 
                        AND sc.data_type = c.data_type THEN 2
                    -- High confidence: column ends with _id and types match
                    WHEN sc.column_name LIKE '%%_id' 
                        AND sc.data_type = c.data_type THEN 3
                    -- Medium confidence: column contains table name and types match
                    WHEN sc.column_name LIKE '%%' || t.table_name || '%%'
                        AND sc.data_type = c.data_type THEN 4
                    -- Lower confidence: column ends with id and types match
                    WHEN sc.column_name LIKE '%%id'
                        AND sc.data_type = c.data_type THEN 5
                END as confidence_level
            FROM source_columns sc
            CROSS JOIN information_schema.tables t
            JOIN information_schema.columns c 
                ON c.table_schema = t.table_schema 
                AND c.table_name = t.table_name
                AND (c.column_name = 'id' OR c.column_name = sc.column_name)
            WHERE t.table_schema = %s
                AND t.table_name != %s  -- Exclude self-references
        )
        SELECT 
            source_column as column_name,
            target_table as foreign_table,
            target_column as foreign_column,
            CASE 
                WHEN confidence_level = 2 THEN 'Strong implied relationship (exact match)'
                WHEN confidence_level = 3 THEN 'Strong implied relationship (_id pattern)'
                WHEN confidence_level = 4 THEN 'Likely implied relationship (name match)'
                ELSE 'Possible implied relationship'
            END as relationship_type,
            confidence_level
        FROM potential_references
        WHERE confidence_level IS NOT NULL
        ORDER BY confidence_level, source_column;
        """
        implied_results = query(implied_sql, [eff_schema, table_name])
        
        return "Explicit Relationships:\n" + explicit_results + "\n\nImplied Relationships:\n" + implied_results
        
    except Exception as e:
        error_msg = f"Error finding relationships: {str(e)}"
        logger.error(error_msg)
        return error_msg

if __name__ == "__main__":
    try:
        # Configure host/port for network transports if provided
        if args.host:
            mcp.settings.host = args.host
        if args.port:
            try:
                mcp.settings.port = int(args.port)
            except Exception:
                pass

        logger.info(
            "Starting MCP Postgres server using %s transport on %s:%s",
            args.transport,
            mcp.settings.host,
            mcp.settings.port,
        )
        if args.transport == "sse":
            mcp.run(transport="sse", mount_path=args.mount)
        else:
            mcp.run(transport=args.transport)
    except Exception as e:
        logger.error(f"Server error: {str(e)}")
        sys.exit(1)
