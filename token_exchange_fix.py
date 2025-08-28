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