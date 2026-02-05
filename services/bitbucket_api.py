import httpx
from services.auth.bitbucket_oauth import get_access_token


async def fetch_diff(diff_url: str) -> str:
    token = await get_access_token()

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "text/plain",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(diff_url, headers=headers, timeout=15.0)
        response.raise_for_status()

    return response.text
