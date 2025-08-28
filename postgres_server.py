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
import sqlite3
from datetime import datetime
import threading
from urllib.parse import urlparse

# Configure logging
def setup_logging():
    railway_env = os.getenv('RAILWAY_ENVIRONMENT', 'development')
    if railway_env == 'production':
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]  # Railway captures stdout
        )
    else:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

setup_logging()
logger = logging.getLogger('postgres-mcp-server')

# Railway-specific environment handling
def get_railway_config():
    """Get Railway-specific configuration"""
    config = {
        'port': int(os.getenv('PORT', 8000)),
        'host': '0.0.0.0' if os.getenv('RAILWAY_ENVIRONMENT') else '127.0.0.1',
        'database_url': os.getenv('DATABASE_URL'),  # Railway provides this
        'public_domain': os.getenv('RAILWAY_PUBLIC_DOMAIN'),
        'environment': os.getenv('RAILWAY_ENVIRONMENT', 'development')
    }
    
    # Set redirect URI based on Railway domain
    if config['public_domain']:
        config['redirect_uri'] = f"https://{config['public_domain']}/auth/callback"
    else:
        config['redirect_uri'] = os.getenv('REDIRECT_URI', 'http://localhost:8000/auth/callback')
    
    return config

railway_config = get_railway_config()

# OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY")
REDIRECT_URI = railway_config['redirect_uri']

