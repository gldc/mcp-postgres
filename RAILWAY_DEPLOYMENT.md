# Railway Deployment Guide

Complete guide for deploying your PostgreSQL MCP Server with OAuth to Railway using the **clean two-service architecture**.

## Architecture Overview

Your deployment can use one of these approaches:

### Option 1: MCP Server Only (Simplified)
- Single service deployment  
- MCP server with Railway's managed PostgreSQL
- OAuth info provided via MCP tools (no actual OAuth endpoints)
- Good for testing and simple deployments

### Option 2: MCP Server + OAuth Companion (Full Featured)  
- Two separate Railway services
- MCP server for database operations
- OAuth companion for authentication
- Full OAuth flow with secure multi-user support

## Prerequisites

Before deploying, ensure you have:
- ✅ Completed [OAUTH_SETUP.md](./OAUTH_SETUP.md) 
- ✅ Google OAuth credentials configured
- ✅ Local testing successful
- ✅ Railway account created
- ✅ Code pushed to GitHub

## Option 1: MCP Server Only Deployment

### Step 1: Deploy MCP Server to Railway

1. **Create Railway Project**:
   - Visit [railway.app](https://railway.app)
   - Click "New Project" → "Deploy from GitHub repo"
   - Select your `mcp-postgres` repository

2. **Add PostgreSQL Database**:
   - In Railway project, click "New" → "Database" → "PostgreSQL"
   - Railway automatically creates `DATABASE_URL` environment variable

3. **Configure Environment Variables**:
   ```bash
   # Optional: OAuth configuration (for auth_info tool)
   GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
   GOOGLE_CLIENT_SECRET=your_client_secret
   SECRET_KEY=your_32_character_secret_key
   
   # Optional: Safety controls
   POSTGRES_READONLY=false
   POSTGRES_STATEMENT_TIMEOUT_MS=30000
   ```

4. **Deploy**:
   - Railway uses `railway.toml` configuration
   - Deploys with unified launcher: `python start.py`
   - Default `SERVICE_ROLE` is `mcp` → runs `postgres_server.py` with streamable HTTP
   - Note: MCP service does not expose HTTP `/health` by default; healthchecks are disabled for it in `railway.toml`

### Step 2: Configure Claude Desktop

```json
{
  "mcpServers": {
    "postgres-railway": {
      "transport": {
        "type": "http",
        "url": "https://your-mcp-app.railway.app"
      }
    }
  }
}
```

## Option 2: Full OAuth Deployment (Two Services)

### Step 1: Deploy MCP Server

Follow Option 1 steps above to deploy the MCP server.

### Step 2: Deploy OAuth Companion Service

1. **Create Second Railway Service**:
   - In the same Railway project, click "New" → "GitHub repo"
   - Select the same repository
   - This creates a second service

2. **Configure OAuth Service** (no custom start command needed):
   - Go to the second service settings
   - Set environment variable `SERVICE_ROLE=oauth` (the unified launcher will run `oauth_companion.py`)
   - Optionally set the service Environment to `oauth` to apply the `/health` healthcheck from `railway.toml`
   - Set required environment variables:
     ```bash
     GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
     GOOGLE_CLIENT_SECRET=your_client_secret
     SECRET_KEY=your_32_character_secret_key
     ```

3. **Update OAuth Redirect URIs**:
   - In Google Cloud Console, add redirect URI:
   - `https://your-oauth-app.railway.app/auth/callback`

### Step 3: Configure Cross-Service Communication

1. **Get Service URLs**:
   - MCP Service: `https://your-mcp-app.railway.app`
   - OAuth Service: `https://your-oauth-app.railway.app`

2. **Test Services**:
   ```bash
   # Test MCP server (no HTTP /health by default; 404/405 on / is normal)
   curl -i https://your-mcp-app.railway.app/

   # Test OAuth service health  
   curl https://your-oauth-app.railway.app/health
   # Expect: {"status": "healthy", ...}
   ```

## Detailed Railway Configuration

### File Structure for Deployment

Your repository should have:
```
mcp-postgres/
├── postgres_server.py          # MCP server
├── oauth_companion.py          # OAuth service  
├── requirements.txt           # Dependencies
├── railway.toml              # Railway config
├── .env.example             # Environment template
└── [documentation files]
```

### railway.toml Configuration

```toml
# Default: Deploy MCP server
[build]
  builder = "NIXPACKS"

[deploy]
  startCommand = "python start.py"
  # No HTTP healthcheck for MCP server; it doesn't expose /health over HTTP
  restartPolicyType = "ON_FAILURE"

# Optional: OAuth service configuration
[environments.oauth]
  [environments.oauth.variables]
    # Optionally place OAuth secrets here or set in the UI
    # GOOGLE_CLIENT_ID = "your_client_id.apps.googleusercontent.com"
    # GOOGLE_CLIENT_SECRET = "your_client_secret"
    # SECRET_KEY = "your_32_char_secret"
    # SERVICE_ROLE = "oauth"  # unified launcher selects oauth_companion

  [environments.oauth.deploy]
    startCommand = "python start.py"
    healthcheckPath = "/health"
    healthcheckTimeout = 30
    restartPolicyType = "ON_FAILURE"
```

### Environment Variables

#### MCP Server Variables
```bash
# Auto-provided by Railway
DATABASE_URL=postgresql://postgres:password@hostname:port/database
PORT=8000
RAILWAY_PUBLIC_DOMAIN=your-mcp-app.railway.app
RAILWAY_ENVIRONMENT=production

# Optional: OAuth info (for auth_info tool)
GOOGLE_CLIENT_ID=your_client_id
GOOGLE_CLIENT_SECRET=your_client_secret
SECRET_KEY=your_secret_key

# Optional: Safety controls
POSTGRES_READONLY=false
POSTGRES_STATEMENT_TIMEOUT_MS=30000
```

#### OAuth Service Variables
```bash
# Auto-provided by Railway
PORT=8000
RAILWAY_PUBLIC_DOMAIN=your-oauth-app.railway.app  
RAILWAY_ENVIRONMENT=production

# Required for OAuth functionality
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret
SECRET_KEY=your_secret_key

# Unified launcher role selector
SERVICE_ROLE=oauth

# Auto-configured
REDIRECT_URI=https://your-oauth-app.railway.app/auth/callback
```

## Testing Deployed Services

### Test MCP Server

```bash
# MCP protocol test (expect 404/405 on / - this is normal)
curl -i https://your-mcp-app.railway.app/
```

### Test OAuth Service (if deployed)

```bash
# Health check
curl https://your-oauth-app.railway.app/health
# Expected: {"status": "healthy", "oauth_enabled": true}

# Get OAuth login URL
curl https://your-oauth-app.railway.app/auth/login
# Expected: {"authorization_url": "https://accounts.google.com/..."}
```

### End-to-End OAuth Test

1. **Get Login URL**:
   ```bash
   curl https://your-oauth-app.railway.app/auth/login
   ```

2. **Complete Authentication**:
   - Visit the authorization URL
   - Complete Google OAuth flow
   - Copy callback URL

3. **Set Database Connection**:
   - Browser (recommended): visit `https://your-oauth-app.railway.app/connection`
   - API:
     ```bash
     curl -X POST https://your-oauth-app.railway.app/connection/set \
       -H "Authorization: Bearer YOUR_TOKEN" \
       -H "Content-Type: application/json" \
       -d '{"connection_string": "postgresql://user:pass@host:port/db"}'
     ```

## Claude Desktop Configuration

### MCP Server Only

```json
{
  "mcpServers": {
    "postgres-railway": {
      "transport": {
        "type": "http",
        "url": "https://your-mcp-app.railway.app"
      },
      "description": "PostgreSQL on Railway with OAuth info"
    }
  }
}
```

### Full OAuth Setup (Two Services)

```json
{
  "mcpServers": {
    "postgres-railway": {
      "transport": {
        "type": "http", 
        "url": "https://your-mcp-app.railway.app"
      },
      "description": "PostgreSQL MCP Server"
    }
  }
}
```

**Note**: Claude Desktop connects to the MCP server. OAuth authentication happens through the separate OAuth service URLs.

## Railway Management

### Monitoring

**Railway Dashboard Features**:
- **Metrics**: CPU, memory, network usage for both services
- **Logs**: Real-time application logs
- **Database**: PostgreSQL performance metrics
- **Deployments**: History and rollback options

### Scaling

**Automatic Scaling**:
- Railway scales both services based on demand
- MCP server scales with database query load
- OAuth service scales with authentication requests
- No manual configuration required

### Cost Management

**Pricing Structure**:
- **Starter Plan**: $5/month per service
  - MCP Server: $5/month
  - OAuth Service: $5/month (optional)
  - PostgreSQL: Included
- **Pro Plan**: $20/month per service (production workloads)

**Cost Optimization**:
- Start with MCP server only ($5/month)
- Add OAuth service when needed (+$5/month)
- Monitor usage in Railway dashboard
- Services auto-sleep when not in use

## Production Considerations

### Security Best Practices

1. **Environment Variables**: Store all secrets in Railway dashboard
2. **OAuth Configuration**: 
   - Use HTTPS redirect URIs only
   - Regularly rotate OAuth secrets
3. **Database Security**:
   - Use Railway's managed PostgreSQL (includes SSL)
   - Set up proper user permissions
4. **API Security**:
   - Enable `POSTGRES_READONLY` for read-only access
   - Set `POSTGRES_STATEMENT_TIMEOUT_MS` for query limits

### Performance Optimization

1. **Connection Pooling**: Railway PostgreSQL includes connection pooling
2. **Caching**: Railway provides automatic CDN caching
3. **Monitoring**: Set up monitoring alerts in Railway dashboard
4. **Resource Limits**: Railway handles resource allocation automatically

### Backup and Recovery

1. **Database Backups**: 
   - Automatic daily backups by Railway
   - Point-in-time recovery available
   - Manual backup triggers available

2. **Code Backups**:
   - Git repository provides version control
   - Railway keeps deployment history
   - Rollback capability through Railway CLI

## Troubleshooting

### Common Deployment Issues

**Build Failures**:
```bash
# Check build logs in Railway dashboard
# Common fixes:
# 1. Verify requirements.txt includes all dependencies
# 2. Check Python version compatibility  
# 3. Ensure start commands are correct
```

**Service Communication Issues**:
```bash
# Verify OAuth service health
curl https://your-oauth-app.railway.app/health

# Check environment variables are set correctly
# Verify Google OAuth redirect URIs match Railway domains
```

**Database Connection Issues**:
```bash
# Railway automatically sets DATABASE_URL
# Check in Railway dashboard under Variables
# Test connection using Railway CLI:
railway connect postgres
```

**OAuth Flow Issues**:
```bash
# Verify redirect URI matches exactly:
# Google Console: https://your-oauth-app.railway.app/auth/callback
# Railway domain: https://your-oauth-app.railway.app

# Check OAuth service logs in Railway dashboard
# Common issue: GOOGLE_CLIENT_SECRET not set or incorrect
```

### Railway CLI Commands

**Install Railway CLI**:
```bash
npm install -g @railway/cli
```

**Useful Commands**:
```bash
# Login and connect to project
railway login
railway link

# View logs for specific service
railway logs --service mcp-server
railway logs --service oauth-service

# View environment variables
railway variables

# Connect to database
railway connect postgres

# Deploy manually
railway up
```

### Debug Mode

**Local Development**:
```bash
# Test locally before deploying
python test_oauth_client.py

# Debug specific issues
python -m pdb postgres_server.py
python -m pdb oauth_companion.py
```

**Production Debugging**:
```bash
# View service logs
railway logs --follow --service mcp-server

# Check service health
curl https://your-app.railway.app/health

# Test MCP protocol connection
# Use MCP client library to test connection
```

## Maintenance and Updates

### Automatic Deployments

**GitHub Integration**:
- Push to main branch triggers automatic deployment
- Both services update simultaneously
- Zero-downtime deployments
- Rollback available if issues occur

### Manual Deployments

```bash
# Deploy specific commit
git checkout <commit-hash>
railway up

# Deploy to specific service
railway up --service mcp-server
railway up --service oauth-service
```

### Database Maintenance

**Automatic Maintenance**:
- PostgreSQL updates managed by Railway
- Automatic security patches
- Backup management
- Performance monitoring

**Manual Operations**:
```bash
# Connect to database for maintenance
railway connect postgres

# Run database migrations
railway run psql $DATABASE_URL -f migration.sql
```

## Migration from Single Service

If you started with MCP server only and want to add full OAuth:

1. **Deploy OAuth Companion**:
   - Create second service in same Railway project
   - Configure with OAuth environment variables
   - Update Google OAuth redirect URIs

2. **Update MCP Server**:
   - Add OAuth environment variables
   - No code changes needed
   - MCP server will show OAuth information in auth_info tool

3. **Test Integration**:
   - Verify both services are healthy
   - Test OAuth flow end-to-end
   - Update Claude Desktop configuration

## Next Steps

1. **✅ Complete deployment** following this guide
2. **🧪 Test all functionality** with your deployed services
3. **🔧 Configure Claude Desktop** with production URLs
4. **📊 Monitor usage** through Railway dashboard
5. **🔒 Review security settings** and access controls
6. **📈 Plan for scaling** based on usage patterns

## Support Resources

- **Railway Documentation**: [docs.railway.app](https://docs.railway.app)
- **Railway Discord**: Community support and discussions
- **Google OAuth Documentation**: [developers.google.com/identity](https://developers.google.com/identity)
- **MCP Documentation**: [modelcontextprotocol.io](https://modelcontextprotocol.io)

Your PostgreSQL MCP Server with OAuth is now production-ready on Railway! 🚀

## Cost Summary

| Configuration | Monthly Cost | Features |
|---------------|---------------|-----------|
| **MCP Only** | $5-20 | Basic database access, managed PostgreSQL |
| **MCP + OAuth** | $10-40 | Multi-user auth, secure connections, full features |
| **Enterprise** | $40+ | High availability, advanced monitoring, premium support |

Choose the configuration that best fits your needs and scale up as you grow!
