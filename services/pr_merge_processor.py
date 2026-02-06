"""
PR merge event processing for both GitHub and Bitbucket.

This module handles PR merge events separately from regular commits,
storing them in a separate collection without diff/changes tracking.
"""
import logging
from typing import Optional
from datetime import datetime
from models.commits import PRMerge

logger = logging.getLogger(__name__)


async def process_github_pr_merge(
    pr_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    mongo_db,
    skip_existing: bool = True,
) -> Optional[PRMerge]:
    """
    Process a GitHub PR merge event.
    
    This function:
    1. Checks if PR merge already exists (idempotency)
    2. Creates a PRMerge model
    3. Stores it in MongoDB pr_merges collection
    4. Does NOT fetch diff or track line changes
    
    Args:
        pr_data: PR data from GitHub webhook payload
        repo_full_name: Repository full name (owner/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        installation_id: GitHub installation ID
        mongo_db: MongoDB database instance
        skip_existing: If True, skip PR merges that already exist
    
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        # Extract PR information from GitHub webhook payload
        pr_number = pr_data.get("number")
        pr_title = pr_data.get("title", "")
        merged = pr_data.get("merged", False)
        
        if not pr_number:
            logger.warning("PR merge event missing PR number")
            return None
        
        if not merged:
            logger.debug(f"PR #{pr_number} was closed but not merged, skipping")
            return None
        
        # Get merge commit hash
        merge_commit_hash = pr_data.get("merge_commit_sha")
        if not merge_commit_hash:
            logger.warning(f"PR #{pr_number} merge event missing merge_commit_sha")
            return None
        
        merge_commit_hash_short = merge_commit_hash[:12]
        
        # Extract merged_by information
        # GitHub PR merge webhook has merged_by in pull_request.merged_by
        merged_by_info = pr_data.get("merged_by", {})
        merged_by_name = merged_by_info.get("login", "Unknown")
        merged_by_email = merged_by_info.get("email", "")
        
        # If email is not available, try to get from user API or use login
        if not merged_by_email:
            merged_by_email = f"{merged_by_name}@github.com"  # Fallback
        
        # Parse merge date
        merged_at_str = pr_data.get("merged_at")
        if merged_at_str:
            try:
                if merged_at_str.endswith("Z"):
                    merged_at_str = merged_at_str.replace("Z", "+00:00")
                merge_date = datetime.fromisoformat(merged_at_str)
            except (ValueError, AttributeError):
                logger.warning(f"Could not parse merged_at {merged_at_str}, using current time")
                merge_date = datetime.utcnow()
        else:
            merge_date = datetime.utcnow()
        
        # Check if PR merge already exists (idempotency)
        if skip_existing:
            existing = mongo_db.pr_merges.find_one({
                "merge_commit_hash": merge_commit_hash_short,
                "repository_name": repo_name,
                "installation_id": installation_id,
            })
            if existing:
                logger.debug(f"PR merge {merge_commit_hash_short} already exists, skipping")
                return None
        
        # Create PRMerge model
        pr_merge_model = PRMerge(
            pr_number=pr_number,
            pr_title=pr_title,
            merge_commit_hash=merge_commit_hash_short,
            merged_by=merged_by_name,
            merged_by_email=merged_by_email,
            repository_name=repo_name,
            repository_url=repo_url,
            date=merge_date,
            installation_id=installation_id,
            source="github",
        )
        
        # Store in MongoDB
        try:
            mongo_db.pr_merges.insert_one(pr_merge_model.model_dump())
            logger.info(f"Stored PR merge event: PR #{pr_number} merged by {merged_by_name}")
        except Exception as e:
            # Handle duplicate key error (race condition)
            if "duplicate key" in str(e).lower() or "E11000" in str(e):
                logger.debug(f"PR merge {merge_commit_hash_short} was inserted concurrently, skipping")
                return None
            raise
        
        return pr_merge_model
        
    except Exception as e:
        logger.error(f"Error processing GitHub PR merge {pr_data.get('number', 'unknown')}: {e}", exc_info=True)
        return None


async def process_bitbucket_pr_merge(
    pr_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    workspace_id: int,
    mongo_db,
    skip_existing: bool = True,
) -> Optional[PRMerge]:
    """
    Process a Bitbucket PR merge event.
    
    This function:
    1. Checks if PR merge already exists (idempotency)
    2. Creates a PRMerge model
    3. Stores it in MongoDB pr_merges collection
    4. Does NOT fetch diff or track line changes
    
    Args:
        pr_data: PR data from Bitbucket webhook payload
        repo_full_name: Repository full name (workspace/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        workspace_id: Bitbucket workspace identifier (used as installation_id equivalent)
        mongo_db: MongoDB database instance
        skip_existing: If True, skip PR merges that already exist
    
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        # Extract PR information from Bitbucket webhook payload
        pr_number = pr_data.get("id")
        pr_title = pr_data.get("title", "")
        
        if not pr_number:
            logger.warning("PR merge event missing PR ID")
            return None
        
        # Get merge commit hash from Bitbucket PR
        # Bitbucket PR merge commit is in pullrequest.destination.commit.hash
        # or we can get it from the merge commit itself
        merge_commit_info = pr_data.get("merge_commit")
        if not merge_commit_info:
            # Try alternative location
            merge_commit_info = pr_data.get("destination", {}).get("commit", {})
        
        merge_commit_hash = merge_commit_info.get("hash", "") if merge_commit_info else ""
        
        if not merge_commit_hash:
            logger.warning(f"PR #{pr_number} merge event missing merge commit hash")
            return None
        
        merge_commit_hash_short = merge_commit_hash[:12]
        
        # Extract merged_by information
        # Bitbucket PR merge webhook has author in pullrequest.author
        author_info = pr_data.get("author", {})
        merged_by_name = author_info.get("display_name", "Unknown")
        merged_by_email = author_info.get("email", "")
        
        # Bitbucket author might be in raw format: "Name <email@example.com>"
        if not merged_by_email and "raw" in author_info:
            raw_author = author_info.get("raw", "")
            if " <" in raw_author and raw_author.endswith(">"):
                parts = raw_author.rsplit(" <", 1)
                merged_by_name = parts[0]
                merged_by_email = parts[1].rstrip(">")
        
        # Fallback if email still not available
        if not merged_by_email:
            merged_by_email = f"{merged_by_name}@bitbucket.org"
        
        # Parse merge date
        # Bitbucket uses updated_on or created_on for merge time
        merged_at_str = pr_data.get("updated_on") or pr_data.get("created_on")
        if merged_at_str:
            try:
                if merged_at_str.endswith("Z"):
                    merged_at_str = merged_at_str.replace("Z", "+00:00")
                elif "+" not in merged_at_str and "-" not in merged_at_str[-6:]:
                    merged_at_str = merged_at_str + "+00:00"
                merge_date = datetime.fromisoformat(merged_at_str)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse merge date {merged_at_str}: {e}, using current time")
                merge_date = datetime.utcnow()
        else:
            merge_date = datetime.utcnow()
        
        # Check if PR merge already exists (idempotency)
        if skip_existing:
            existing = mongo_db.pr_merges.find_one({
                "merge_commit_hash": merge_commit_hash_short,
                "repository_name": repo_name,
                "installation_id": workspace_id,
            })
            if existing:
                logger.debug(f"PR merge {merge_commit_hash_short} already exists, skipping")
                return None
        
        # Create PRMerge model
        pr_merge_model = PRMerge(
            pr_number=pr_number,
            pr_title=pr_title,
            merge_commit_hash=merge_commit_hash_short,
            merged_by=merged_by_name,
            merged_by_email=merged_by_email,
            repository_name=repo_name,
            repository_url=repo_url,
            date=merge_date,
            installation_id=workspace_id,
            source="bitbucket",
        )
        
        # Store in MongoDB
        try:
            mongo_db.pr_merges.insert_one(pr_merge_model.model_dump())
            logger.info(f"Stored PR merge event: PR #{pr_number} merged by {merged_by_name}")
        except Exception as e:
            # Handle duplicate key error (race condition)
            if "duplicate key" in str(e).lower() or "E11000" in str(e):
                logger.debug(f"PR merge {merge_commit_hash_short} was inserted concurrently, skipping")
                return None
            raise
        
        return pr_merge_model
        
    except Exception as e:
        logger.error(f"Error processing Bitbucket PR merge {pr_data.get('id', 'unknown')}: {e}", exc_info=True)
        return None

