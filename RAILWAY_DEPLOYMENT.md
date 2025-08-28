# Railway Deployment Guide

Complete guide for deploying your PostgreSQL MCP Server with OAuth to Railway.

## Prerequisites

Before deploying, ensure you have:
- ✅ Completed [OAUTH_SETUP.md](./OAUTH_SETUP.md) 
- ✅ Google OAuth credentials configured
- ✅ Local testing successful
- ✅ Railway account created
- ✅ Code pushed to GitHub

## Step 1: Prepare Repository

### Verify File Structure

Your repository should contain:
```
mcp-postgres/
├── postgres_server.py          # Updated OAuth server
├── requirements.txt           # Python dependencies
├── railway.toml              # Railway configuration
├── .env.example             # Environment template
├── OAUTH_SETUP.md          # Setup guide
├── RAILWAY_DEPLOYMENT.md   # This file
└── README.md              # Project documentation
```

### Final Code Review

**Verify `railway.toml` configuration:**
```toml
[build]
  builder = "NIXPACKS"

[deploy]
  startCommand = "python postgres_server.py --transport streamable-http --host 0.0.0.0 --port $PORT --oauth-only"
  healthcheckPath = "/health"
  healthcheckTimeout = 30
  restartPolicyType = "ON_FAILURE"
```

**Check `requirements.txt` includes all dependencies:**
- fastmcp, mcp, psycopg, authlib, requests, python-jose, itsdangerous, uvicorn, fastapi, pydantic

## Step 2: Railway Account Setup

