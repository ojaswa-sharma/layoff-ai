import asyncio
import os
import requests
from dotenv import load_dotenv
from services.auth.bitbucket_oauth import get_access_token

load_dotenv()


async def main():
    access_token = await get_access_token()

    workspace = os.getenv("BITBUCKET_WORKSPACE")
    if not workspace:
        raise ValueError("BITBUCKET_WORKSPACE environment variable not set")

    url = f"https://api.bitbucket.org/2.0/workspaces/{workspace}/hooks"

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    payload = {
        "description": "Workspace-wide Bitbucket webhook",
        "url": os.getenv("BITBUCKET_WEBHOOK_URL"),
        "active": True,
        "events": [
            "repo:push",
            "pullrequest:created",
            "pullrequest:updated",
            "pullrequest:fulfilled",
            "repo:created",
            "repo:updated"
        ],
    }

    response = requests.post(url, headers=headers, json=payload)
    response.raise_for_status()

    print(response.json())


if __name__ == "__main__":
    asyncio.run(main())
