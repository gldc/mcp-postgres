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
async def app_lifespan(server: FastMCP) -> AsyncIterator[AppContext]:
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
mcp = FastMCP(
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
