"""
Shared commit processing logic for both webhook and backfill flows.

This module provides a unified way to process commits, ensuring consistency
between real-time webhook processing and historical backfill.
"""
import logging
from typing import Optional
from datetime import datetime
from models.commits import Commit
from services.git_diff import fetch_diff_from_webhook, count_diff_stats
from services.ai_service import summarize_and_upload
import asyncio

logger = logging.getLogger(__name__)

MAX_DIFF_SIZE = 1_000_000  # 1MB limit for diff processing


async def process_commit_from_webhook(
    commit_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    app_id: str,
    private_key_pem: str,
    mongo_db,
    skip_existing: bool = True,
) -> Optional[Commit]:
    """
    Process a commit from a webhook event.
    
    This function:
    1. Checks if commit already exists (idempotency)
    2. Fetches the diff from GitHub API
    3. Creates a Commit model
    4. Stores it in MongoDB
    5. Triggers AI analysis asynchronously
    
    Args:
        commit_data: Commit data from webhook payload
        repo_full_name: Repository full name (owner/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        installation_id: GitHub installation ID
        app_id: GitHub App ID
        private_key_pem: GitHub App private key PEM content
        mongo_db: MongoDB database instance
        skip_existing: If True, skip commits that already exist
    
    Returns:
        Commit model if successfully processed, None if skipped
    """
    try:
        full_commit_hash = commit_data["id"]
        commit_hash = full_commit_hash[:12]
        
        # Check if commit already exists (idempotency)
        if skip_existing:
            existing = mongo_db.commits.find_one({
                "commit_hash": commit_hash,
                "repository_name": repo_name,
                "installation_id": installation_id,
            })
            if existing:
                logger.debug(f"Commit {commit_hash} already exists, skipping")
                return None
        
        # Fetch diff from GitHub API
        commit_api_url = f"https://api.github.com/repos/{repo_full_name}/commits/{full_commit_hash}"
        
        try:
            diff_text = await fetch_diff_from_webhook(
                commit_api_url, installation_id, app_id, private_key_pem
            )
            
            # Skip if diff is too large
            if len(diff_text) > MAX_DIFF_SIZE:
                logger.warning(
                    f"Commit {commit_hash} has diff > {MAX_DIFF_SIZE} bytes, skipping"
                )
                return None
                
        except Exception as e:
            logger.warning(f"Failed to fetch diff for commit {commit_hash}: {e}")
            # Continue with empty diff
            diff_text = ""
        
        # Parse date from webhook timestamp
        timestamp_str = commit_data.get("timestamp")
        if timestamp_str:
            # Handle ISO format with or without timezone
            try:
                if timestamp_str.endswith("Z"):
                    timestamp_str = timestamp_str.replace("Z", "+00:00")
                commit_date = datetime.fromisoformat(timestamp_str)
            except (ValueError, AttributeError):
                logger.warning(f"Could not parse timestamp {timestamp_str}, using current time")
                commit_date = datetime.utcnow()
        else:
            commit_date = datetime.utcnow()
        
        # Create Commit model from webhook data
        commit_model = Commit(
            commit_hash=commit_hash,
            message=commit_data.get("message", ""),
            author=commit_data.get("author", {}).get("name", "Unknown"),
            email=commit_data.get("author", {}).get("email", ""),
            date=commit_date,
            repository_name=repo_name,
            repository_url=repo_url,
            diff=diff_text,
            installation_id=installation_id,
            changes=count_diff_stats(diff_text=diff_text) if diff_text else None,
        )
        
        # Store in MongoDB
        try:
            mongo_db.commits.insert_one(commit_model.model_dump())
        except Exception as e:
            # Handle duplicate key error (race condition)
            if "duplicate key" in str(e).lower() or "E11000" in str(e):
                logger.debug(f"Commit {commit_hash} was inserted concurrently, skipping")
                return None
            raise
        
        # Trigger AI analysis asynchronously
        asyncio.create_task(
            summarize_and_upload(
                diff_text,
                commit_model.author,
                commit_model.email,
                repo_name,
                commit_model.message,
                mongo_db,
                commit_hash=commit_hash,
            )
        )
        
        return commit_model
        
    except Exception as e:
        logger.error(f"Error processing commit {commit_data.get('id', 'unknown')}: {e}")
        return None

