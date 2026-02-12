import httpx
from fastapi import Header, HTTPException, status
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
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                AUTH_SERVICE_URL,
                headers={"Authorization": f"Bearer {token}"},
            )
            status_code = resp.status_code
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        logger.error(f"Auth API rejected token: {e.response.text}")
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
