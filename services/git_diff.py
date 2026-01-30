import aiohttp
import jwt
import time

def create_app_jwt(app_id: str, private_key_pem: str) -> str:
    now = int(time.time())
    payload = {
        "iat": now - 60,
        "exp": now + 600,
        "iss": app_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")

async def get_installation_token(app_id, private_key_pem, installation_id):
    app_jwt = create_app_jwt(app_id, private_key_pem)

    headers = {
        "Authorization": f"Bearer {app_jwt}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "layoff-ai-app",
    }

    url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.post(url) as resp:
            data = await resp.json()

            if resp.status != 201:
                raise RuntimeError(f"{resp.status}: {data}")

            return data["token"]


async def fetch_git_diff(url):
    diff_url = f"{url}.diff"
    print(diff_url)
    headers = {
        "User-Agent": "layoff-ai",
        "Accept": "application/vnd.github.v3.diff",
    }

    async with aiohttp.ClientSession(headers=headers) as session:
        async with session.get(diff_url) as response:
            return await response.text()
