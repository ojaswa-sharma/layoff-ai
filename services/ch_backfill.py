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
from sqlalchemy import select

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
    Update repository status in ClickHouse repo_sync_events table.
    Since ClickHouse doesn't support traditional UPDATE, we use INSERT.
    
    Args:
        session: SQLAlchemy session
        repo_full_name: Repository full name
        installation_id: Installation ID
        updates: Dictionary of fields to update
        
    Returns:
        True if successful, False otherwise
    """
    try:
        from sqlalchemy import text
        
        # Check if repository exists using raw SQL
        check_query = text("""
            SELECT repository_full_name
            FROM repo_sync_events
            WHERE repository_full_name = :repo_full_name
            AND installation_id = :installation_id
            LIMIT 1
        """)
        
        exists = session.execute(
            check_query,
            {"repo_full_name": repo_full_name, "installation_id": installation_id}
        ).first()
        
        # For ClickHouse, we always INSERT (MergeTree handles deduplication based on order_by)
        insert_query = text("""
            INSERT INTO repo_sync_events (
                repository_full_name,
                installation_id,
                repository_name,
                sync_status,
                last_commit_processed,
                total_commits,
                error_message,
                event_time
            ) VALUES (
                :repository_full_name,
                :installation_id,
                :repository_name,
                :sync_status,
                :last_commit_processed,
                :total_commits,
                :error_message,
                :event_time
            )
        """)
        
        session.execute(insert_query, {
            "repository_full_name": repo_full_name,
            "installation_id": installation_id,
            "repository_name": updates.get("repository_name", ""),
            "sync_status": updates.get("sync_status", SyncStatus.BACKFILLING.value),
            "last_commit_processed": updates.get("last_commit_processed", ""),
            "total_commits": updates.get("total_commits", 0),
            "error_message": updates.get("error_message", ""),
            "event_time": updates.get("event_time"),
        })
        
        session.commit()
        
        if not exists:
            logger.debug(f"Inserted new repository {repo_full_name} into ClickHouse")
        else:
            logger.debug(f"Updated repository {repo_full_name} in ClickHouse")
        
        return True
        
    except Exception as e:
        session.rollback()
        logger.error(f"Error updating repository status in ClickHouse: {e}")
        import traceback
        traceback.print_exc()
        return False

async def get_repository_status_ch(
    session: Session,
    repo_full_name: str,
    installation_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Get repository status from ClickHouse using SQLAlchemy ORM.
    """
    from sqlalchemy import text
    
    try:
        query = text("""
            SELECT 
                repository_full_name,
                installation_id,
                repository_name,
                sync_status,
                last_commit_processed,
                total_commits,
                error_message,
                event_time
            FROM repo_sync_events
            WHERE repository_full_name = :repo_full_name
            AND installation_id = :installation_id
            LIMIT 1
        """)
        
        print(f'[DEBUG] About to execute query for {repo_full_name}, {installation_id}')
        
        result = session.execute(
            query,
            {"repo_full_name": repo_full_name, "installation_id": installation_id}
        ).first()
        
        print(f'[DEBUG] Query executed successfully. Result: {result}')
        
        if not result:
            print(f'[DEBUG] No result found, returning None')
            return None
        
        print(f'[DEBUG] Building dict from result')
        result_dict = {
            "repository_full_name": result[0],
            "installation_id": result[1],
            "repository_name": result[2],
            "sync_status": result[3],
            "last_commit_processed": result[4],
            "total_commits": result[5],
            "error_message": result[6],
            "event_time": result[7],
        }
        print(f'[DEBUG] Returning result dict: {result_dict}')
        return result_dict
        
    except Exception as e:
        print(f'[DEBUG] Exception caught in get_repository_status_ch')
        logger.error(f"Error getting repository status from ClickHouse: {e}")
        import traceback
        traceback.print_exc()
        raise  # Re-raise to see where it's actually being caught    

def debug_table_schema(session):
    from sqlalchemy import text
    
    result = session.execute(text("DESCRIBE TABLE repo_sync_events"))
    print("=== TABLE SCHEMA ===")
    for row in result:
        print(row)
    print("===================")
