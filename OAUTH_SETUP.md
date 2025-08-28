# PostgreSQL MCP Server with OAuth - Setup Guide

## Overview

This PostgreSQL MCP server now includes OAuth authentication support and is optimized for Railway deployment. Users can authenticate with Google OAuth and securely connect to their own PostgreSQL databases.

## Features

- **OAuth Authentication**: Secure Google OAuth 2.0 integration
- **Multi-tenant**: Each user has their own database connection
- **Railway Ready**: Optimized for Railway cloud deployment
- **Session Management**: Secure token-based sessions
- **Health Monitoring**: Built-in health checks and monitoring
- **Production Safe**: Read-only mode, query timeouts, and security controls

## Prerequisites

1. **Python 3.8+** with pip
2. **Google Cloud Account** for OAuth setup
3. **Railway Account** for deployment (optional)
4. **PostgreSQL Database** (can be provided by Railway)

## Google OAuth Setup

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing one
3. Enable the required APIs:
   - Google+ API (for user profiles)
   - OAuth 2.0 API

### Step 2: Configure OAuth Consent Screen

1. Navigate to **APIs & Services** → **OAuth consent screen**
2. Choose **External** user type (unless you have Google Workspace)
3. Fill in the required information:
   - **App name**: "PostgreSQL MCP Server"
   - **User support email**: Your email
   - **Developer contact information**: Your email
4. Add your email as a test user during development

### Step 3: Create OAuth 2.0 Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **Create Credentials** → **OAuth 2.0 Client IDs**
3. Configure the client:
   - **Application type**: Web application
   - **Name**: "MCP Postgres Server"
   - **Authorized JavaScript origins**: 
     - `http://localhost:8000` (for local development)
     - `https://your-app-name.railway.app` (add after Railway deployment)
   - **Authorized redirect URIs**:
     - `http://localhost:8000/auth/callback` (for local development)
     - `https://your-app-name.railway.app/auth/callback` (add after Railway deployment)
4. Save and copy the **Client ID** and **Client Secret**

## Local Development Setup

### Step 1: Install Dependencies

```bash
# Clone or navigate to your repository
cd mcp-postgres

# Install Python dependencies
pip install -r requirements.txt
```

### Step 2: Configure Environment

```bash
# Copy the environment template
cp .env.example .env

# Edit .env with your values
nano .env
```

**Required environment variables**:
```bash
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
SECRET_KEY=your_32_character_secret_key_generate_with_openssl_rand_hex_32
```

**Generate a secure secret key**:
```bash
# Generate a secure secret key
openssl rand -hex 32
```

### Step 3: Test Local Server

```bash
# Start the server locally
python postgres_server.py --transport streamable-http --host 127.0.0.1 --port 8000

# Check health endpoint
curl http://localhost:8000/health

# Expected response:
{
  "status": "healthy",
  "service": "PostgreSQL MCP Server with OAuth",
  "oauth_enabled": true,
  "environment": "development"
}
```

### Step 4: Test OAuth Flow

```bash
# Get login URL
curl http://localhost:8000/auth/login

# Response will include authorization_url - visit it in your browser
# Complete Google OAuth flow
# Use the callback URL to get your session token
```

## Security Considerations

### Production Secrets Management

- **Never commit secrets** to git
- Use Railway's environment variables for production
- Rotate secrets regularly
- Use strong SECRET_KEY (32+ characters)

### Database Security

- Enable **POSTGRES_READONLY=true** for read-only access when appropriate
- Set **POSTGRES_STATEMENT_TIMEOUT_MS** to prevent runaway queries
- Use connection strings with limited privileges
- Consider database-level user permissions

### OAuth Security

- Keep **GOOGLE_CLIENT_SECRET** secure and private
- Use HTTPS in production (Railway provides this automatically)
- Regularly review OAuth consent screen and authorized domains
- Monitor OAuth usage in Google Cloud Console

## Development vs Production

### Development Mode
```bash
# Local development with optional OAuth
python postgres_server.py --conn "postgresql://user:pass@localhost:5432/db"

# OAuth-only mode for testing
python postgres_server.py --oauth-only --transport streamable-http
```

### Production Mode (Railway)
```bash
# Automatic OAuth-only mode when RAILWAY_ENVIRONMENT=production
# All configuration via environment variables
# Managed PostgreSQL via Railway
```

## Claude Desktop Integration

### Development Configuration

```json
{
  "mcpServers": {
    "postgres-dev": {
      "command": "python",
      "args": [
        "/path/to/mcp-postgres/postgres_server.py",
        "--conn", "postgresql://user:pass@localhost:5432/mydb"
      ]
    }
  }
}
```

### Production Configuration (Railway)

```json
{
  "mcpServers": {
    "postgres-oauth": {
      "transport": {
        "type": "http",
        "url": "https://your-app-name.railway.app"
      }
    }
  }
}
```

## Troubleshooting

### Common Issues

**"OAuth not configured" error:**
- Verify `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` are set correctly
- Check Google Cloud Console for proper OAuth setup

**"Authentication required" error:**
- Complete OAuth flow first via `/auth/login`
- Ensure session token is valid and included in requests

**Database connection errors:**
- Verify connection string format: `postgresql://user:pass@host:port/db`
- Test connection independently: `psql "postgresql://user:pass@host:port/db"`
- Check firewall and network connectivity

**OAuth redirect errors:**
- Ensure redirect URI matches exactly in Google Console
- Use HTTPS in production
- Check for typos in domain names

### Debug Mode

```bash
# Enable debug logging
export PYTHONPATH=/path/to/mcp-postgres
python -m pdb postgres_server.py --oauth-only

# Check logs
tail -f postgres_server.log
```

## Next Steps

1. **Complete local testing** with OAuth flow
2. **Deploy to Railway** using the deployment guide
3. **Update Google OAuth** redirect URIs with Railway domain
4. **Configure Claude Desktop** with your deployed server
5. **Test end-to-end** functionality

See [RAILWAY_DEPLOYMENT.md](./RAILWAY_DEPLOYMENT.md) for detailed deployment instructions.

## Support

- **Documentation**: Check README.md for basic usage
- **Issues**: Create GitHub issues for bugs or feature requests
- **Discussions**: Use GitHub Discussions for questions

## License

This project maintains the same license as the original MCP PostgreSQL server.