# Simple session storage for development (use Redis/database for production)
class SessionManager:
    def __init__(self):
        self.db_path = "user_sessions.db"
        self.init_db()
        self.lock = threading.Lock()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                connection_string TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()
        conn.close()
    
    def store_user_session(self, user_id: str, email: str, connection_string: str = None):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO user_sessions 
                (user_id, email, connection_string, last_accessed) 
                VALUES (?, ?, ?, ?)
            """, (user_id, email, connection_string, datetime.now()))
            conn.commit()
            conn.close()
    
    def get_user_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, email, connection_string, created_at, last_accessed 
                FROM user_sessions WHERE user_id = ?
            """, (user_id,))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                return {
                    "user_id": row[0],
                    "email": row[1],
                    "connection_string": row[2],
                    "created_at": row[3],
                    "last_accessed": row[4]
                }
            return None
    
    def update_connection_string(self, user_id: str, connection_string: str):
        with self.lock:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_sessions 
                SET connection_string = ?, last_accessed = ? 
                WHERE user_id = ?
            """, (connection_string, datetime.now(), user_id))
            conn.commit()
            conn.close()

session_manager = SessionManager()

# Update argument parsing
parser = argparse.ArgumentParser(description="PostgreSQL Explorer MCP server with OAuth")
parser.add_argument(
    "--conn",
    dest="conn",
    default=railway_config['database_url'] or os.getenv("POSTGRES_CONNECTION_STRING"),
    help="Default PostgreSQL connection string (optional when using OAuth)"
)
parser.add_argument(
    "--transport",
    dest="transport",
    choices=["stdio", "sse", "streamable-http"],
    default=os.getenv("MCP_TRANSPORT", "streamable-http" if railway_config['environment'] == 'production' else "stdio"),
    help="Transport protocol: stdio, sse, or streamable-http",
)
parser.add_argument(
    "--host",
    dest="host",
    default=railway_config['host'],
    help="Host to bind for SSE/HTTP transports",
)
parser.add_argument(
    "--port",
    dest="port",
    type=int,
    default=railway_config['port'],
    help="Port to bind for SSE/HTTP transports",
)
parser.add_argument(
    "--mount",
    dest="mount",
    default=os.getenv("MCP_SSE_MOUNT"),
    help="Optional mount path for SSE transport (e.g., /mcp)",
)
parser.add_argument(
    "--oauth-only",
    dest="oauth_only",
    action="store_true",
    help="Require OAuth authentication (disable direct connection string mode)",
)

args, _ = parser.parse_known_args()
CONNECTION_STRING: Optional[str] = args.conn
OAUTH_ONLY = args.oauth_only or railway_config['environment'] == 'production'

# Optional safety and performance controls via environment variables
READONLY: bool = os.getenv("POSTGRES_READONLY", "false").lower() in {"1", "true", "yes"}
STATEMENT_TIMEOUT_MS: Optional[int] = None
try:
    if os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS"):
        STATEMENT_TIMEOUT_MS = int(os.getenv("POSTGRES_STATEMENT_TIMEOUT_MS"))
except ValueError:
    logger.warning("Invalid POSTGRES_STATEMENT_TIMEOUT_MS; ignoring")

logger.info(
    "Starting PostgreSQL MCP server – %s environment – %s mode",
    railway_config['environment'],
    "OAuth-ready" if (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET) else "Direct connection"
)

# Connection handling
def get_connection():
    # For now, use the default connection string
    # In a production OAuth setup, this would be enhanced to use user-specific connections
    if not CONNECTION_STRING:
        raise RuntimeError(
            "Database connection not configured. " +
            ("Use auth_info tool to get authentication instructions." if OAUTH_ONLY 
             else "Provide --conn DSN or export POSTGRES_CONNECTION_STRING.")
        )
    try:
        conn = psycopg.connect(CONNECTION_STRING)
        logger.debug("Database connection established successfully")
        # Set session parameters for safety and observability
        with conn.cursor() as cur:
            try:
                cur.execute("SET application_name = %s", ("mcp-postgres-oauth",))
                if STATEMENT_TIMEOUT_MS and STATEMENT_TIMEOUT_MS > 0:
                    cur.execute("SET statement_timeout = %s", (STATEMENT_TIMEOUT_MS,))
                conn.commit()
            except Exception:
                conn.rollback()
        return conn
    except Exception as e:
        logger.error(f"Failed to establish database connection: {str(e)}")
        raise

# Create the MCP server
mcp = FastMCP(
    "PostgreSQL Explorer with OAuth Support",
    log_level="INFO"
)

@mcp.tool()
def auth_info() -> Dict[str, Any]:
    """Return authentication and configuration info."""
    oauth_configured = bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
    
    base_url = "https://" + railway_config['public_domain'] if railway_config['public_domain'] else f"http://{args.host}:{args.port}"
    
    info = {
        "service": "PostgreSQL MCP Server with OAuth Support",
        "oauth_configured": oauth_configured,
        "oauth_only_mode": OAUTH_ONLY,
        "has_default_connection": bool(CONNECTION_STRING and not OAUTH_ONLY),
        "environment": railway_config['environment'],
        "server_url": base_url,
    }
    
    if oauth_configured:
        info.update({
            "oauth_setup_required": True,
            "instructions": {
                "1": "This server supports OAuth authentication but requires external setup",
                "2": f"OAuth Login URL: {base_url}/auth/login",
                "3": f"OAuth Status URL: {base_url}/auth/status", 
                "4": f"Set Connection URL: {base_url}/connection/set",
                "5": "For full OAuth functionality, deploy this server with FastAPI endpoints",
                "note": "Current MCP-only mode provides database tools but limited OAuth integration"
            }
        })
    else:
        info.update({
            "instructions": {
                "note": "OAuth not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables to enable OAuth support."
            }
        })
    
    return info

@mcp.tool()
def server_info() -> Dict[str, Any]:
    """Return server and environment info useful for clients."""
    fastmcp_version = None
    try:
        import mcp.server.fastmcp as fastmcp_module
        fastmcp_version = getattr(fastmcp_module, "__version__", None)
    except Exception:
        pass

    return {
        "name": "PostgreSQL Explorer with OAuth Support",
        "readonly": READONLY,
        "statement_timeout_ms": STATEMENT_TIMEOUT_MS,
        "fastmcp_version": fastmcp_version,
        "psycopg_version": getattr(psycopg, "__version__", None),
        "oauth_enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "oauth_only": OAUTH_ONLY,
        "environment": railway_config['environment'],
        "railway_domain": railway_config['public_domain'],
        "server_mode": "MCP with OAuth configuration support"
    }

@mcp.tool()
def health_check() -> Dict[str, Any]:
    """Health check for monitoring"""
    try:
        # Test database connectivity if available
        if CONNECTION_STRING:
            conn = get_connection()
            conn.close()
            db_status = "connected"
        else:
            db_status = "not_configured"
        
        return {
            "status": "healthy",
            "service": "PostgreSQL MCP Server with OAuth Support",
            "oauth_enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
            "database_status": db_status,
            "environment": railway_config['environment']
        }
    except Exception as e:
        return {
            "status": "unhealthy", 
            "error": str(e),
            "service": "PostgreSQL MCP Server with OAuth Support"
        }

@mcp.tool()
def db_identity() -> Dict[str, Any]:
    """Return current DB identity details: db, user, host, port, search_path, server version, cluster name."""
    conn = None
    try:
        try:
            conn = get_connection()
        except RuntimeError as e:
            return {"error": str(e)}

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
    except Exception as e:
        return {"error": str(e)}
    finally:
        if conn:
            conn.close()
            logger.debug("Database connection closed")

# All the existing database tools remain the same
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
    """Execute a SQL query and return JSON-serializable rows (legacy signature)."""
    res = _exec_query(sql, parameters, row_limit, as_json=True)
    if isinstance(res, list):
        return res
    return []

@mcp.tool()
def run_query(input: QueryInput) -> str:
    """Execute a SQL query with typed input (preferred)."""
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
    res = _exec_query(input.sql, input.parameters, input.row_limit, as_json=True)
    return res if isinstance(res, list) else []

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
def list_schemas() -> str:
    """List all schemas in the database."""
    logger.info("Listing database schemas")
    return query(
        "SELECT schema_name FROM information_schema.schemata ORDER BY schema_name",
        None,
        10000,
    )

@mcp.tool()
def list_tables(db_schema: Optional[str] = None) -> str:
    """List all tables in a specific schema.
    
    Args:
        db_schema: The schema name to list tables from (defaults to current schema)
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
        db_schema: The schema name (defaults to current schema)
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
        db_schema: The schema name (defaults to current schema)
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
        db_schema: The schema name (defaults to current schema)
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
        
        explicit_results = query(fk_sql, [eff_schema, table_name])
        return f"Relationships for {eff_schema}.{table_name}:\n{explicit_results}"
        
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
            "Starting PostgreSQL MCP server using %s transport on %s:%s",
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
