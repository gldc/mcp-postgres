# PostgreSQL MCP Server with OAuth

[![smithery badge](https://smithery.ai/badge/@gldc/mcp-postgres)](https://smithery.ai/server/@gldc/mcp-postgres)

<a href="https://glama.ai/mcp/servers/@gldc/mcp-postgres">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@gldc/mcp-postgres/badge" />
</a>

A PostgreSQL MCP server implementation with **OAuth authentication** support using the [Model Context Protocol (MCP)](https://github.com/modelcontextprotocol) Python SDK. This server enables AI agents to interact with PostgreSQL databases through a standardized interface, with secure multi-user authentication and cloud deployment capabilities.

## ✨ New Features

- **🔐 OAuth Authentication**: Secure Google OAuth 2.0 integration
- **👥 Multi-tenant**: Each user has their own database connection
- **☁️ Railway Ready**: Optimized for Railway cloud deployment  
- **🛡️ Production Safe**: Session management, security controls, and health monitoring

## Features

### Core Database Operations
- List database schemas with advanced filtering and pagination
- List tables within schemas with pattern matching
- Describe table structures and constraints
- Discover table relationships (explicit foreign keys + implied relationships)
- Execute SQL queries with safety controls
- Typed tools with JSON/markdown output
- Optional table resources and guidance prompts

### Authentication & Security
- **Google OAuth 2.0**: Secure user authentication
- **Session Management**: Token-based sessions with expiration
- **User Isolation**: Each user's database connections are separate
- **Read-only Mode**: Optional query restrictions
- **Query Timeouts**: Prevent runaway queries
- **Health Monitoring**: Built-in health checks and metrics

### Deployment Options
- **Local Development**: Direct database connections
- **OAuth Mode**: Multi-user authentication with personal database connections
- **Railway Cloud**: One-click cloud deployment with managed PostgreSQL
- **Docker**: Containerized deployment

## 🚀 Quick Start

### Option 1: Traditional Mode (Direct Connection)
```bash
# Run with direct database connection (original behavior)
export POSTGRES_CONNECTION_STRING="postgresql://user:pass@host:5432/db"
python postgres_server.py

# Or pass connection string as argument
python postgres_server.py --conn "postgresql://user:pass@host:5432/db"
```

### Option 2: OAuth Mode (Multi-user)
```bash
# Set up OAuth credentials (see OAUTH_SETUP.md for details)
export GOOGLE_CLIENT_ID="your_client_id.apps.googleusercontent.com"
export GOOGLE_CLIENT_SECRET="your_client_secret"
export SECRET_KEY="your_32_character_secret_key"

# Run in OAuth mode
python postgres_server.py --oauth-only --transport streamable-http --port 8000
```

### Option 3: Railway Cloud Deployment
```bash
# One-click deployment to Railway (see RAILWAY_DEPLOYMENT.md)
# 1. Push code to GitHub
# 2. Connect Railway to your repository
# 3. Create TWO services from this repo (same project):
#    - Service A (MCP server): default settings (SERVICE_ROLE defaults to mcp)
#    - Service B (OAuth companion): set SERVICE_ROLE=oauth; optionally set Environment=oauth
# 4. Add PostgreSQL to the project (Railway sets DATABASE_URL)
# 5. Set GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET / SECRET_KEY at project level
# 6. Deploy (railway.toml uses unified launcher: `python start.py`)
```

## 📚 Documentation

- **[OAUTH_SETUP.md](./OAUTH_SETUP.md)** - Complete OAuth setup guide
- **[RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md)** - Railway cloud deployment guide

## Installation

### Installing via Smithery

To install PostgreSQL MCP Server for Claude Desktop automatically via [Smithery](https://smithery.ai/server/@gldc/mcp-postgres):

```bash
npx -y @smithery/cli install @gldc/mcp-postgres --client claude
```

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

### Authentication Flow (OAuth Mode)

1. **Start the server in OAuth mode**:
   ```bash
   python postgres_server.py --oauth-only --transport streamable-http --port 8000
   ```

2. **Get authentication info** (via MCP client like Claude):
   ```
   User: "Show me information about the database server"
   Claude: [Calls auth_info tool, provides Google OAuth login URL]
   ```

3. **Complete OAuth flow**:
   - Visit the provided login URL
   - Authenticate with Google  
   - Receive session token

4. **Configure database connection**:
   - Browser: visit `http://localhost:8000/connection` (uses your session cookie)
   - API:
     ```bash
     curl -X POST http://localhost:8000/connection/set \
       -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"connection_string": "postgresql://user:pass@host:port/db"}'
     ```

5. **Use database tools** - all operations now work with your authenticated connection

### Direct Mode (Traditional)

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

## Available Tools

### Core Database Tools
- `query`: Execute SQL queries against the database
- `list_schemas`: List all available schemas
- `list_tables`: List all tables in a specific schema
- `describe_table`: Get detailed information about a table's structure
- `get_foreign_keys`: Get foreign key relationships for a table
- `find_relationships`: Discover both explicit and implied relationships for a table
- `db_identity`: Show current db/user/host/port, search_path, and version

### Authentication Tools (OAuth Mode)
- `auth_info`: Get authentication status and login instructions
- `server_info`: Server configuration and capabilities

### Typed Tools (Preferred)
- `run_query(input)`: Execute with typed input (`sql`, `parameters`, `row_limit`, `format: 'markdown'|'json'`)
- `run_query_json(input)`: Execute and return JSON-serializable rows
- `list_schemas_json(input)`: List schemas with filters (`include_system`, `include_temp`, `require_usage`, `row_limit`)
- `list_schemas_json_page(input)`: Paginated listing with filters and `name_like` pattern
- `list_tables_json(input)`: List tables within a schema with filters (name pattern, case sensitivity, table_types, row_limit)
- `list_tables_json_page(input)`: Paginated tables listing with filters

### Example Tool Usage

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

// List schemas with filters
{
  "include_system": false,
  "include_temp": false,
  "require_usage": true,
  "row_limit": 10000
}

// Paginated list with pattern filter
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

### Resources & Prompts

Resources (if supported by client):
- `table://{schema}/{table}` for reading table rows. Fallback tools are available:
  - `list_table_resources(schema)` → `table://...` URIs
  - `read_table_resource(schema, table, row_limit)` → rows JSON

Prompts (registered when supported; also exposed as tools):
- `write_safe_select` / `prompt_write_safe_select_tool`
- `explain_plan_tips` / `prompt_explain_plan_tips_tool`

## Configuration

### Claude Desktop Configuration

#### Traditional Mode
```json
{
  "mcpServers": {
    "postgres": {
      "command": "/path/to/.venv/bin/python",
      "args": ["/path/to/postgres_server.py"],
      "env": {
        "POSTGRES_CONNECTION_STRING": "postgresql://username:password@host:5432/database?ssl=true"
      }
    }
  }
}
```

#### OAuth Mode (Local Development)
```json
{
  "mcpServers": {
    "postgres-oauth": {
      "command": "/path/to/.venv/bin/python",
      "args": [
        "/path/to/postgres_server.py",
        "--oauth-only",
        "--transport", "streamable-http",
        "--port", "8000"
      ],
      "env": {
        "GOOGLE_CLIENT_ID": "your_client_id.apps.googleusercontent.com",
        "GOOGLE_CLIENT_SECRET": "your_client_secret",
        "SECRET_KEY": "your_32_character_secret_key"
      }
    }
  }
}
```

#### Railway Cloud Deployment
```json
{
  "mcpServers": {
    "postgres-railway": {
      "transport": {
        "type": "http",
        "url": "https://your-app-name.railway.app"
      }
    }
  }
}
```

### Environment Variables

#### Core Configuration
- `POSTGRES_CONNECTION_STRING`: Direct database connection (traditional mode)
- `MCP_TRANSPORT`: `stdio|sse|streamable-http` (default: `stdio`)
- `MCP_HOST`: Host for HTTP transports (default: `127.0.0.1`)
- `MCP_PORT`: Port for HTTP transports (default: `8000`)

#### OAuth Configuration
- `GOOGLE_CLIENT_ID`: Google OAuth client ID (required for OAuth mode)
- `GOOGLE_CLIENT_SECRET`: Google OAuth client secret (required for OAuth mode)  
- `SECRET_KEY`: Session encryption key (32+ characters, required for OAuth mode)
- `REDIRECT_URI`: OAuth redirect URI (auto-configured for Railway)

#### Security & Performance
- `POSTGRES_READONLY`: `true` to allow only SELECT/CTE/EXPLAIN/SHOW/VALUES queries
- `POSTGRES_STATEMENT_TIMEOUT_MS`: Query timeout in milliseconds (e.g., `30000`)

#### Railway Deployment (Auto-configured)
- `DATABASE_URL`: Managed PostgreSQL connection string
- `PORT`: Server port (Railway-provided)
- `RAILWAY_PUBLIC_DOMAIN`: Public domain for OAuth redirects
- `RAILWAY_ENVIRONMENT`: Deployment environment

### Running with Docker

Build the image:
```bash
docker build -t mcp-postgres .
```

Traditional mode:
```bash
docker run \
  -e POSTGRES_CONNECTION_STRING="postgresql://username:password@host:5432/database" \
  -p 8000:8000 \
  mcp-postgres
```

OAuth mode:
```bash
docker run \
  -e GOOGLE_CLIENT_ID="your_client_id" \
  -e GOOGLE_CLIENT_SECRET="your_client_secret" \
  -e SECRET_KEY="your_32_char_secret" \
  -p 8000:8000 \
  mcp-postgres

Unified launcher (optional, same image):
```bash
# MCP
docker run -e SERVICE_ROLE=mcp -p 8000:8000 mcp-postgres python start.py

# OAuth companion
docker run -e SERVICE_ROLE=oauth -e GOOGLE_CLIENT_ID=... -e GOOGLE_CLIENT_SECRET=... -e SECRET_KEY=... -p 8000:8000 mcp-postgres python start.py
```

## HTTP Client Integration

Run the server with Streamable HTTP:
```bash
python postgres_server.py --transport streamable-http --host 0.0.0.0 --port 8000
```

### Health Check (OAuth service)
```bash
curl http://localhost:8000/health
# Expected response:
{
  "status": "healthy",
  "service": "PostgreSQL MCP OAuth Companion",
  "oauth_enabled": true,
  "environment": "development"
}
```

### OAuth Endpoints (OAuth Mode)
- `GET /auth/login` - Get Google OAuth authorization URL
- `GET /auth/callback` - OAuth callback endpoint  
- `GET /auth/status` - Check authentication status
- `POST /connection/set` - Set user's database connection string

### Python MCP Client Example
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
        print("result:", result.content[0].text if result.content else result.structuredContent)

if __name__ == "__main__":
    asyncio.run(main())
```

## Security Best Practices

### Authentication & Authorization
- **OAuth Secrets**: Keep Google OAuth credentials secure, never commit to git
- **Session Keys**: Use strong SECRET_KEY (32+ characters minimum)
- **Token Rotation**: Regularly rotate OAuth credentials
- **User Isolation**: Each authenticated user has separate database connections

### Database Security  
- **Connection Strings**: Use minimal privilege database connections
- **Read-only Mode**: Enable `POSTGRES_READONLY=true` when appropriate
- **Query Timeouts**: Set `POSTGRES_STATEMENT_TIMEOUT_MS` to prevent runaway queries
- **SSL Connections**: Always use SSL for production database connections

### Production Deployment
- **Environment Variables**: Never expose secrets in code or logs
- **HTTPS**: Use HTTPS for all OAuth flows (Railway provides this automatically)
- **Access Controls**: Implement proper database user permissions
- **Connection Pooling**: Use connection pooling for better resource management

## Deployment Options

### 1. Local Development
- Direct database connections
- OAuth testing with localhost
- Development environment variables

### 2. Railway Cloud (Recommended)
- Managed PostgreSQL database
- Automatic HTTPS and domain management
- Environment variable management
- Automatic deployments from GitHub
- Built-in monitoring and logging
- **Cost**: $5-20/month for most use cases

### 3. Custom Cloud Deployment
- Any cloud provider supporting Python applications
- Container-based deployment with Docker
- Manual OAuth configuration
- Custom domain and SSL setup

## Migration Guide

### From Traditional to OAuth Mode

1. **Backup Current Setup**: Save existing configuration files
2. **Set Up OAuth**: Follow [OAUTH_SETUP.md](./OAUTH_SETUP.md) guide
3. **Update Server**: Replace with OAuth-enabled version
4. **Test Locally**: Verify OAuth flow works
5. **Deploy**: Use Railway or custom deployment
6. **Update Clients**: Configure Claude Desktop with new server URL

### Backwards Compatibility
- Traditional mode still works with `--conn` parameter
- Existing MCP clients remain compatible
- All original tools and functionality preserved

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

### Development Setup
1. Create a `.venv` and install runtime deps: `pip install -r requirements.txt`
2. (Optional) Install test deps: `pip install -r dev-requirements.txt` 
3. Set up OAuth credentials for testing (see [OAUTH_SETUP.md](./OAUTH_SETUP.md))
4. Run tests: `pytest -q`

### Development & Testing
- **Local Testing**: Test both traditional and OAuth modes
- **Integration Tests**: Test with actual PostgreSQL databases
- **OAuth Testing**: Test complete authentication flow
- **Railway Testing**: Test cloud deployment

## Troubleshooting

### Common Issues

**OAuth not configured**:
- Verify `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set
- Check Google Cloud Console OAuth setup

**Authentication required**:  
- Complete OAuth flow via `/auth/login` endpoint
- Verify session token is included in requests

**Database connection errors**:
- Verify connection string format
- Test database connectivity independently
- Check firewall and network access

**Railway deployment issues**:
- Check environment variables are set correctly
- Verify OAuth redirect URIs match Railway domain
- Monitor deployment logs in Railway dashboard

For detailed troubleshooting, see [OAUTH_SETUP.md](./OAUTH_SETUP.md) and [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md).

## Related Projects

- [MCP Specification](https://github.com/modelcontextprotocol/specification)
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk)
- [MCP Servers](https://github.com/modelcontextprotocol/servers)
- [Railway](https://railway.app) - Cloud deployment platform
- [Google OAuth 2.0](https://developers.google.com/identity/protocols/oauth2) - Authentication provider

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