### Create Railway Account
1. Visit [railway.app](https://railway.app)
2. Sign up with GitHub (recommended for automatic deployments)
3. Verify your email address
4. Connect your GitHub account if not done during signup

### Verify GitHub Connection
1. Go to Railway dashboard
2. Check that your GitHub repositories are accessible
3. If needed, adjust GitHub app permissions in your GitHub settings

## Step 3: Create Railway Project

### Deploy from GitHub
1. **New Project**: Click "New Project" in Railway dashboard
2. **Deploy from GitHub**: Choose "Deploy from GitHub repo"
3. **Select Repository**: Find and select your `mcp-postgres` repository
4. **Confirm Deployment**: Railway will analyze your repo and suggest configuration

### Initial Deployment
- Railway automatically detects Python project
- Uses Nixpacks to build based on `requirements.txt`
- Reads configuration from `railway.toml`
- Creates initial deployment (will fail without environment variables)

## Step 4: Add PostgreSQL Database

### Add Database Service
1. **Add Service**: In your Railway project, click "New" → "Database" → "PostgreSQL"
2. **Configure Database**: Accept default settings (PostgreSQL 15)
3. **Automatic Variables**: Railway automatically creates `DATABASE_URL` environment variable

### Database Details
- **Automatic Backups**: Daily backups enabled by default
- **SSL Encryption**: Enabled automatically
- **Connection Pooling**: Managed by Railway
- **Monitoring**: Available in Railway dashboard

## Step 5: Configure Environment Variables

### Required Variables

Navigate to your service **Settings** → **Environment Variables**:

```bash
# OAuth Credentials (Required)
GOOGLE_CLIENT_ID=your_client_id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your_client_secret

# Session Security (Required)
SECRET_KEY=your_32_character_secret_key

# Optional: Safety Controls
POSTGRES_READONLY=false
POSTGRES_STATEMENT_TIMEOUT_MS=30000
```

### Auto-Provided Variables

Railway automatically sets these:
```bash
DATABASE_URL=postgresql://postgres:password@hostname:port/database
PORT=8000
RAILWAY_PUBLIC_DOMAIN=your-app-name.railway.app
RAILWAY_ENVIRONMENT=production
```

### Secure Secret Generation

Generate a secure secret key locally:
```bash
# Generate secure secret
openssl rand -hex 32

# Copy result to Railway environment variables
```

## Step 6: Deploy and Verify

### Trigger Deployment
1. **Manual Deploy**: Click "Deploy" in Railway dashboard
2. **Auto Deploy**: Push commits to connected GitHub branch
3. **Watch Logs**: Monitor deployment progress in Railway dashboard

### Check Deployment Status
```bash
# Your app will be available at:
https://your-app-name.railway.app

# Health check endpoint:
curl https://your-app-name.railway.app/health

# Expected response:
{
  "status": "healthy",
  "service": "PostgreSQL MCP Server with OAuth",
  "oauth_enabled": true,
  "database_available": true,
  "environment": "production"
}
```

## Step 7: Update Google OAuth Configuration

### Add Railway Domain to OAuth

1. **Google Cloud Console**: Go to APIs & Services → Credentials
2. **Edit OAuth Client**: Click on your OAuth 2.0 Client ID
3. **Add Authorized Origins**: 
   ```
   https://your-app-name.railway.app
   ```
4. **Add Redirect URIs**:
   ```
   https://your-app-name.railway.app/auth/callback
   ```
5. **Save Changes**: Click Save

### Test OAuth Flow

```bash
# Get login URL from your deployed server
curl https://your-app-name.railway.app/auth/login

# Response includes authorization_url - test in browser
# Complete OAuth flow with Railway domain
```

## Step 8: Configure Claude Desktop

### Update Claude Desktop Configuration

Edit your Claude Desktop configuration file:

```json
{
  "mcpServers": {
    "postgres-railway": {
      "transport": {
        "type": "http",
        "url": "https://your-app-name.railway.app"
      },
      "description": "PostgreSQL Server with OAuth on Railway"
    }
  }
}
```

### Restart Claude Desktop

1. **Quit Claude Desktop** completely
2. **Restart Claude Desktop**
3. **Verify Connection**: The server should appear in available MCP servers

## Step 9: End-to-End Testing

### Test Authentication Flow

1. **Ask Claude about database info**:
   ```
   "Can you show me information about the database server?"
   ```

2. **Claude will call the auth_info tool** and provide OAuth login URL

3. **Complete Authentication**:
   - Click the provided URL
   - Complete Google OAuth flow
   - Receive session token

4. **Set Database Connection**:
   ```bash
   curl -X POST https://your-app-name.railway.app/connection/set \
     -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"connection_string": "postgresql://user:pass@host:port/db"}'
   ```

### Test Database Operations

After authentication and connection setup:
```
"List all tables in the database"
"Show me the schema for the users table"  
"Run a query to count rows in the products table"
```

## Railway Management

### Monitor Your Application

**Railway Dashboard Features**:
- **Metrics**: CPU, memory, and network usage
- **Logs**: Real-time application logs
- **Database**: PostgreSQL metrics and queries
- **Deployments**: History and rollback options

### Scaling

**Automatic Scaling**:
- Railway automatically scales based on traffic
- No configuration needed for typical MCP usage
- Scales to zero when not in use (cost savings)

**Resource Limits**:
- **Starter Plan**: 512MB RAM, suitable for development
- **Pro Plan**: 8GB RAM, suitable for production
- **Database Storage**: Starts at 1GB, scales automatically

### Cost Management

**Pricing Overview**:
- **Starter Plan**: $5/month (512MB RAM)
- **Pro Plan**: $20/month (8GB RAM)
- **Database**: Included in plan pricing
- **Bandwidth**: Generous limits included

**Cost Optimization**:
- Use Starter plan for development/testing
- Upgrade to Pro for production workloads
- Monitor usage in Railway dashboard
- Set up billing alerts

## Troubleshooting

### Common Deployment Issues

**Build Failures**:
```bash
# Check build logs in Railway dashboard
# Common fixes:
# 1. Verify requirements.txt syntax
# 2. Check Python version compatibility
# 3. Ensure all imports are available
```

**Database Connection Errors**:
```bash
# Verify DATABASE_URL is set
# Check database service is running
# Test connection in Railway console:
railway run psql $DATABASE_URL
```

**OAuth Redirect Errors**:
```bash
# Verify redirect URI matches exactly in Google Console
# Check HTTPS is used (Railway provides automatically)
# Ensure domain is correct (no typos)
```

**Health Check Failures**:
```bash
# Check /health endpoint manually:
curl https://your-app-name.railway.app/health

# Common issues:
# 1. Database connection failed
# 2. OAuth variables not set
# 3. Application startup errors
```

### Railway CLI Commands

**Install Railway CLI**:
```bash
npm install -g @railway/cli
```

**Useful Commands**:
```bash
# Login and link project
railway login
railway link

# View logs
railway logs --follow

# Connect to database
railway connect postgres

# View environment variables
railway variables

# Deploy manually
railway up

# Open deployed app
railway open
```

### Debugging Application Issues

**View Application Logs**:
```bash
# Real-time logs
railway logs --follow

# Filter by service
railway logs --service postgres-server --follow

# Search logs
railway logs | grep ERROR
```

**Database Debugging**:
```bash
# Connect to PostgreSQL
railway connect postgres

# View database details
railway variables | grep DATABASE_URL

# Test queries
railway run psql $DATABASE_URL -c "SELECT version();"
```

## Maintenance and Updates

### Automatic Deployments

**GitHub Integration**:
- Push to main branch triggers automatic deployment
- Railway builds and deploys new version
- Zero-downtime deployments
- Rollback available if needed

**Manual Deployments**:
```bash
# Deploy current branch
railway up

# Deploy specific commit
git checkout <commit-hash>
railway up
```

### Database Maintenance

**Backups**:
- Automatic daily backups enabled
- Point-in-time recovery available
- Manual backup triggers available

**Updates**:
- PostgreSQL version updates managed by Railway
- Automatic security patches
- Minimal downtime for maintenance

### Monitoring and Alerts

**Built-in Monitoring**:
- Application metrics dashboard
- Database performance metrics
- Error rate and response time tracking

**Custom Monitoring**:
```bash
# Health check endpoint for external monitoring
https://your-app-name.railway.app/health

# Database connection status
# Authentication system status
# OAuth configuration validation
```

## Production Considerations

### Security Best Practices

1. **Environment Variables**: Never commit secrets to git
2. **OAuth Secrets**: Rotate Google OAuth credentials periodically
3. **Database Access**: Use minimal privilege connection strings
4. **HTTPS**: Enabled automatically by Railway
5. **Session Security**: Strong SECRET_KEY (32+ characters)

### Performance Optimization

1. **Connection Pooling**: Enabled by default with Railway PostgreSQL
2. **Query Timeouts**: Set POSTGRES_STATEMENT_TIMEOUT_MS appropriately
3. **Read-only Mode**: Enable POSTGRES_READONLY when appropriate
4. **Monitoring**: Use Railway metrics to identify bottlenecks

### Backup and Recovery

1. **Database Backups**: Automatic daily backups by Railway
2. **Code Backups**: Git repository with version control
3. **Configuration**: Document all environment variables
4. **Recovery Plan**: Test restoration procedures

## Next Steps

1. **✅ Complete deployment** following this guide
2. **🔧 Configure monitoring** and alerts
3. **📊 Set up analytics** for usage tracking
4. **👥 Add team members** to Railway project if needed
5. **📈 Plan for scaling** based on usage patterns

## Support Resources

- **Railway Documentation**: [docs.railway.app](https://docs.railway.app)
- **Railway Discord**: Community support and discussions
- **Google OAuth Documentation**: [developers.google.com/identity/protocols/oauth2](https://developers.google.com/identity/protocols/oauth2)
- **MCP Documentation**: [modelcontextprotocol.io](https://modelcontextprotocol.io)

Your PostgreSQL MCP Server with OAuth is now production-ready on Railway! 🚀