#!/usr/bin/env python3
"""
OAuth Test Client for PostgreSQL MCP Server

This script helps test the OAuth functionality locally before deploying to Railway.

Usage:
    python test_oauth_client.py

Prerequisites:
    1. Start the server in OAuth mode:
       python postgres_server.py --oauth-only --transport streamable-http --port 8000
    
    2. Set up Google OAuth credentials in your environment:
       export GOOGLE_CLIENT_ID="your_client_id"
       export GOOGLE_CLIENT_SECRET="your_client_secret"
       export SECRET_KEY="your_secret_key"
"""

import requests
import webbrowser
import sys
import json
from urllib.parse import parse_qs, urlparse

SERVER_BASE = "http://localhost:8000"

def test_server_health():
    """Test if the server is running and healthy"""
    print("🔍 Testing server health...")
    try:
        response = requests.get(f"{SERVER_BASE}/health", timeout=5)
        response.raise_for_status()
        data = response.json()
        
        print(f"✅ Server is healthy")
        print(f"   Service: {data.get('service', 'Unknown')}")
        print(f"   OAuth enabled: {data.get('oauth_enabled', False)}")
        print(f"   Environment: {data.get('environment', 'unknown')}")
        return True
        
    except requests.exceptions.ConnectionError:
        print("❌ Server is not running")
        print("   Start the server with: python postgres_server.py --oauth-only --transport streamable-http --port 8000")
        return False
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False

def get_oauth_login_url():
    """Get the OAuth login URL from the server"""
    print("\n🔐 Getting OAuth login URL...")
    try:
        response = requests.get(f"{SERVER_BASE}/auth/login")
        response.raise_for_status()
        data = response.json()
        
        if 'error' in data:
            print(f"❌ Error: {data['error']}")
            print("   Make sure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET are set")
            return None
        
        auth_url = data.get('authorization_url')
        if auth_url:
            print(f"✅ Login URL obtained")
            return auth_url
        else:
            print("❌ No authorization URL in response")
            return None
            
    except Exception as e:
        print(f"❌ Failed to get login URL: {e}")
        return None

def exchange_code_for_token(code):
    """Exchange authorization code for session token"""
    print("\n🔄 Exchanging authorization code for session token...")
    try:
        response = requests.get(f"{SERVER_BASE}/auth/callback", params={'code': code})
        response.raise_for_status()
        data = response.json()
        
        if 'error' in data:
            print(f"❌ Error: {data['error']}")
            return None
        
        session_token = data.get('session_token')
        user_info = data.get('user', {})
        
        if session_token:
            print(f"✅ Authentication successful!")
            print(f"   User: {user_info.get('email', 'Unknown')}")
            print(f"   Session token: {session_token[:20]}...")
            return session_token
        else:
            print("❌ No session token in response")
            return None
            
    except Exception as e:
        print(f"❌ Failed to exchange code: {e}")
        return None

def verify_auth_status(session_token):
    """Verify authentication status with session token"""
    print("\n✅ Verifying authentication status...")
    try:
        headers = {'Authorization': f'Bearer {session_token}'}
        response = requests.get(f"{SERVER_BASE}/auth/status", headers=headers)
        response.raise_for_status()
        data = response.json()
        
        if data.get('authenticated'):
            user = data.get('user', {})
            print(f"✅ Authentication verified")
            print(f"   User: {user.get('email', 'Unknown')}")
            print(f"   Has database connection: {data.get('has_connection', False)}")
            return True
        else:
            print("❌ Authentication not verified")
            return False
            
    except Exception as e:
        print(f"❌ Failed to verify auth status: {e}")
        return False

def set_database_connection(session_token):
    """Set database connection string for the authenticated user"""
    print("\n🗄️ Setting up database connection...")
    
    print("Enter your PostgreSQL connection string:")
    print("Format: postgresql://username:password@host:port/database")
    print("Example: postgresql://postgres:mypass@localhost:5432/mydb")
    print("(Leave empty to skip)")
    
    connection_string = input("Connection string: ").strip()
    
    if not connection_string:
        print("⚠️  No connection string provided, skipping database setup")
        return False
    
    try:
        headers = {
            'Authorization': f'Bearer {session_token}',
            'Content-Type': 'application/json'
        }
        payload = {'connection_string': connection_string}
        
        response = requests.post(f"{SERVER_BASE}/connection/set", 
                               headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()
        
        if data.get('success'):
            print("✅ Database connection configured successfully!")
            return True
        else:
            print(f"❌ Error: {data.get('error', 'Unknown error')}")
            return False
            
    except Exception as e:
        print(f"❌ Failed to set database connection: {e}")
        return False

def main():
    """Main test flow"""
    print("🧪 PostgreSQL MCP Server OAuth Test Client")
    print("=" * 50)
    
    # Step 1: Test server health
    if not test_server_health():
        sys.exit(1)
    
    # Step 2: Get OAuth login URL
    auth_url = get_oauth_login_url()
    if not auth_url:
        sys.exit(1)
    
    # Step 3: Open browser and get authorization code
    print(f"\n🌐 Opening browser for OAuth authentication...")
    print(f"URL: {auth_url}")
    
    try:
        webbrowser.open(auth_url)
    except Exception:
        print("Could not open browser automatically")
    
    print("\nAfter completing OAuth in your browser:")
    print("1. You'll be redirected to a callback URL")
    print("2. Copy the FULL callback URL from your browser")
    print("3. Paste it here")
    
    callback_url = input("\nCallback URL: ").strip()
    
    if not callback_url:
        print("❌ No callback URL provided")
        sys.exit(1)
    
    # Parse authorization code from callback URL
    try:
        parsed = urlparse(callback_url)
        query_params = parse_qs(parsed.query)
        code = query_params.get('code', [None])[0]
        
        if not code:
            print("❌ No authorization code found in callback URL")
            print("Make sure you copied the complete URL including the ?code= parameter")
            sys.exit(1)
        
        print(f"✅ Authorization code extracted: {code[:20]}...")
        
    except Exception as e:
        print(f"❌ Failed to parse callback URL: {e}")
        sys.exit(1)
    
    # Step 4: Exchange code for token
    session_token = exchange_code_for_token(code)
    if not session_token:
        sys.exit(1)
    
    # Step 5: Verify authentication
    if not verify_auth_status(session_token):
        sys.exit(1)
    
    # Step 6: Set up database connection
    set_database_connection(session_token)
    
    # Step 7: Summary and next steps
    print("\n" + "=" * 50)
    print("🎉 OAuth Test Complete!")
    print("\nResults:")
    print("✅ Server is running and healthy")
    print("✅ OAuth flow completed successfully")
    print("✅ Session token obtained and verified")
    
    print(f"\n🔑 Your session token:")
    print(f"{session_token}")
    
    print("\nNext steps:")
    print("1. 🚀 Deploy to Railway using RAILWAY_DEPLOYMENT.md")
    print("2. 🔧 Configure Claude Desktop with your server")
    print("3. 🧪 Test database operations through Claude")
    
    print("\nFor Railway deployment:")
    print("- Your OAuth flow is working correctly")
    print("- Add your Google OAuth credentials to Railway environment variables")
    print("- Railway will auto-configure HTTPS and domains")
    
    print("\nSession token saved for your records.")
    print("Keep this token secure - it provides access to your database connection!")

if __name__ == "__main__":
    main()
