import httpx
from fastapi import Header, HTTPException, status
import logging

logger = logging.getLogger(__name__)

AUTH_SERVICE_URL = "https://internal-auth.com/verify" 

async def verify_auth_token(authorization: str = Header(None)):
    return True
    # if not authorization:
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Missing Authorization header",
    #     )

    # try:
    #     scheme, token = authorization.split()
    #     if scheme.lower() != "bearer":
    #         raise ValueError()
    # except ValueError:
    #     raise HTTPException(
    #         status_code=401,
    #         detail="Invalid Authorization format. Use Bearer <token>",
    #     )

    # # Calling internal auth API
    # try:
    #     async with httpx.AsyncClient(timeout=5) as client:
    #         resp = await client.post(
    #             AUTH_SERVICE_URL,
    #             json={"token": token},
    #         )
    #         resp.raise_for_status()
    #         data = resp.json()
    # except Exception as e:
    #     logger.error(f"Auth service error: {e}")
    #     raise HTTPException(500, "Auth service unavailable")

    # # YE I WILL CHANGE AFTER ROHIT GIVE THE RESPONSE STRUCTURE
    # if not data.get("valid"):
    #     raise HTTPException(
    #         status_code=status.HTTP_401_UNAUTHORIZED,
    #         detail="Invalid or expired token",
    #     )

    # # Optionally return user info
    # return data  # or return token
