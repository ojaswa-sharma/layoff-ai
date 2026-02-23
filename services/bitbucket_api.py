import httpx
from typing import Optional, Dict, Any
from services.auth.bitbucket_oauth import get_access_token

BITBUCKET_API = "https://api.bitbucket.org/2.0"


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


async def fetch_commit_by_hash(
    repo_full_name: str,
    commit_hash: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch a single commit from Bitbucket API using the commit hash.
    
    Args:
        repo_full_name: Repository full name (workspace/repo)
        commit_hash: Full commit hash (e.g., "1e90705eb1bd")
    
    Returns:
        Commit JSON data with author information, or None if not found
    """
    try:
        token = await get_access_token()
        
        commit_url = f"{BITBUCKET_API}/repositories/{repo_full_name}/commit/{commit_hash}"
        
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(commit_url, headers=headers, timeout=15.0)
            response.raise_for_status()
            
            return response.json()
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            return None
        raise
    except Exception as e:
        raise RuntimeError(f"Failed to fetch commit {commit_hash} from Bitbucket: {e}")
