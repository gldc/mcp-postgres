# PostgreSQL MCP Server

[![smithery badge](https://smithery.ai/badge/@gldc/mcp-postgres)](https://smithery.ai/server/@gldc/mcp-postgres)

<a href="https://glama.ai/mcp/servers/@gldc/mcp-postgres">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@gldc/mcp-postgres/badge" />
</a>

A PostgreSQL MCP server implementation using the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) Python SDK- an open protocol that enables seamless integration between LLM applications and external data sources. This server allows AI agents to interact with PostgreSQL databases through a standardized interface.

## Features

- List database schemas
- List tables within schemas
- Describe table structures
- List table constraints and relationships
- Get foreign key information
- Execute SQL queries
- Typed tools with JSON/markdown output
- Optional table resources and guidance prompts

## Quick Start

```bash
# Run the server without a DB connection (useful for Glama or inspection)
python postgres_server.py

# With a live database – pick one method:
export POSTGRES_CONNECTION_STRING="postgresql://user:pass@host:5432/db"
python postgres_server.py

# …or…
python postgres_server.py --conn "postgresql://user:pass@host:5432/db"

# Or using Docker (build once, then run over HTTP):
# docker build -t mcp-postgres . && docker run -p 8000:8000 mcp-postgres \
#   python postgres_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

## Installation

### Installing via Smithery

To install PostgreSQL MCP Server for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@gldc/mcp-postgres):

```bash
npx -y @smithery/cli install @gldc/mcp-postgres --client claude
```

Note: The published Smithery server uses the Streamable HTTP transport by default, binding to the configured host/port.

Defaults (Smithery):
- Transport: Streamable HTTP
- Host: 127.0.0.1
- Port: 8000
You can override these in the Smithery server configuration.

### Manual Installation
1. Clone this repository:
```bash
git clone <repository-url>
cd mcp-postgres
```

2. Create and activate a virtual environment (recommended):
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows, use: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

## Usage

1. Start the MCP server.

   ```bash
   # Without a connection string (server starts, DB‑backed tools will return a friendly error)
   python postgres_server.py

   # Or set the connection string via environment variable:
   export POSTGRES_CONNECTION_STRING="postgresql://username:password@host:port/database"
   python postgres_server.py

   # Or pass it using the --conn flag:
   python postgres_server.py --conn "postgresql://username:password@host:port/database"

   # Optional: Run over HTTP transports
   # Streamable HTTP (recommended for streaming tool outputs)
   python postgres_server.py --transport streamable-http --host 0.0.0.0 --port 8000

   # SSE transport (server-sent events) mounted at /sse and /messages/
   python postgres_server.py --transport sse --host 0.0.0.0 --port 8000 --mount /mcp
   ```
2. The server provides the following tools:

- `query`: Execute SQL queries against the database
- `list_schemas`: List all available schemas
- `list_tables`: List all tables in a specific schema
- `describe_table`: Get detailed information about a table's structure
- `get_foreign_keys`: Get foreign key relationships for a table
- `find_relationships`: Discover both explicit and implied relationships for a table
- `db_identity`: Show current db/user/host/port, search_path, and version

Typed (preferred):
- `run_query(input)`: Execute with typed input (`sql`, `parameters`, `row_limit`, `format: 'markdown'|'json'`).
- `run_query_json(input)`: Execute and return JSON-serializable rows.
- `list_schemas_json(input)`: List schemas with filters (`include_system`, `include_temp`, `require_usage`, `row_limit`).
- `list_schemas_json_page(input)`: Paginated listing with filters and `name_like` pattern.
- `list_tables_json(input)`: List tables within a schema with filters (name pattern, case sensitivity, table_types, row_limit).
- `list_tables_json_page(input)`: Paginated tables listing with filters.

Examples:

```json
// run_query (markdown)
{
  "sql": "SELECT * FROM information_schema.tables WHERE table_schema = %s",
  "parameters": ["public"],
  "row_limit": 50,
  "format": "markdown"
}

// run_query_json
{
  "sql": "SELECT now() as ts",
  "row_limit": 1
}
```

Inspect current connection identity:

```json
// db_identity (no input)
{}
```

List schemas (JSON) with filters:

```json
{
  "include_system": false,
  "include_temp": false,
  "require_usage": true,
  "row_limit": 10000
}
```

Paginated list with pattern filter:

```json
{
  "include_system": false,
  "include_temp": false,
  "require_usage": true,
  "page_size": 200,
  "cursor": null,
  "name_like": "sales_*",
  "case_sensitive": false
}
```

Response shape:

```json
{
  "items": [ { "schema_name": "sales_eu", "owner": "...", "is_system": false, "is_temporary": false, "has_usage": true } ],
  "next_cursor": "...base64..." // null when no more pages
}
```

List tables with filters (JSON):

```json
{
  "db_schema": "public",
  "name_like": "orders_*",
  "case_sensitive": false,
  "table_types": ["BASE TABLE", "VIEW"],
  "row_limit": 1000
}
```

Paginated tables listing:

```json
{
  "db_schema": "public",
  "page_size": 200,
  "cursor": null,
  "name_like": "orders_%"
}
```

Resources (if supported by client):
- `table://{schema}/{table}` for reading table rows. Fallback tools are available:
  - `list_table_resources(schema)` → `table://...` URIs
  - `read_table_resource(schema, table, row_limit)` → rows JSON

Prompts (registered when supported; also exposed as tools):
- `write_safe_select` / `prompt_write_safe_select_tool`
- `explain_plan_tips` / `prompt_explain_plan_tips_tool`

### Running with Docker

Build the image:

```bash
docker build -t mcp-postgres .
```

Run the container over Streamable HTTP (inspectable without a DSN):

```bash
docker run -p 8000:8000 mcp-postgres \
  python postgres_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

Run with a live PostgreSQL database by supplying `POSTGRES_CONNECTION_STRING`:

```bash
docker run \
  -e POSTGRES_CONNECTION_STRING="postgresql://username:password@host:5432/database" \
  -p 8000:8000 \
  mcp-postgres \
  python postgres_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

*If the environment variable is omitted, the server boots normally and all database‑backed tools return a friendly “connection string is not set” message until you provide it.*

### Configuration with mcp.json

To integrate this server with MCP-compatible tools (like Cursor), add it to your `~/.cursor/mcp.json`:

```json
{
  "servers": {
    "postgres": {
      "command": "/path/to/.venv/bin/python",
      "args": [
        "/path/to/postgres_server.py"
      ],
      "env": {
        "POSTGRES_CONNECTION_STRING": "postgresql://username:password@host:5432/database?ssl=true"
      }
    }
  }
}
```

### Transport Environment Variables
- `MCP_TRANSPORT=stdio|sse|streamable-http` (default: `stdio`)
- `MCP_HOST=0.0.0.0` and `MCP_PORT=8000` for SSE/HTTP transports
- `MCP_SSE_MOUNT=/mcp` optional SSE mount path

Defaults: host `127.0.0.1`, port `8000`. `MCP_HOST`/`MCP_PORT` mirror the `--host/--port` flags.

*If `POSTGRES_CONNECTION_STRING` is omitted, the server still starts and is fully inspectable; database‑backed tools will simply return an informative error until the variable is provided.*

Replace:
- `/path/to/.venv` with your virtual environment path
- `/path/to/postgres_server.py` with the absolute path to the server script

### HTTP Client Integration

Run the server with Streamable HTTP:

```bash
python postgres_server.py --transport streamable-http --host 0.0.0.0 --port 8000
# or with Docker
docker run -p 8000:8000 mcp-postgres \
  python postgres_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

Basic reachability check (expect non-200 since MCP expects a handshake):

```bash
curl -i http://localhost:8000/mcp
# A 404/405/422 indicates the server is reachable; clients must speak MCP.
```

Example MCP client config (conceptual) pointing at the Streamable HTTP endpoint:

```json
{
  "servers": {
    "postgres": {
      "transport": "streamable-http",
      "url": "http://localhost:8000/mcp"
    }
  }
}
```

For SSE instead of Streamable HTTP:

```bash
python postgres_server.py --transport sse --host 0.0.0.0 --port 8000 --mount /mcp
curl -N http://localhost:8000/mcp/sse  # Connects to the SSE endpoint
```

#### Python MCP Client Example (Streamable HTTP)

```python
import asyncio
from mcp.client import streamable_http
from mcp.client.session import ClientSession


async def main():
    url = "http://localhost:8000/mcp"
    async with streamable_http.streamablehttp_client(url) as (read, write, _get_session_id):
        session = ClientSession(read, write)
        init = await session.initialize()
        print("protocol:", init.protocolVersion)

        # List tools
        tools = await session.list_tools()
        print("tools:", [t.name for t in tools.tools])

        # Call typed tool: run_query_json
        result = await session.call_tool(
            "run_query_json",
            {"input": {"sql": "SELECT 1 AS n", "row_limit": 1}},
        )
        # Prefer structuredContent if provided; fallback to text content
        if result.structuredContent is not None:
            print("structured:", result.structuredContent)
        else:
            print("text blocks:", [getattr(b, "text", None) for b in result.content])


if __name__ == "__main__":
    asyncio.run(main())
```

## Security

- Never expose sensitive database credentials in your code
- Use environment variables or secure configuration files for database connection strings
- Consider using connection pooling for better resource management
- Implement proper access controls and user authentication

### Environment options
- `POSTGRES_READONLY=true` to allow only SELECT/CTE/EXPLAIN/SHOW/VALUES
- `POSTGRES_STATEMENT_TIMEOUT_MS=15000` to cap statement runtime

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development & Tests
- Create a `.venv` and install runtime deps: `pip install -r requirements.txt`
- (Optional) install test deps: `pip install -r dev-requirements.txt`
- Run tests: `pytest -q`

## Related Projects

- [MCP Specification](https://github.com/modelcontextprotocol/specification)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Servers](https://github.com/modelcontextprotocol/servers)

## License

MIT License

Copyright (c) 2025 gldc

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
