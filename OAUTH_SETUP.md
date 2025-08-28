# PostgreSQL MCP Server with OAuth - Setup Guide

## Overview

This PostgreSQL MCP server now includes OAuth authentication support with a **clean, modular architecture**:

- **MCP Server** (`postgres_server.py`) - Handles database operations via MCP protocol
- **OAuth Companion Service** (`oauth_companion.py`) - Handles Google OAuth authentication

This separation allows you to deploy them together or separately, giving you flexibility in architecture and deployment.

## Architecture Options

### Option 1: MCP Server Only (Traditional)
- Direct database connections
- No authentication required
- Simple deployment
- Good for single-user or trusted environments

### Option 2: MCP Server + OAuth Companion (Recommended)
- Secure multi-user authentication
- Each user has their own database connection  
- Scalable and production-ready
- OAuth-protected database access

### Option 3: Railway Deployment
- Cloud-hosted with managed PostgreSQL
- Automatic HTTPS and domain management
- Production-ready scaling
- Environment variable management

## Quick Start

### Prerequisites

1. **Python 3.8+** with pip
2. **Google Cloud Account** for OAuth setup
3. **PostgreSQL Database** (local or cloud)

### 1. Installation

```bash
# Clone or navigate to repository
cd mcp-postgres

# Install dependencies
pip install -r requirements.txt
```

### 2. Google OAuth Setup (Required for OAuth features)

#### Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable required APIs:
   - Google+ API (for user profiles)
   - OAuth 2.0 API

#### Configure OAuth Consent Screen

1. Navigate to **APIs & Services** → **OAuth consent screen**
2. Choose **External** user type
3. Fill in required information:
   - **App name**: "PostgreSQL MCP Server"
   - **User support email**: Your email
   - **Developer contact**: Your email
4. Add test users during development

#### Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth 2.0 Client IDs**
3. Configure:
   - **Application type**: Web application
   - **Name**: "MCP Postgres Server OAuth"
   - **Authorized redirect URIs**:
     - `http://localhost:8001/auth/callback` (local development)
     - `https://your-domain.railway.app/auth/callback` (production)
4. Save **Client ID** and **Client Secret**

### 3. Environment Configuration

```bash
# Copy environment template
cp .env.example .env

# Edit .env file
nano .env
```

**Required environment variables:**
```bash
# OAuth Configuration (required for OAuth features)
GOOGLE_CLIENT_ID="your_client_id.apps.googleusercontent.com"
GOOGLE_CLIENT_SECRET="your_client_secret"
SECRET_KEY="your_32_character_secret_key"

# Optional: Database connection (for MCP server)
POSTGRES_CONNECTION_STRING="postgresql://user:pass@host:port/db"

# Optional: Server configuration
MCP_TRANSPORT="streamable-http"
MCP_PORT=8000
OAUTH_PORT=8001
```

**Generate secure secret key:**
```bash
# Use OpenSSL to generate a secure secret
openssl rand -hex 32
```

### 4. Local Testing

#### Option A: MCP Server Only (Traditional Mode)

```bash
# Start MCP server with direct database connection
python postgres_server.py --conn "postgresql://user:pass@localhost:5432/db" \
                          --transport streamable-http --port 8000

# Test health
curl http://localhost:8000/  # Expect MCP protocol response
```

#### Option B: MCP Server + OAuth Companion

```bash
# Terminal 1: Start MCP Server
python postgres_server.py --transport streamable-http --port 8000

# Terminal 2: Start OAuth Companion Service  
python oauth_companion.py --port 8001

# Terminal 3: Test both services
python test_oauth_client.py
```

## OAuth Flow Testing

### Manual Testing

1. **Get OAuth Login URL:**
   ```bash
   curl http://localhost:8001/auth/login
   # Returns: {"authorization_url": "https://accounts.google.com/...", ...}
   ```

2. **Complete Authentication:**
   - Visit the authorization URL in browser
   - Complete Google OAuth flow
   - Copy callback URL from browser

3. **Exchange Code for Token:**
   ```bash
   # Extract code from callback URL and exchange it
   curl "http://localhost:8001/auth/callback?code=YOUR_CODE"
   # Returns: {"session_token": "...", "user": {...}}
   ```

4. **Configure Database Connection:**
   ```bash
   curl -X POST http://localhost:8001/connection/set \
     -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"connection_string": "postgresql://user:pass@host:port/db"}'
   ```

### Automated Testing

```bash
# Test both services
python test_oauth_client.py

# Test MCP server only  
python test_oauth_client.py --mcp-only

# Test OAuth companion only
python test_oauth_client.py --oauth-only
```

## Claude Desktop Integration

### MCP Server Only (Traditional)

```json
{
  "mcpServers": {
    "postgres": {
      "command": "python",
      "args": ["/path/to/postgres_server.py"],
      "env": {
        "POSTGRES_CONNECTION_STRING": "postgresql://user:pass@localhost:5432/db"
      }
    }
  }
}
```

