import aiohttp
import jwt
import time

GITHUB_API = "https://api.github.com"

def create_app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": app_id
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")

async def get_installation_token(
    app_id: str,
    private_key_pem: str,
    installation_id: int,
) -> str:
    app_jwt = create_app_jwt(app_id, private_key_pem)
    print(jwt.decode(app_jwt, options={"verify_signature": False}))
    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "layoff-ai-app",
    }
    url = f"{GITHUB_API}/app/installations/{installation_id}/access_tokens"
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url) as resp:
            data = await resp.json()
            if resp.status != 201:
                raise RuntimeError(
                    f"Installation token error {resp.status}: {data}"
                )
            return data["token"]

async def fetch_diff_from_webhook(
    diff_url: str,
    installation_id: int,
    app_id: str,
    private_key_pem: str,
) -> str:
    installation_token = await get_installation_token(
        app_id=app_id,
        private_key_pem=private_key_pem,
        installation_id=installation_id,
    )
    headers = {
        "Authorization": f"token {installation_token}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "layoff-ai",
    }
    
    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(diff_url) as resp:
            if resp.status != 200:
                body = await resp.text()
                raise RuntimeError(
                    f"Diff fetch failed {resp.status}: {body}"
                )
            return await resp.text()

def count_diff_stats(diff_text: str) -> dict:
    additions = 0
    deletions = 0

    for line in diff_text.splitlines():
        if not line:
            continue

        # skip diff metadata
        if (
            line.startswith("+++")
            or line.startswith("---")
            or line.startswith("@@")
        ):
            continue

        if line.startswith("+"):
            additions += 1
        elif line.startswith("-"):
            deletions += 1

    return {
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
    }
