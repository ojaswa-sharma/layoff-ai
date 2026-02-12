"""
ClickHouse PR merge event processing using SQLAlchemy ORM.

This module handles PR merge events separately from regular commits,
storing them in ClickHouse pr_merges table without diff/changes tracking.
"""
import logging
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.commits import PRMerge
from models.ch_models import PRMergeCH

logger = logging.getLogger(__name__)


async def check_pr_merge_exists_ch(
    session: Session,
    merge_commit_hash: str,
    repo_name: str,
    installation_id: int,
) -> bool:
    """
    Check if a PR merge already exists in ClickHouse (idempotency check).
    
    Args:
        session: SQLAlchemy session
        merge_commit_hash: Merge commit hash to check
        repo_name: Repository name
        installation_id: Installation ID
        
    Returns:
        True if PR merge exists, False otherwise
    """
    try:
        count = session.query(func.count(PRMergeCH.merge_commit_hash)).filter(
            PRMergeCH.merge_commit_hash == merge_commit_hash,
            PRMergeCH.repository_name == repo_name,
            PRMergeCH.installation_id == installation_id,
        ).scalar()
        
        return count > 0
    except Exception as e:
        logger.error(f"Error checking PR merge existence: {e}")
        return False


async def insert_pr_merge_ch(
    session: Session,
    pr_merge: PRMerge,
) -> bool:
    """
    Insert a PR merge into ClickHouse using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        pr_merge: PRMerge model to insert
        
    Returns:
        True if successful, False otherwise
    """
    try:
        pr_merge_ch = PRMergeCH.from_pydantic(pr_merge)
        session.add(pr_merge_ch)
        session.commit()
        
        logger.info(
            f"Stored PR merge event in ClickHouse: PR #{pr_merge.pr_number} "
            f"merged by {pr_merge.merged_by}"
        )
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error inserting PR merge into ClickHouse: {e}")
        return False


async def process_pr_merge_ch(
    pr_merge: PRMerge,
    session: Session,
    skip_existing: bool = True,
) -> Optional[PRMerge]:
    """
    Process and insert a PR merge into ClickHouse using SQLAlchemy ORM.
    
    This function:
    1. Checks if PR merge already exists (idempotency)
    2. Inserts PR merge into ClickHouse
    
    Args:
        pr_merge: PRMerge model to process
        session: SQLAlchemy session
        skip_existing: If True, skip PR merges that already exist
        
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        if skip_existing:
            exists = await check_pr_merge_exists_ch(
                session,
                pr_merge.merge_commit_hash,
                pr_merge.repository_name,
                pr_merge.installation_id,
            )
            if exists:
                logger.debug(
                    f"PR merge {pr_merge.merge_commit_hash} already exists in ClickHouse, skipping"
                )
                return None
        
        success = await insert_pr_merge_ch(session, pr_merge)
        if not success:
            return None
        
        return pr_merge
        
    except Exception as e:
        logger.error(
            f"Error processing PR merge {pr_merge.pr_number}: {e}",
            exc_info=True
        )
        return None


async def process_github_pr_merge(
    pr_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    session: Session,
    skip_existing: bool = True,
) -> Optional[PRMerge]:
    """
    Process a GitHub PR merge event using ClickHouse.
    
    This function:
    1. Checks if PR merge already exists (idempotency)
    2. Creates a PRMerge model
    3. Stores it in ClickHouse pr_merges table
    4. Does NOT fetch diff or track line changes
    
    Args:
        pr_data: PR data from GitHub webhook payload
        repo_full_name: Repository full name (owner/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        installation_id: GitHub installation ID
        session: SQLAlchemy session
        skip_existing: If True, skip PR merges that already exist
    
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        pr_number = pr_data.get("number")
        pr_title = pr_data.get("title", "")
        merged = pr_data.get("merged", False)
        
        if not pr_number:
            logger.warning("PR merge event missing PR number")
            return None
        
        if not merged:
            logger.debug(f"PR #{pr_number} was closed but not merged, skipping")
            return None
        
        merge_commit_hash = pr_data.get("merge_commit_sha")
        if not merge_commit_hash:
            logger.warning(f"PR #{pr_number} merge event missing merge_commit_sha")
            return None
        
        merge_commit_hash_short = merge_commit_hash[:12]
        
        merged_by_info = pr_data.get("merged_by", {})
        merged_by_name = merged_by_info.get("login", "Unknown")
        merged_by_email = merged_by_info.get("email", "")
        
        if not merged_by_email:
            merged_by_email = f"{merged_by_name}@github.com"
        
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
        
        result = await process_pr_merge_ch(
            pr_merge_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing GitHub PR merge {pr_data.get('number', 'unknown')}: {e}", exc_info=True)
        return None


async def process_bitbucket_pr_merge(
    pr_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    workspace_id: int,
    session: Session,
    skip_existing: bool = True,
) -> Optional[PRMerge]:
    """
    Process a Bitbucket PR merge event using ClickHouse.
    
    This function:
    1. Checks if PR merge already exists (idempotency)
    2. Creates a PRMerge model
    3. Stores it in ClickHouse pr_merges table
    4. Does NOT fetch diff or track line changes
    
    Args:
        pr_data: PR data from Bitbucket webhook payload
        repo_full_name: Repository full name (workspace/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        workspace_id: Bitbucket workspace identifier (used as installation_id equivalent)
        session: SQLAlchemy session
        skip_existing: If True, skip PR merges that already exist
    
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        pr_number = pr_data.get("id")
        pr_title = pr_data.get("title", "")
        
        if not pr_number:
            logger.warning("PR merge event missing PR ID")
            return None
        
        merge_commit_info = pr_data.get("merge_commit")
        if not merge_commit_info:
            merge_commit_info = pr_data.get("destination", {}).get("commit", {})
        
        merge_commit_hash = merge_commit_info.get("hash", "") if merge_commit_info else ""
        
        if not merge_commit_hash:
            logger.warning(f"PR #{pr_number} merge event missing merge commit hash")
            return None
        
        merge_commit_hash_short = merge_commit_hash[:12]
        
        author_info = pr_data.get("author", {})
        merged_by_name = author_info.get("display_name", "Unknown")
        merged_by_email = author_info.get("email", "")
        
        if not merged_by_email and "raw" in author_info:
            raw_author = author_info.get("raw", "")
            if " <" in raw_author and raw_author.endswith(">"):
                parts = raw_author.rsplit(" <", 1)
                merged_by_name = parts[0]
                merged_by_email = parts[1].rstrip(">")
        
        if not merged_by_email:
            merged_by_email = f"{merged_by_name}@bitbucket.org"
        
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
        
        result = await process_pr_merge_ch(
            pr_merge_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing Bitbucket PR merge {pr_data.get('id', 'unknown')}: {e}", exc_info=True)
        return None