### MCP Server with OAuth (Local Development)

```json
{
  "mcpServers": {
    "postgres-oauth": {
      "command": "python",
      "args": [
        "/path/to/postgres_server.py",
        "--transport", "streamable-http",
        "--port", "8000"
      ],
      "env": {
        "GOOGLE_CLIENT_ID": "your_client_id",
        "GOOGLE_CLIENT_SECRET": "your_client_secret",
        "SECRET_KEY": "your_secret_key"
      }
    }
  }
}
```

### Railway Production Deployment

```json
{
  "mcpServers": {
    "postgres-railway": {
      "transport": {
        "type": "http",
        "url": "https://your-app.railway.app"
      }
    }
  }
}
```

## Usage Examples

### Using MCP Tools

Once connected, you can use Claude to interact with your database:

```
User: "Show me information about the database server"
Claude: [Calls auth_info tool, shows OAuth configuration]

User: "List all tables in the database"
Claude: [Calls list_tables tool, returns table list]

User: "Describe the users table structure"  
Claude: [Calls describe_table tool, shows column details]

User: "Run a query to count rows in the products table"
Claude: [Calls query tool, executes SELECT COUNT(*) FROM products]
```

### OAuth Authentication Flow

```
User: "Connect to the database"
Claude: [Calls auth_info tool]
Claude: "I can see the database server supports OAuth authentication. 
        Visit http://localhost:8001/auth/login to authenticate with Google."

User: [Completes OAuth flow, gets session token]
User: "I have the session token: abc123..."

Claude: "Great! Now you can configure your database connection using the 
        /connection/set endpoint with your session token."
```

## Development vs Production

### Development Setup
- Both services run locally (ports 8000 and 8001)
- HTTP OAuth redirect URIs  
- Local database connections
- Environment variables in `.env` file

### Production Setup (Railway)
- Services deployed to cloud
- HTTPS OAuth redirect URIs
- Managed PostgreSQL database
- Environment variables in Railway dashboard

## Deployment Options

### Local Development
```bash
# Start both services locally
python postgres_server.py --transport streamable-http --port 8000 &
python oauth_companion.py --port 8001 &
```

### Railway Cloud (Recommended)
- Deploy MCP server to Railway
- Optionally deploy OAuth companion as separate service
- Use Railway's managed PostgreSQL
- See [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md) for details

### Docker Deployment
```bash
# Build and run MCP server
docker build -t mcp-postgres .
docker run -p 8000:8000 mcp-postgres

# Run OAuth companion
docker run -p 8001:8001 -e GOOGLE_CLIENT_ID=... mcp-postgres \
  python oauth_companion.py --port 8001
```

## Security Considerations

### OAuth Security
- **Client Secrets**: Keep Google OAuth credentials secure
- **Session Tokens**: Use strong SECRET_KEY (32+ characters)
- **HTTPS**: Required for production OAuth flows
- **Token Expiration**: Sessions expire after 7 days by default

### Database Security
- **User Isolation**: Each OAuth user has separate database connection
- **Connection Strings**: Store securely, use minimal privileges
- **Read-only Mode**: Enable with `POSTGRES_READONLY=true`
- **Query Timeouts**: Set with `POSTGRES_STATEMENT_TIMEOUT_MS`

### Production Security
- **Environment Variables**: Never commit secrets to code
- **HTTPS**: Use HTTPS for all OAuth communications
- **Database SSL**: Enable SSL for database connections
- **Access Controls**: Implement proper database user permissions

## Troubleshooting

### Common Issues

**"OAuth not configured" error:**
- Verify `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set
- Check Google Cloud Console OAuth configuration

**"Connection refused" errors:**
- Verify services are running on correct ports
- Check firewall settings
- Confirm OAuth companion is accessible

**Database connection errors:**
- Test connection string independently: `psql "postgresql://..."`
- Verify database is running and accessible
- Check network connectivity and firewalls

**OAuth redirect errors:**
- Ensure redirect URIs match exactly in Google Console
- Use correct domain (localhost for dev, your domain for prod)
- Verify HTTPS in production

### Debug Mode

```bash
# Enable debug logging
export PYTHONPATH=/path/to/mcp-postgres
python -m pdb postgres_server.py

# Test individual components
python test_oauth_client.py --mcp-only
python test_oauth_client.py --oauth-only
```

## Next Steps

1. **✅ Complete local setup and testing**
2. **🚀 Deploy to Railway** (see [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md))
3. **🔧 Configure Claude Desktop** with your deployed server
4. **🧪 Test end-to-end functionality**
5. **📊 Monitor usage and performance**

## Support

- **Documentation**: README.md for basic usage
- **Issues**: GitHub issues for bugs or feature requests  
- **Discussions**: GitHub Discussions for questions
- **Railway Support**: Railway Discord community

Your PostgreSQL MCP server is now ready with OAuth authentication! 🎉
