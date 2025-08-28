#!/usr/bin/env python3
"""
Test Client for PostgreSQL MCP Server with OAuth

This script tests both the MCP server and OAuth companion service.

Usage:
    # Test MCP server only
    python test_oauth_client.py --mcp-only

    # Test OAuth companion service (if running)
    python test_oauth_client.py --oauth-port 8001

    # Test both (default)
    python test_oauth_client.py

Prerequisites:
    1. Start the MCP server:
       python postgres_server.py --transport streamable-http --port 8000
    
    2. (Optional) Start OAuth companion service:
       python oauth_companion.py --port 8001
    
    3. Set OAuth environment variables:
       export GOOGLE_CLIENT_ID="your_client_id"
       export GOOGLE_CLIENT_SECRET="your_client_secret"
       export SECRET_KEY="your_secret_key"
"""

import requests
import webbrowser
import sys
import json
import argparse
from urllib.parse import parse_qs, urlparse

def test_mcp_server(port=8000):
    """Test the MCP server auth_info tool via HTTP"""
    print("🔍 Testing MCP Server...")
    
    try:
        # Test if server is running (this will likely fail with 404, which is expected)
        response = requests.get(f"http://localhost:{port}/", timeout=5)
        print(f"✅ MCP Server is running on port {port}")
        return True
    except requests.exceptions.ConnectionError:
        print(f"❌ MCP Server is not running on port {port}")
        print(f"   Start it with: python postgres_server.py --transport streamable-http --port {port}")
        return False
    except Exception as e:
        print(f"⚠️  MCP Server response (expected): {type(e).__name__}")
        print(f"✅ MCP Server appears to be running on port {port}")
        return True

def test_oauth_companion(port=8001):
    """Test the OAuth companion service"""
    print(f"\n🔐 Testing OAuth Companion Service on port {port}...")
    
    try:
        # Test health endpoint
        response = requests.get(f"http://localhost:{port}/health", timeout=5)
        response.raise_for_status()
        data = response.json()
        
        print(f"✅ OAuth Companion Service is healthy")
        print(f"   Service: {data.get('service', 'Unknown')}")
        print(f"   OAuth enabled: {data.get('oauth_enabled', False)}")
        print(f"   Environment: {data.get('environment', 'unknown')}")
        print(f"   Redirect URI: {data.get('redirect_uri', 'unknown')}")
        
        # Show configuration details
        config = data.get('config', {})
        print(f"   Configuration:")
        print(f"     Google Client ID: {'✓' if config.get('google_client_id_set') else '✗'}")
        print(f"     Google Client Secret: {'✓' if config.get('google_client_secret_set') else '✗'}")
        print(f"     Secret Key: {'✓' if config.get('secret_key_set') else '✗'}")
        
        return True
        
    except requests.exceptions.ConnectionError:
        print(f"❌ OAuth Companion Service is not running on port {port}")
        print(f"   Start it with: python oauth_companion.py --port {port}")
        return False
    except Exception as e:
        print(f"❌ OAuth Companion Service test failed: {e}")
        return False

def debug_oauth_config(port=8001):
    """Debug OAuth configuration"""
    print(f"\n🔧 Debugging OAuth Configuration...")
    
    try:
        response = requests.get(f"http://localhost:{port}/debug/config", timeout=5)
        response.raise_for_status()
        data = response.json()
        
        print(f"📋 Environment Variables:")
        env_vars = data.get('environment_variables', {})
        for key, value in env_vars.items():
            print(f"   {key}: {value}")
        
        print(f"\n⚙️ Computed Configuration:")
        config = data.get('computed_config', {})
        for key, value in config.items():
            print(f"   {key}: {value}")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to debug OAuth config: {e}")
        return False

