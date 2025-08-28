#!/usr/bin/env python3
"""
OAuth Companion Service for PostgreSQL MCP Server

This service handles OAuth authentication and can run alongside the MCP server.
It provides the OAuth endpoints that the MCP server references.

Usage:
    python oauth_companion.py --port 8001

The MCP server can then run on port 8000 while this OAuth service runs on 8001.
"""

import os
import sys
import argparse
import logging
import sqlite3
import json
from datetime import datetime
from typing import Optional, Dict, Any
import secrets
import urllib.parse

import uvicorn
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, HTMLResponse
import requests
from itsdangerous import URLSafeTimedSerializer
import psycopg

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('oauth-companion')

# Railway-specific environment handling
def get_railway_config():
    """Get Railway-specific configuration"""
    config = {
        'port': int(os.getenv('OAUTH_PORT', 8001)),
        'host': '0.0.0.0' if os.getenv('RAILWAY_ENVIRONMENT') else '127.0.0.1',
        'public_domain': os.getenv('RAILWAY_PUBLIC_DOMAIN'),
        'environment': os.getenv('RAILWAY_ENVIRONMENT', 'development')
    }
    
    # Set redirect URI based on Railway domain
    if config['public_domain']:
        config['redirect_uri'] = f"https://{config['public_domain']}/auth/callback"
    else:
        config['redirect_uri'] = os.getenv('REDIRECT_URI', 'http://localhost:8001/auth/callback')
    
    return config

railway_config = get_railway_config()

# OAuth Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SECRET_KEY = os.getenv("SECRET_KEY")

# Generate SECRET_KEY if not provided
if not SECRET_KEY:
    SECRET_KEY = secrets.token_hex(32)
    logger.warning("SECRET_KEY not provided, generated temporary key. Set SECRET_KEY environment variable for production.")

REDIRECT_URI = railway_config['redirect_uri']

# Google OAuth2 endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# Log configuration for debugging
logger.info(f"OAuth Configuration:")
logger.info(f"  GOOGLE_CLIENT_ID: {'✓ Set' if GOOGLE_CLIENT_ID else '✗ Not set'}")
logger.info(f"  GOOGLE_CLIENT_SECRET: {'✓ Set' if GOOGLE_CLIENT_SECRET else '✗ Not set'}")
logger.info(f"  SECRET_KEY: {'✓ Set' if SECRET_KEY else '✗ Not set'}")
logger.info(f"  REDIRECT_URI: {REDIRECT_URI}")
logger.info(f"  Environment: {railway_config['environment']}")

# Session storage
class SessionManager:
    def __init__(self):
        self.db_path = "oauth_sessions.db"
        self.init_db()
    
    def init_db(self):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_sessions (
                    user_id TEXT PRIMARY KEY,
                    email TEXT NOT NULL,
                    connection_string TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_accessed TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    token_version INTEGER DEFAULT 0
                )
            """)
            # In case the DB existed before without token_version, try to add it
            try:
                cursor.execute("ALTER TABLE user_sessions ADD COLUMN token_version INTEGER DEFAULT 0")
            except Exception:
                pass
            conn.commit()
            conn.close()
            logger.info("Session database initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize session database: {e}")
            raise
    
    def store_user_session(self, user_id: str, email: str, connection_string: str = None):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Preserve token_version across updates
            cursor.execute(
                """
                INSERT INTO user_sessions (user_id, email, connection_string, last_accessed)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email=excluded.email,
                    connection_string=excluded.connection_string,
                    last_accessed=excluded.last_accessed
                """,
                (user_id, email, connection_string, datetime.now()),
            )
            conn.commit()
            conn.close()
            logger.info(f"Stored session for user: {email}")
        except Exception as e:
            logger.error(f"Failed to store user session: {e}")
            raise
    
    def get_user_session(self, user_id: str) -> Optional[Dict[str, Any]]:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT user_id, email, connection_string, created_at, last_accessed, token_version
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
                    "last_accessed": row[4],
                    "token_version": row[5] if len(row) > 5 else 0,
                }
            return None
        except Exception as e:
            logger.error(f"Failed to get user session: {e}")
            return None
    
    def update_connection_string(self, user_id: str, connection_string: str):
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE user_sessions 
                SET connection_string = ?, last_accessed = ? 
                WHERE user_id = ?
            """, (connection_string, datetime.now(), user_id))
            conn.commit()
            conn.close()
            logger.info(f"Updated connection for user: {user_id}")
        except Exception as e:
            logger.error(f"Failed to update connection string: {e}")
            raise

    def increment_token_version(self, user_id: str) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE user_sessions SET token_version = COALESCE(token_version, 0) + 1, last_accessed = ? WHERE user_id = ?",
                (datetime.now(), user_id),
            )
            conn.commit()
            conn.close()
            logger.info(f"Incremented token version for user: {user_id}")
        except Exception as e:
            logger.error(f"Failed to increment token version: {e}")
            raise

