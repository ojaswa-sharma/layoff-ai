import os
import time
import httpx
from dotenv import load_dotenv

load_dotenv()

BITBUCKET_TOKEN_URL = "https://bitbucket.org/site/oauth2/access_token"

CLIENT_ID = os.getenv("BITBUCKET_CLIENT_ID")
CLIENT_SECRET = os.getenv("BITBUCKET_CLIENT_SECRET")

_cached_token = None
_token_expiry = 0


async def get_access_token() -> str:
    global _cached_token, _token_expiry

    # reuse token if still valid
    if _cached_token and time.time() < _token_expiry:
        return _cached_token

    async with httpx.AsyncClient() as client:
        response = await client.post(
            BITBUCKET_TOKEN_URL,
            auth=(CLIENT_ID, CLIENT_SECRET),
            data={"grant_type": "client_credentials"},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

    _cached_token = data["access_token"]
    _token_expiry = time.time() + data["expires_in"] - 60  # safety buffer

    return _cached_token