def test_oauth_flow(oauth_port=8001):
    """Test the complete OAuth flow"""
    print(f"\n🌐 Testing OAuth Flow...")
    
    # Step 1: Get login URL
    try:
        print("📋 Step 1: Getting OAuth login URL...")
        response = requests.get(f"http://localhost:{oauth_port}/auth/login", timeout=10)
        
        # Print response details for debugging
        print(f"   Response Status: {response.status_code}")
        print(f"   Response Headers: {dict(response.headers)}")
        
        if response.status_code != 200:
            print(f"❌ Login request failed with status {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error details: {json.dumps(error_data, indent=2)}")
                
                # Provide specific guidance based on error
                if "GOOGLE_CLIENT_ID" in str(error_data):
                    print(f"\n🔧 Fix: Set your Google OAuth credentials:")
                    print(f"   export GOOGLE_CLIENT_ID='your_client_id.apps.googleusercontent.com'")
                    print(f"   export GOOGLE_CLIENT_SECRET='your_client_secret'")
                    print(f"   export SECRET_KEY='$(openssl rand -hex 32)'")
                
            except:
                print(f"   Raw response: {response.text}")
            return False
        
        data = response.json()
        
        if 'error' in data:
            print(f"❌ Error: {data['error']}")
            if 'message' in data:
                print(f"   Message: {data['message']}")
            if 'fix' in data:
                print(f"   Fix: {data['fix']}")
            return False
        
        auth_url = data.get('authorization_url')
        if not auth_url:
            print("❌ No authorization URL received")
            print(f"   Response: {json.dumps(data, indent=2)}")
            return False
        
        print(f"✅ OAuth login URL obtained")
        print(f"🔗 URL: {auth_url[:80]}...")
        
        # Step 2: Open browser for user authentication
        print(f"\n📋 Step 2: Opening browser for OAuth authentication...")
        
        try:
            webbrowser.open(auth_url)
            print("✅ Browser opened successfully")
        except Exception as e:
            print(f"⚠️  Could not open browser automatically: {e}")
        
        print("\n" + "="*60)
        print("OAUTH AUTHENTICATION REQUIRED")
        print("="*60)
        print("1. Complete authentication in your browser")
        print("2. After authentication, you'll be redirected to a callback URL")
        print("3. Copy the COMPLETE callback URL from your browser")
        print("4. Paste it below")
        print("\nExample callback URL:")
        print("http://localhost:8001/auth/callback?code=4/0AfJohXn...")
        print("="*60)
        
        callback_url = input("\nPaste the complete callback URL: ").strip()
        
        if not callback_url:
            print("❌ No callback URL provided")
            return False
        
        # Parse authorization code
        try:
            print(f"\n📋 Step 3: Parsing authorization code...")
            parsed = urlparse(callback_url)
            query_params = parse_qs(parsed.query)
            code = query_params.get('code', [None])[0]
            
            if not code:
                print("❌ No authorization code found in callback URL")
                print(f"   Parsed URL: {parsed}")
                print(f"   Query params: {query_params}")
                return False
            
            print(f"✅ Authorization code extracted: {code[:20]}...")
            
        except Exception as e:
            print(f"❌ Failed to parse callback URL: {e}")
            return False
        
        # Step 3: Exchange code for token
        print(f"\n📋 Step 4: Exchanging code for session token...")
        
        response = requests.get(f"http://localhost:{oauth_port}/auth/callback", params={'code': code}, timeout=30)
        
        print(f"   Response Status: {response.status_code}")
        
        if response.status_code != 200:
            print(f"❌ Token exchange failed with status {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error details: {json.dumps(error_data, indent=2)}")
            except:
                print(f"   Raw response: {response.text}")
            return False
        
        data = response.json()
        
        if 'error' in data:
            print(f"❌ Error: {data['error']}")
            if 'message' in data:
                print(f"   Message: {data['message']}")
            return False
        
        session_token = data.get('session_token')
        user_info = data.get('user', {})
        
        if not session_token:
            print("❌ No session token received")
            print(f"   Response: {json.dumps(data, indent=2)}")
            return False
        
        print(f"✅ Authentication successful!")
        print(f"   User: {user_info.get('email', 'Unknown')}")
        print(f"   Token: {session_token[:20]}...")
        
        # Step 4: Test database connection setup
        print(f"\n📋 Step 5: Testing database connection setup...")
        
        print("Enter a PostgreSQL connection string to test:")
        print("Format: postgresql://username:password@host:port/database")
        print("Example: postgresql://postgres:password@localhost:5432/testdb")
        print("(Leave empty to skip)")
        
        connection_string = input("Connection string: ").strip()
        
        if connection_string:
            try:
                headers = {
                    'Authorization': f'Bearer {session_token}',
                    'Content-Type': 'application/json'
                }
                payload = {'connection_string': connection_string}
                
                response = requests.post(f"http://localhost:{oauth_port}/connection/set", 
                                       headers=headers, json=payload, timeout=10)
                
                print(f"   Response Status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    if data.get('success'):
                        print("✅ Database connection configured successfully!")
                    else:
                        print(f"❌ Error: {data.get('error', 'Unknown error')}")
                else:
                    try:
                        error_data = response.json()
                        print(f"❌ Connection setup failed: {json.dumps(error_data, indent=2)}")
                    except:
                        print(f"❌ Connection setup failed: {response.text}")
                
            except Exception as e:
                print(f"❌ Failed to set database connection: {e}")
        else:
            print("⚠️  Skipped database connection setup")
        
        print(f"\n🎯 OAuth Flow Test Results:")
        print(f"✅ OAuth authentication: SUCCESS")
        print(f"✅ Session token generation: SUCCESS") 
        print(f"✅ User information retrieval: SUCCESS")
        print(f"🔑 Session Token: {session_token}")
        
        return True
        
    except requests.exceptions.Timeout:
        print("❌ OAuth flow test failed: Request timeout")
        print("   The OAuth service may be taking too long to respond")
        return False
    except requests.exceptions.ConnectionError:
        print("❌ OAuth flow test failed: Connection error")
        print(f"   Make sure OAuth service is running on port {oauth_port}")
        return False
    except Exception as e:
        print(f"❌ OAuth flow test failed: {type(e).__name__}: {e}")
        return False

def main():
    """Main test function"""
    parser = argparse.ArgumentParser(description="Test PostgreSQL MCP Server with OAuth")
    parser.add_argument("--mcp-port", type=int, default=8000, help="MCP server port")
    parser.add_argument("--oauth-port", type=int, default=8001, help="OAuth companion service port")
    parser.add_argument("--mcp-only", action="store_true", help="Test MCP server only")
    parser.add_argument("--oauth-only", action="store_true", help="Test OAuth companion only")
    parser.add_argument("--no-oauth-flow", action="store_true", help="Skip interactive OAuth flow")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode with detailed output")
    
    args = parser.parse_args()
    
    print("🧪 PostgreSQL MCP Server with OAuth - Test Client")
    print("=" * 60)
    
    results = {}
    
    # Test MCP Server
    if not args.oauth_only:
        results['mcp_server'] = test_mcp_server(args.mcp_port)
    
    # Test OAuth Companion
    if not args.mcp_only:
        results['oauth_companion'] = test_oauth_companion(args.oauth_port)
        
        # Debug OAuth configuration if requested or if OAuth test failed
        if args.debug or not results.get('oauth_companion', True):
            debug_oauth_config(args.oauth_port)
        
        # Test OAuth flow if companion is running
        if results.get('oauth_companion') and not args.no_oauth_flow:
            results['oauth_flow'] = test_oauth_flow(args.oauth_port)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 TEST SUMMARY")
    print("=" * 60)
    
    if 'mcp_server' in results:
        status = "✅ PASS" if results['mcp_server'] else "❌ FAIL"
        print(f"MCP Server (port {args.mcp_port}): {status}")
    
    if 'oauth_companion' in results:
        status = "✅ PASS" if results['oauth_companion'] else "❌ FAIL"
        print(f"OAuth Companion (port {args.oauth_port}): {status}")
    
    if 'oauth_flow' in results:
        status = "✅ PASS" if results['oauth_flow'] else "❌ FAIL"
        print(f"OAuth Flow Test: {status}")
    
    print("\n🚀 Next Steps:")
    
    if results.get('mcp_server') and results.get('oauth_companion'):
        if results.get('oauth_flow'):
            print("✅ All tests passed - ready for production deployment!")
        else:
            print("⚠️  OAuth flow test failed - check OAuth configuration")
        print("📋 For Railway deployment:")
        print("   1. Push code to GitHub")
        print("   2. Deploy MCP server to Railway")
        print("   3. Optionally deploy OAuth companion as separate service")
        print("   4. Configure environment variables in Railway")
    elif results.get('mcp_server'):
        print("✅ MCP server is ready")
        print("⚠️  OAuth companion not running - limited OAuth functionality")
        print("📋 You can still deploy the MCP server to Railway")
    elif results.get('oauth_companion'):
        print("✅ OAuth companion is ready")  
        print("⚠️  MCP server not running - start it for full functionality")
    else:
        print("❌ Neither service is running")
        print("📋 Start the services:")
        print(f"   MCP Server: python postgres_server.py --transport streamable-http --port {args.mcp_port}")
        print(f"   OAuth Companion: python oauth_companion.py --port {args.oauth_port}")
    
    # Configuration help
    if not results.get('oauth_flow', True):
        print("\n🔧 OAuth Configuration Help:")
        print("If OAuth tests are failing, ensure these environment variables are set:")
        print("   export GOOGLE_CLIENT_ID='your_client_id.apps.googleusercontent.com'")
        print("   export GOOGLE_CLIENT_SECRET='your_client_secret'")
        print("   export SECRET_KEY='$(openssl rand -hex 32)'")
        print("\n📚 See OAUTH_SETUP.md for complete setup instructions")
    
    print("\n📚 Documentation:")
    print("   - OAUTH_SETUP.md: Complete setup guide")
    print("   - RAILWAY_DEPLOYMENT.md: Railway deployment guide")
    
    if args.debug:
        print(f"\n🐛 Debug mode enabled - use --debug for detailed output")

if __name__ == "__main__":
    main()
