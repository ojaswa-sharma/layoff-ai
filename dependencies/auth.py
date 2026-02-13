import httpx
from fastapi import Header, HTTPException, status
from services.auth.auth_client import get_client
import aiohttp
import logging
from dotenv import load_dotenv
import os

load_dotenv()

logger = logging.getLogger(__name__)

AUTH_SERVICE_URL = os.getenv("AUTH_SERVICE_URL")


async def verify_auth_token(authorization: str = Header(None)):
    """
    Validates Bearer token via internal auth service.
    Returns auth payload if valid, otherwise raises 401.
    """

    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
        )

    try:
        scheme, token = authorization.split(" ", 1)
        if scheme.lower() != "bearer" or not token:
            raise ValueError()
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization format. Expected: Bearer <token>",
        )
    status_code = 401
    try:
        headers = {"Authorization": f"Bearer {token}"}
        client = get_client()
        async with client.get("/v1/auth/validate",headers=headers) as resp:
            status_code = resp.status
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientResponseError as e:
        logger.error(f"Auth API rejected token: {e.message}")
        if int(status_code) == 429:
            raise HTTPException(
                status_code = 429,
                detail="RATE LIMIT EXCEEDED, PLEASE WAIT"
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"[ERROR] Error from core auth service : {e}",
        )
    except Exception as e:
        logger.exception("Auth service unreachable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"[ERROR] Error from internal service : {e}",
        )

    if status_code<200 or status_code>=300:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token expired",
        )

    return {
        "organization_id": data["data"]["organization_id"],
        "raw": data,
    }
