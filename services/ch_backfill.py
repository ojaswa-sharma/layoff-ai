"""
ClickHouse backfill operations using SQLAlchemy ORM.

This module provides SQLAlchemy ORM-based implementations for bulk commit inserts
and repository status tracking during backfill operations.
"""
import logging
from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from models.commits import Commit, Repository, SyncStatus
from models.ch_models import CommitCH, RepoSyncEventCH
from services.ch_commit_processor import check_commit_exists_ch

logger = logging.getLogger(__name__)


async def insert_commits_batch_ch(
    session: Session,
    commits: List[Commit],
    skip_existing: bool = True,
) -> Dict[str, int]:
    """
    Insert multiple commits into ClickHouse in a batch using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        commits: List of Commit models to insert
        skip_existing: If True, skip commits that already exist
        
    Returns:
        Dictionary with counts: {"inserted": int, "skipped": int}
    """
    if not commits:
        return {"inserted": 0, "skipped": 0}
    
    inserted_count = 0
    skipped_count = 0
    commits_to_insert = []
    
    for commit in commits:
        if skip_existing:
            exists = await check_commit_exists_ch(
                session,
                commit.commit_hash,
                commit.repository_name,
                commit.installation_id or 0,
            )
            if exists:
                skipped_count += 1
                continue
        
        commit_ch = CommitCH.from_pydantic(commit)
        commits_to_insert.append(commit_ch)
    
    if commits_to_insert:
        try:
            session.add_all(commits_to_insert)
            session.commit()
            inserted_count = len(commits_to_insert)
            logger.debug(f"Inserted {inserted_count} commits into ClickHouse in batch")
        except Exception as e:
            session.rollback()
            logger.error(f"Error inserting commits batch into ClickHouse: {e}")
            # Return what we attempted
            inserted_count = len(commits_to_insert)
    
    return {
        "inserted": inserted_count,
        "skipped": skipped_count,
    }


async def update_repository_status_ch(
    session: Session,
    repo_full_name: str,
    installation_id: int,
    updates: Dict[str, Any],
) -> bool:
    """
    Update repository status in ClickHouse repo_sync_events table using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        repo_full_name: Repository full name
        installation_id: Installation ID
        updates: Dictionary of fields to update
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if repository exists
        repo = session.query(RepoSyncEventCH).filter(
            RepoSyncEventCH.repository_full_name == repo_full_name,
            RepoSyncEventCH.installation_id == installation_id,
        ).first()
        
        if not repo:
            # Insert new repository record
            repo = RepoSyncEventCH(
                repository_name=updates.get("repository_name", ""),
                repository_full_name=repo_full_name,
                installation_id=installation_id,
                sync_status=updates.get("sync_status", SyncStatus.BACKFILLING.value),
                # backfill_started_at=updates.get("backfill_started_at"),
                # backfill_completed_at=updates.get("backfill_completed_at"),
                last_commit_processed=updates.get("last_commit_processed"),
                total_commits=updates.get("total_commits", 0),
                error_message=updates.get("error_message"),
                event_time=updates.get("event_time"),
            )
            session.add(repo)
            logger.debug(f"Inserted new repository {repo_full_name} into ClickHouse")
        else:
            # Update existing repository
            if "sync_status" in updates:
                repo.sync_status = updates["sync_status"]
            # if "backfill_started_at" in updates:
            #     repo.backfill_started_at = updates["backfill_started_at"]
            # if "backfill_completed_at" in updates:
            #     repo.backfill_completed_at = updates["backfill_completed_at"]
            if "last_commit_processed" in updates:
                repo.last_commit_processed = updates["last_commit_processed"]
            if "total_commits" in updates:
                repo.total_commits = updates["total_commits"]
            if "error_message" in updates:
                repo.error_message = updates["error_message"]
            if "event_time" in updates:
                repo.event_time = updates["event_time"]
            logger.debug(f"Updated repository {repo_full_name} in ClickHouse")
        
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating repository status in ClickHouse: {e}")
        return False


async def get_repository_status_ch(
    session: Session,
    repo_full_name: str,
    installation_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Get repository status from ClickHouse using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        repo_full_name: Repository full name
        installation_id: Installation ID
        
    Returns:
        Dictionary with repository status or None if not found
    """
    try:
        repo = session.query(RepoSyncEventCH).filter(
            RepoSyncEventCH.repository_full_name == repo_full_name,
            RepoSyncEventCH.installation_id == installation_id,
        ).first()
        
        if not repo:
            return None
        
        return repo.to_dict()
    except Exception as e:
        logger.error(f"Error getting repository status from ClickHouse: {e}")
        return None
