"""
Service for fetching tech stack information from GitHub and Bitbucket repositories.

This module provides functions to fetch language statistics and topics
from GitHub repositories and language statistics from Bitbucket repositories
using their respective APIs.
"""
import logging
import aiohttp
from typing import Dict, Any
from services.git_diff import get_installation_token, GITHUB_API
from services.auth.bitbucket_oauth import get_access_token

logger = logging.getLogger(__name__)

BITBUCKET_API = "https://api.bitbucket.org/2.0"


async def fetch_github_repository_languages(
    repo_full_name: str,
    app_id: str,
    private_key_pem: str,
    installation_id: int,
) -> Dict[str, int]:
    """
    Fetch language statistics from GitHub repository.
    
    GitHub API endpoint: GET /repos/{owner}/{repo}/languages
    Returns a dictionary mapping language names to bytes of code.
    
    Args:
        repo_full_name: Repository full name (owner/repo)
        app_id: GitHub App ID
        private_key_pem: GitHub App private key PEM content
        installation_id: GitHub installation ID
    
    Returns:
        Dictionary mapping language names to bytes of code, e.g.:
        {"Python": 12345, "JavaScript": 6789, ...}
    """
    try:
        installation_token = await get_installation_token(
            app_id=app_id,
            private_key_pem=private_key_pem,
            installation_id=installation_id,
        )
        
        url = f"{GITHUB_API}/repos/{repo_full_name}/languages"
        headers = {
            "Authorization": f"token {installation_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "house-of-apps-ai-engineering-manager",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    languages = await resp.json()
                    logger.info(f"Fetched languages for {repo_full_name}: {list(languages.keys())}")
                    return languages
                elif resp.status == 404:
                    logger.warning(f"Repository {repo_full_name} not found or no access")
                    return {}
                else:
                    error_body = await resp.text()
                    logger.warning(f"Failed to fetch languages for {repo_full_name}: {resp.status} - {error_body}")
                    return {}
    except Exception as e:
        logger.error(f"Error fetching languages for {repo_full_name}: {e}", exc_info=True)
        return {}


async def fetch_github_repository_topics(
    repo_full_name: str,
    app_id: str,
    private_key_pem: str,
    installation_id: int,
) -> list[str]:
    """
    Fetch repository topics from GitHub.
    
    GitHub API endpoint: GET /repos/{owner}/{repo}
    Topics are included in the repository object.
    
    Args:
        repo_full_name: Repository full name (owner/repo)
        app_id: GitHub App ID
        private_key_pem: GitHub App private key PEM content
        installation_id: GitHub installation ID
    
    Returns:
        List of topic strings, e.g. ["python", "fastapi", "mongodb"]
    """
    try:
        installation_token = await get_installation_token(
            app_id=app_id,
            private_key_pem=private_key_pem,
            installation_id=installation_id,
        )
        
        url = f"{GITHUB_API}/repos/{repo_full_name}"
        headers = {
            "Authorization": f"token {installation_token}",
            "Accept": "application/vnd.github.mercy-preview+json",  # Includes topics
            "User-Agent": "house-of-apps-ai-engineering-manager",
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    repo_data = await resp.json()
                    topics = repo_data.get("topics", [])
                    logger.info(f"Fetched topics for {repo_full_name}: {topics}")
                    return topics
                elif resp.status == 404:
                    logger.warning(f"Repository {repo_full_name} not found or no access")
                    return []
                else:
                    error_body = await resp.text()
                    logger.warning(f"Failed to fetch topics for {repo_full_name}: {resp.status} - {error_body}")
                    return []
    except Exception as e:
        logger.error(f"Error fetching topics for {repo_full_name}: {e}", exc_info=True)
        return []


async def fetch_github_tech_stack(
    repo_full_name: str,
    app_id: str,
    private_key_pem: str,
    installation_id: int,
) -> Dict[str, Any]:
    """
    Fetch complete tech stack information from GitHub repository.
    
    Combines language statistics and topics into a single response.
    
    Args:
        repo_full_name: Repository full name (owner/repo)
        app_id: GitHub App ID
        private_key_pem: GitHub App private key PEM content
        installation_id: GitHub installation ID
    
    Returns:
        Dictionary containing:
        {
            "languages": {"Python": 12345, "JavaScript": 6789, ...},
            "topics": ["python", "fastapi", "mongodb"],
            "source": "github"
        }
    """
    try:
        # Fetch languages and topics concurrently
        languages = await fetch_github_repository_languages(
            repo_full_name=repo_full_name,
            app_id=app_id,
            private_key_pem=private_key_pem,
            installation_id=installation_id,
        )
        
        topics = await fetch_github_repository_topics(
            repo_full_name=repo_full_name,
            app_id=app_id,
            private_key_pem=private_key_pem,
            installation_id=installation_id,
        )
        
        return {
            "languages": languages,
            "topics": topics,
            "source": "github",
        }
    except Exception as e:
        logger.error(f"Error fetching tech stack for {repo_full_name}: {e}", exc_info=True)
        return {
            "languages": {},
            "topics": [],
            "source": "github",
        }



async def fetch_bitbucket_repository_languages(
    workspace: str,
    repo_slug: str,
    access_token: str,
) -> Dict[str, int]:
    """
    Fetch language statistics for a Bitbucket repository.
    
    Bitbucket API endpoint: GET /repositories/{workspace}/{repo_slug}/languages
    Returns a dictionary mapping language names to bytes of code.
    
    Args:
        workspace: Bitbucket workspace ID (e.g. "my-org")
        repo_slug: Repository slug (e.g. "my-repo")
        access_token: OAuth or App Password token
    
    Returns:
        Dictionary mapping language names to bytes of code, e.g.:
        {"Python": 12345, "JavaScript": 6789, ...}
    """
    try:
        url = f"{BITBUCKET_API}/repositories/{workspace}/{repo_slug}/languages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "User-Agent": "house-of-apps-ai-engineering-manager",
        }
        
        repo_full_name = f"{workspace}/{repo_slug}"
        
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
            async with session.get(url, headers=headers) as resp:
                if resp.status == 200:
                    languages = await resp.json()
                    logger.info(f"Fetched languages for {repo_full_name}: {list(languages.keys())}")
                    return languages
                elif resp.status == 404:
                    logger.warning(f"Repository {repo_full_name} not found or no access")
                    return {}
                else:
                    error_body = await resp.text()
                    logger.warning(f"Failed to fetch languages for {repo_full_name}: {resp.status} - {error_body}")
                    return {}
    except Exception as e:
        repo_full_name = f"{workspace}/{repo_slug}"
        logger.error(f"Error fetching languages for {repo_full_name}: {e}", exc_info=True)
        return {}


async def fetch_bitbucket_tech_stack(
    repo_full_name: str,
) -> Dict[str, Any]:
    """
    Fetch complete tech stack information from Bitbucket repository.
    
    Combines language statistics into a single response.
    Note: Bitbucket doesn't support repository topics like GitHub.
    
    Args:
        repo_full_name: Repository full name (workspace/repo)
    
    Returns:
        Dictionary containing:
        {
            "languages": {"Python": 12345, "JavaScript": 6789, ...},
            "topics": [],  # Empty list since Bitbucket doesn't support topics
            "source": "bitbucket"
        }
    """
    try:
        # Parse repo_full_name to extract workspace and repo_slug
        parts = repo_full_name.split("/")
        if len(parts) != 2:
            logger.error(f"Invalid repo_full_name format: {repo_full_name}. Expected 'workspace/repo'")
            return {
                "languages": {},
                "topics": [],
                "source": "bitbucket",
            }
        
        workspace, repo_slug = parts[0], parts[1]
        
        # Get Bitbucket access token
        access_token = await get_access_token()
        
        # Fetch languages
        languages = await fetch_bitbucket_repository_languages(
            workspace=workspace,
            repo_slug=repo_slug,
            access_token=access_token,
        )
        
        return {
            "languages": languages,
            "topics": [],  # Bitbucket doesn't support repository topics
            "source": "bitbucket",
        }
    except Exception as e:
        logger.error(f"Error fetching tech stack for {repo_full_name}: {e}", exc_info=True)
        return {
            "languages": {},
            "topics": [],
            "source": "bitbucket",
        }
