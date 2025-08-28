#!/usr/bin/env python3
"""
Unified launcher for Railway deployments.

Runs either the MCP server or the OAuth companion service based on SERVICE_ROLE.

Usage (Railway): start command should be `python start.py`.

Configure per service via environment variable:
- SERVICE_ROLE=mcp   -> runs postgres_server.py (default)
- SERVICE_ROLE=oauth -> runs oauth_companion.py
"""

import os
import sys


def main() -> None:
    role = os.getenv("SERVICE_ROLE", "mcp").strip().lower()
    host = os.getenv("HOST", "0.0.0.0")
    port = os.getenv("PORT", "8000")

    if role == "oauth":
        # OAuth companion HTTP service with /health endpoint
        args = [
            sys.executable,
            "oauth_companion.py",
            "--host",
            host,
            "--port",
            str(port),
        ]
    else:
        # Default to MCP server using streamable-http for Railway
        args = [
            sys.executable,
            "postgres_server.py",
            "--transport",
            "streamable-http",
            "--host",
            host,
            "--port",
            str(port),
        ]

    # Replace current process with the target command
    os.execv(args[0], args)


if __name__ == "__main__":
    main()


