"""
Service for fetching tech stack information from GitHub repositories.

This module provides functions to fetch language statistics and topics
from GitHub repositories using the GitHub API.
"""
import logging
import aiohttp
from typing import Dict, Any
from services.git_diff import get_installation_token, GITHUB_API

logger = logging.getLogger(__name__)


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