session_manager = SessionManager()

# OAuth2 helper functions
def generate_oauth_url(client_id: str, redirect_uri: str, state: str = None) -> str:
    """Generate OAuth2 authorization URL"""
    if not state:
        state = secrets.token_urlsafe(32)
    
    params = {
        'client_id': client_id,
        'redirect_uri': redirect_uri,
        'scope': 'openid email profile',
        'response_type': 'code',
        'access_type': 'offline',
        'prompt': 'consent',
        'state': state
    }
    
    return f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"

def exchange_code_for_token(code: str, client_id: str, client_secret: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange authorization code for access token"""
    
    # Google OAuth2 token endpoint expects form data with specific headers
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded',
        'Accept': 'application/json'
    }
    
    data = {
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    logger.info(f"Exchanging code for token with Google")
    logger.debug(f"Token request data: {dict((k, v if k != 'client_secret' else '***') for k, v in data.items())}")
    
    try:
        response = requests.post(GOOGLE_TOKEN_URL, data=data, headers=headers, timeout=15)
        
        logger.info(f"Token response status: {response.status_code}")
        
        # Log response for debugging (but don't log sensitive data)
        if response.status_code != 200:
            logger.error(f"Token exchange failed: {response.status_code}")
            logger.error(f"Response headers: {dict(response.headers)}")
            logger.error(f"Response body: {response.text}")
            
        response.raise_for_status()
        
        token_data = response.json()
        logger.info("Successfully exchanged code for token")
        
        return token_data
        
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error during token exchange: {e}")
        logger.error(f"Response content: {e.response.text if e.response else 'No response'}")
        raise
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error during token exchange: {e}")
        raise

def get_user_info(access_token: str) -> Dict[str, Any]:
    """Get user information using access token"""
    headers = {'Authorization': f'Bearer {access_token}'}
    
    response = requests.get(GOOGLE_USERINFO_URL, headers=headers, timeout=10)
    response.raise_for_status()
    
    return response.json()

# Create FastAPI app
app = FastAPI(
    title="PostgreSQL MCP OAuth Companion",
    description="OAuth service for PostgreSQL MCP Server",
    version="1.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add exception handler for better error reporting
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "message": str(exc),
            "type": type(exc).__name__
        }
    )

@app.get("/")
async def root():
    return {
        "service": "PostgreSQL MCP OAuth Companion",
        "version": "1.0.0",
        "status": "running",
        "oauth_configured": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "environment": railway_config['environment'],
        "redirect_uri": REDIRECT_URI
    }

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "PostgreSQL MCP OAuth Companion",
        "oauth_enabled": bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET),
        "environment": railway_config['environment'],
        "redirect_uri": REDIRECT_URI,
        "config": {
            "google_client_id_set": bool(GOOGLE_CLIENT_ID),
            "google_client_secret_set": bool(GOOGLE_CLIENT_SECRET),
            "secret_key_set": bool(SECRET_KEY)
        }
    }

@app.get("/debug/config")
async def debug_config():
    """Debug endpoint to check configuration"""
    return {
        "environment_variables": {
            "GOOGLE_CLIENT_ID": "Set" if GOOGLE_CLIENT_ID else "Not set",
            "GOOGLE_CLIENT_SECRET": "Set" if GOOGLE_CLIENT_SECRET else "Not set", 
            "SECRET_KEY": "Set" if SECRET_KEY else "Not set",
            "REDIRECT_URI": REDIRECT_URI,
            "RAILWAY_ENVIRONMENT": os.getenv('RAILWAY_ENVIRONMENT', 'Not set'),
            "RAILWAY_PUBLIC_DOMAIN": railway_config['public_domain'] or 'Not set'
        },
        "computed_config": railway_config,
        "oauth_endpoints": {
            "google_auth_url": GOOGLE_AUTH_URL,
            "google_token_url": GOOGLE_TOKEN_URL,
            "google_userinfo_url": GOOGLE_USERINFO_URL
        }
    }

@app.get("/auth/login")
async def login():
    """Start OAuth login flow"""
    try:
        logger.info("Starting OAuth login flow")
        
        # Check OAuth configuration
        if not GOOGLE_CLIENT_ID:
            logger.error("GOOGLE_CLIENT_ID not set")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "OAuth not configured", 
                    "message": "GOOGLE_CLIENT_ID environment variable is not set",
                    "fix": "Set GOOGLE_CLIENT_ID environment variable"
                }
            )
        
        if not GOOGLE_CLIENT_SECRET:
            logger.error("GOOGLE_CLIENT_SECRET not set") 
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "OAuth not configured",
                    "message": "GOOGLE_CLIENT_SECRET environment variable is not set", 
                    "fix": "Set GOOGLE_CLIENT_SECRET environment variable"
                }
            )
        
        # Generate state parameter for security
        state = secrets.token_urlsafe(32)
        
        logger.info(f"Creating OAuth URL with client_id: {GOOGLE_CLIENT_ID[:20]}...")
        logger.info(f"Using redirect_uri: {REDIRECT_URI}")
        
        # Generate authorization URL
        authorization_url = generate_oauth_url(GOOGLE_CLIENT_ID, REDIRECT_URI, state)
        
        logger.info(f"Generated authorization URL: {authorization_url[:100]}...")
        
        return {
            "authorization_url": authorization_url, 
            "state": state,
            "redirect_uri": REDIRECT_URI,
            "success": True
        }
        
    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Unexpected error in login endpoint: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Failed to initialize OAuth flow",
                "message": str(e),
                "type": type(e).__name__
            }
        )

@app.get("/auth/callback")
async def callback(request: Request):
    """Handle OAuth callback"""
    try:
        logger.info("Processing OAuth callback")
        
        if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
            raise HTTPException(
                status_code=500, 
                detail={"error": "OAuth not configured"}
            )
        
        code = request.query_params.get('code')
        error = request.query_params.get('error')
        
        if error:
            logger.error(f"OAuth error in callback: {error}")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "OAuth authentication failed",
                    "oauth_error": error,
                    "description": request.query_params.get('error_description', 'No description provided')
                }
            )
        
        if not code:
            logger.error("No authorization code in callback")
            raise HTTPException(
                status_code=400, 
                detail={"error": "Authorization code not provided"}
            )
        
        logger.info(f"Received authorization code: {code[:20]}...")
        
        # Exchange code for token
        logger.info("Exchanging code for token")
        token_data = exchange_code_for_token(code, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, REDIRECT_URI)
        
        access_token = token_data.get('access_token')
        if not access_token:
            logger.error("No access token in response")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "Failed to obtain access token",
                    "token_response": token_data
                }
            )
        
        logger.info("Access token received, fetching user info")
        
        # Get user info
        user_info = get_user_info(access_token)
        
        logger.info(f"User info received for: {user_info.get('email', 'unknown')}")
        
        # Store user session
        user_id = user_info['id']
        email = user_info['email']
        session_manager.store_user_session(user_id, email)

        # Fetch current token version and create session token
        current_session = session_manager.get_user_session(user_id) or {}
        token_version = int(current_session.get('token_version') or 0)
        serializer = URLSafeTimedSerializer(SECRET_KEY)
        session_token = serializer.dumps({'user_id': user_id, 'v': token_version})

        logger.info(f"Session created for user: {email}")

        # Set HTTP-only session cookie for browser-based flow
        response = JSONResponse(content={
            "success": True,
            "user": {"id": user_id, "email": email},
            "session_token": session_token,
            "message": "Authentication successful. You can now set your database connection.",
            "next_steps": {
                "1": "Visit /connection to set your database connection in the browser",
                "2": "Or POST to /connection/set with your token (API)",
                "3": "The MCP server can now use your authenticated connection"
            },
            "next_step_url": "/connection"
        })
        response.set_cookie(
            key="session_token",
            value=session_token,
            httponly=True,
            secure=(railway_config['environment'] == 'production'),
            samesite="Lax",
            max_age=86400 * 7,
            path="/",
        )
        return response
        
    except HTTPException:
        raise
    except requests.RequestException as e:
        logger.error(f"Network error during OAuth callback: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Network error during OAuth flow",
                "message": str(e),
                "type": "NetworkError"
            }
        )
    except Exception as e:
        logger.error(f"OAuth callback error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500, 
            detail={
                "error": f"Authentication failed: {str(e)}",
                "type": type(e).__name__
            }
        )

@app.get("/auth/status")
async def auth_status(request: Request):
    """Check authentication status"""
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return {"authenticated": False}
    
    token = auth_header[7:]  # Remove 'Bearer '
    
    try:
        serializer = URLSafeTimedSerializer(SECRET_KEY)
        data = serializer.loads(token, max_age=86400 * 7)  # 7 days
        user_id = data.get('user_id')
        token_version = int(data.get('v')) if 'v' in data else None
        user_session = session_manager.get_user_session(user_id)

        # Require version match if present in DB
        if user_session:
            current_version = int(user_session.get('token_version') or 0)
            if token_version is None or token_version != current_version:
                return {"authenticated": False}
            return {
                "authenticated": True,
                "user": {
                    "id": user_session['user_id'],
                    "email": user_session['email']
                },
                "has_connection": bool(user_session['connection_string'])
            }
    except Exception as e:
        logger.debug(f"Token validation failed: {str(e)}")
    
    return {"authenticated": False}

def _extract_token_from_request(request: Request) -> Optional[str]:
    auth_header = request.headers.get('Authorization', '')
    if auth_header.startswith('Bearer '):
        return auth_header[7:]
    cookie_token = request.cookies.get('session_token')
    if cookie_token:
        return cookie_token
    return None

@app.post("/auth/logout")
async def logout(request: Request):
    """Invalidate current session by bumping per-user token version and clearing cookie."""
    token = _extract_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail={"error": "Authentication required"})
    try:
        serializer = URLSafeTimedSerializer(SECRET_KEY)
        data = serializer.loads(token, max_age=86400 * 7)
        user_id = data.get('user_id')
        if not user_id:
            raise HTTPException(status_code=401, detail={"error": "Invalid session"})
        session_manager.increment_token_version(user_id)
        # Clear cookie
        resp = JSONResponse({"success": True, "message": "Logged out"})
        resp.delete_cookie(
            key="session_token",
            path="/",
            samesite="Lax",
            secure=(railway_config['environment'] == 'production'),
        )
        return resp
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Logout failed"})

@app.get("/connection")
async def connection_form(request: Request):
    """Simple HTML form for users to set their database connection string."""
    # Check if session cookie exists to provide a better UX
    has_token = bool(request.cookies.get('session_token'))
    html = f"""
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Configure Database Connection</title>
        <style>
          body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Arial; margin: 2rem; color: #111; }}
          .card {{ max-width: 640px; padding: 1.5rem; border: 1px solid #e5e7eb; border-radius: 12px; box-shadow: 0 1px 2px rgba(0,0,0,0.03); }}
          label {{ display: block; font-weight: 600; margin-bottom: 0.5rem; }}
          input[type="text"] {{ width: 100%; padding: 0.75rem; border: 1px solid #d1d5db; border-radius: 8px; font-size: 14px; }}
          button {{ margin-top: 1rem; background: #111827; color: white; padding: 0.75rem 1rem; border: none; border-radius: 8px; cursor: pointer; }}
          .note {{ color: #6b7280; font-size: 0.9rem; margin-top: 0.5rem; }}
          .ok {{ color: #16a34a; }} .err {{ color: #dc2626; }}
        </style>
      </head>
      <body>
        <div class="card">
          <h2>Configure Database Connection</h2>
          <p class="note">{('Session detected. You can submit directly.' if has_token else 'No session cookie found. Authenticate via /auth/login first, or include an Authorization: Bearer token.')}</p>
          <form id="connForm">
            <label for="cs">Connection String</label>
            <input id="cs" name="connection_string" type="text" placeholder="postgresql://user:pass@host:port/db" required />
            <button type="submit">Save Connection</button>
          </form>
          <p id="msg" class="note"></p>
        </div>
        <script>
          const form = document.getElementById('connForm');
          const msg = document.getElementById('msg');
          form.addEventListener('submit', async (e) => {{
            e.preventDefault();
            msg.textContent = 'Saving...';
            const cs = document.getElementById('cs').value;
            try {{
              const res = await fetch('/connection/set', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                credentials: 'include',
                body: JSON.stringify({{ connection_string: cs }})
              }});
              const data = await res.json();
              if (res.ok && data.success) {{
                msg.textContent = '✓ Connection saved successfully';
                msg.className = 'note ok';
              }} else {{
                msg.textContent = 'Error: ' + (data.error || data.message || res.statusText);
                msg.className = 'note err';
              }}
            }} catch (err) {{
              msg.textContent = 'Network error: ' + err;
              msg.className = 'note err';
            }}
          }});
        </script>
      </body>
    </html>
    """
    return HTMLResponse(content=html)

@app.post("/connection/set")
async def set_connection(request: Request):
    """Set database connection for authenticated user"""
    auth_header = request.headers.get('Authorization', '')
    token = None
    if auth_header.startswith('Bearer '):
        token = auth_header[7:]
    else:
        # Fallback to session cookie for browser-based flow
        token = request.cookies.get('session_token')
        if not token:
            raise HTTPException(status_code=401, detail={"error": "Authentication required"})
    
    try:
        serializer = URLSafeTimedSerializer(SECRET_KEY)
        data = serializer.loads(token, max_age=86400 * 7)
        user_id = data['user_id']
        token_version = int(data.get('v')) if 'v' in data else None
        session = session_manager.get_user_session(user_id)
        if not session:
            raise HTTPException(status_code=401, detail={"error": "Invalid session"})
        current_version = int(session.get('token_version') or 0)
        if token_version is None or token_version != current_version:
            raise HTTPException(status_code=401, detail={"error": "Session expired"})
        
        # Support both JSON and form submissions
        connection_string = None
        content_type = request.headers.get('content-type', '')
        if 'application/json' in content_type:
            try:
                request_data = await request.json()
                connection_string = request_data.get('connection_string')
            except Exception:
                connection_string = None
        if not connection_string:
            try:
                form = await request.form()
                connection_string = form.get('connection_string')
            except Exception:
                connection_string = None
        
        if not connection_string:
            raise HTTPException(status_code=400, detail={"error": "connection_string is required"})
        
        # Test connection before storing
        try:
            logger.info(f"Testing database connection for user {user_id}")
            test_conn = psycopg.connect(connection_string, connect_timeout=5)
            test_conn.close()
            logger.info("Database connection test successful")
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            raise HTTPException(status_code=400, detail={"error": f"Invalid connection string: {str(e)}"})
        
        session_manager.update_connection_string(user_id, connection_string)
        
        return {
            "success": True, 
            "message": "Database connection configured successfully",
            "user_id": user_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Set connection error: {str(e)}")
        raise HTTPException(status_code=401, detail={"error": "Authentication failed"})

@app.get("/users/{user_id}/connection")
async def get_user_connection(user_id: str, request: Request):
    """Get database connection for a user (for MCP server to use)"""
    # This endpoint would be used by the MCP server to get user connections
    # In production, add proper authentication/authorization
    
    try:
        user_session = session_manager.get_user_session(user_id)
        if not user_session:
            raise HTTPException(status_code=404, detail={"error": "User session not found"})
        
        if not user_session['connection_string']:
            raise HTTPException(status_code=404, detail={"error": "No database connection configured"})
        
        return {
            "user_id": user_id,
            "connection_configured": True,
            "email": user_session['email'],
            # Don't return the actual connection string in production
            "connection_string": user_session['connection_string']
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user connection error: {e}")
        raise HTTPException(status_code=500, detail={"error": "Internal server error"})

def main():
    """Run the OAuth companion service"""
    parser = argparse.ArgumentParser(description="OAuth Companion Service for PostgreSQL MCP Server")
    parser.add_argument(
        "--port",
        type=int,
        default=railway_config['port'],
        help="Port to run the OAuth service on"
    )
    parser.add_argument(
        "--host",
        default=railway_config['host'],
        help="Host to bind to"
    )
    
    args = parser.parse_args()
    
    # Configuration validation and warnings
    if not GOOGLE_CLIENT_ID:
        logger.warning("GOOGLE_CLIENT_ID not set. OAuth login will not work.")
    if not GOOGLE_CLIENT_SECRET:
        logger.warning("GOOGLE_CLIENT_SECRET not set. OAuth login will not work.")
    if not (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET):
        logger.warning("OAuth not fully configured. The service will start but OAuth functionality will be limited.")
        logger.info("Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET environment variables to enable OAuth.")
    
    logger.info(f"Starting OAuth Companion Service on {args.host}:{args.port}")
    logger.info(f"Environment: {railway_config['environment']}")
    logger.info(f"Redirect URI: {REDIRECT_URI}")
    logger.info(f"OAuth Status: {'✓ Configured' if (GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET) else '✗ Not configured'}")
    
    try:
        uvicorn.run(
            app,
            host=args.host,
            port=args.port,
            log_level="info"
        )
    except Exception as e:
        logger.error(f"Failed to start server: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
