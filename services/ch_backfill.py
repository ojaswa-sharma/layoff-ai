"""
ClickHouse backfill operations using SQLAlchemy ORM.

This module provides SQLAlchemy ORM-based implementations for bulk commit inserts
and repository status tracking during backfill operations.
"""
import logging
import asyncio
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from models.commits import Commit, SyncStatus
from models.ch_models import CommitCH
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


async def backfill_repository_ch(
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    session: Session,
    source: str = "github",
    max_commits: int = 100,
    app_id: Optional[str] = None,
    private_key_pem: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Unified backfill function for GitHub and Bitbucket repositories into ClickHouse.
    
    Fetches the last N commits (default 100) from the repository API and processes them
    using ClickHouse commit processor. Updates repository status accordingly.
    
    Args:
        repo_full_name: Repository full name (owner/repo or workspace/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        installation_id: GitHub installation ID or Bitbucket workspace_id
        session: SQLAlchemy ClickHouse session
        source: Source platform - "github" or "bitbucket" (default: "github")
        max_commits: Maximum number of commits to fetch (default: 100)
        app_id: GitHub App ID (required for GitHub)
        private_key_pem: GitHub App private key PEM content (required for GitHub)
    
    Returns:
        Dictionary with backfill statistics:
        {
            "status": "completed" | "failed",
            "total_commits": int,
            "processed_commits": int,
            "skipped_commits": int,
        }
    """
    source_lower = source.lower()
    if source_lower not in ["github", "bitbucket"]:
        raise ValueError(f"Invalid source: {source}. Must be 'github' or 'bitbucket'")
    
    logger.info(f"Starting ClickHouse backfill for {source_lower} repository: {repo_full_name}")
    
    # Update repository status to BACKFILLING
    await update_repository_status_ch(
        session,
        repo_full_name,
        installation_id,
        {
            "repository_name": repo_name,
            "sync_status": SyncStatus.BACKFILLING.value,
            "event_time": datetime.utcnow(),
            "error_message": None,
        },
    )
    
    try:
        # Import here to avoid circular dependencies
        from services.ch_commit_processor import process_commit_from_webhook, process_bitbucket_commit_from_webhook
        
        # Fetch commits based on source
        if source_lower == "github":
            if not app_id or not private_key_pem:
                raise ValueError("app_id and private_key_pem are required for GitHub backfill")
            
            from services.git_diff import get_installation_token
            from services.backfill import fetch_repository_commits
            
            # Get installation token for GitHub API
            installation_token = await get_installation_token(
                app_id=app_id,
                private_key_pem=private_key_pem,
                installation_id=installation_id,
            )
            
            # Fetch commits (limit to max_commits)
            commits_data = await fetch_repository_commits(
                repo_full_name=repo_full_name,
                installation_token=installation_token,
                max_commits=max_commits,
            )
            
        else:  # bitbucket
            from services.auth.bitbucket_oauth import get_access_token
            from services.backfill import fetch_bitbucket_repository_commits
            
            # Get Bitbucket OAuth token
            access_token = await get_access_token()
            
            # Fetch commits (limit to max_commits)
            commits_data = await fetch_bitbucket_repository_commits(
                repo_full_name=repo_full_name,
                access_token=access_token,
                max_commits=max_commits,
            )
        
        if not commits_data:
            logger.info(f"No commits found for {source_lower} {repo_full_name}")
            await update_repository_status_ch(
                session,
                repo_full_name,
                installation_id,
                {
                    "repository_name": repo_name,
                    "sync_status": SyncStatus.LIVE.value,
                    "total_commits": 0,
                    "event_time": datetime.utcnow(),
                },
            )
            return {
                "status": "completed",
                "total_commits": 0,
                "processed_commits": 0,
                "skipped_commits": 0,
            }
        
        # Process commits in batches to avoid overwhelming the system
        batch_size = 10
        processed_count = 0
        skipped_count = 0
        
        for i in range(0, len(commits_data), batch_size):
            batch = commits_data[i:i + batch_size]
            
            # Process batch concurrently
            tasks = []
            for commit_data in batch:
                if source_lower == "github":
                    # Adapt GitHub API commit format to webhook format
                    # GitHub API uses "sha" and nested "commit" object
                    # Webhook format uses "id" and flat structure
                    webhook_format_commit = {
                        "id": commit_data["sha"],  # Full commit hash
                        "message": commit_data.get("commit", {}).get("message", ""),
                        "timestamp": commit_data.get("commit", {}).get("author", {}).get("date", ""),
                        "author": {
                            "name": commit_data.get("commit", {}).get("author", {}).get("name", "Unknown"),
                            "email": commit_data.get("commit", {}).get("author", {}).get("email", ""),
                        },
                    }
                    
                    tasks.append(
                        process_commit_from_webhook(
                            commit_data=webhook_format_commit,
                            repo_full_name=repo_full_name,
                            repo_name=repo_name,
                            repo_url=repo_url,
                            installation_id=installation_id,
                            app_id=app_id,
                            private_key_pem=private_key_pem,
                            session=session,
                            skip_existing=True,  # Idempotency: skip existing commits
                        )
                    )
                else:  # bitbucket
                    # Bitbucket API commit format is already compatible with process_bitbucket_commit_from_webhook
                    tasks.append(
                        process_bitbucket_commit_from_webhook(
                            commit_data=commit_data,
                            repo_full_name=repo_full_name,
                            repo_name=repo_name,
                            repo_url=repo_url,
                            workspace_id=installation_id,
                            session=session,
                            skip_existing=True,  # Idempotency: skip existing commits
                        )
                    )
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Error in batch processing: {result}")
                    skipped_count += 1
                elif result is None:
                    skipped_count += 1
                else:
                    processed_count += 1
            
            # Get commit hash for progress tracking (different field names for GitHub vs Bitbucket)
            last_commit_hash = ""
            if batch:
                if source_lower == "github":
                    last_commit_hash = batch[0].get("sha", "")
                else:  # bitbucket
                    last_commit_hash = batch[0].get("hash", "")
            
            # Update progress
            await update_repository_status_ch(
                session,
                repo_full_name,
                installation_id,
                {
                    "repository_name": repo_name,
                    "sync_status": SyncStatus.BACKFILLING.value,
                    "total_commits": processed_count,
                    "last_commit_processed": last_commit_hash,
                    "event_time": datetime.utcnow(),
                },
            )
            
            logger.info(
                f"Backfill progress for {source_lower} {repo_full_name}: "
                f"{processed_count} processed, {skipped_count} skipped"
            )
            
            # Small delay between batches to respect rate limits
            await asyncio.sleep(1)
        
        # Check current repository status - only update to LIVE if not already LIVE
        # (LIVE status may be set when 20th commit is sent to Zep)
        repo_status = await get_repository_status_ch(
            session,
            repo_full_name,
            installation_id,
        )
        current_status = repo_status.get("sync_status") if repo_status else None
        
        # Only update status if not already LIVE
        if current_status != SyncStatus.LIVE.value:
            await update_repository_status_ch(
                session,
                repo_full_name,
                installation_id,
                {
                    "repository_name": repo_name,
                    "sync_status": SyncStatus.LIVE.value,
                    "total_commits": processed_count,
                    "event_time": datetime.utcnow(),
                },
            )
        else:
            # Already LIVE, just update completion timestamp and count
            await update_repository_status_ch(
                session,
                repo_full_name,
                installation_id,
                {
                    "repository_name": repo_name,
                    "sync_status": SyncStatus.LIVE.value,
                    "total_commits": processed_count,
                    "event_time": datetime.utcnow(),
                },
            )
        
        logger.info(
            f"Backfill completed for {source_lower} {repo_full_name}: "
            f"{processed_count} processed, {skipped_count} skipped, "
            f"status: {current_status or 'LIVE'}"
        )
        
        return {
            "status": "completed",
            "total_commits": len(commits_data),
            "processed_commits": processed_count,
            "skipped_commits": skipped_count,
        }
        
    except Exception as e:
        logger.error(f"Backfill failed for {source_lower} {repo_full_name}: {e}", exc_info=True)
        
        # Update repository status to FAILED
        await update_repository_status_ch(
            session,
            repo_full_name,
            installation_id,
            {
                "repository_name": repo_name,
                "sync_status": SyncStatus.FAILED.value,
                "error_message": str(e),
                "event_time": datetime.utcnow(),
            },
        )
        
        return {
            "status": "failed",
            "total_commits": 0,
            "processed_commits": 0,
            "skipped_commits": 0,
            "error": str(e),
        }
