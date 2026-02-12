"""
ClickHouse backfill operations using SQLAlchemy ORM.

This module provides SQLAlchemy ORM-based implementations for bulk commit inserts
and repository status tracking during backfill operations.
"""
import logging
import asyncio
import aiohttp
from typing import List, Optional, Dict, Any
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.orm import Session
from models.commits import Commit, SyncStatus
from models.ch_models import CommitCH
from services.clickhouse_service.ch_commit_processor import check_commit_exists_ch

logger = logging.getLogger(__name__)

BITBUCKET_MAX_COMMITS_PER_PAGE = 50
BITBUCKET_API = "https://api.bitbucket.org/2.0"
GITHUB_API = "https://api.github.com"
MAX_COMMITS_PER_PAGE = 100


async def fetch_with_retry(
    session: aiohttp.ClientSession,
    url: str,
    headers: Dict[str, str],
    max_retries: int = 3,
    base_delay: float = 1.0,
) -> aiohttp.ClientResponse:
    """
    Fetch with exponential backoff retry logic.
    
    Handles rate limiting (429) and transient errors (5xx).
    
    Note: The returned response must be used within an async context manager
    or read immediately to avoid connection closed errors.
    """
    for attempt in range(max_retries):
        try:
            resp = await session.get(url, headers=headers)
            
            if resp.status == 429:
                retry_after = int(resp.headers.get("Retry-After", base_delay * (2 ** attempt)))
                logger.warning(
                    f"Rate limited. Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})"
                )
                resp.close()
                await asyncio.sleep(retry_after)
                continue
            
            if resp.status >= 500:
                if attempt < max_retries - 1:
                    delay = base_delay * (2 ** attempt)
                    logger.warning(
                        f"Server error {resp.status}. Retrying after {delay}s (attempt {attempt + 1}/{max_retries})"
                    )
                    resp.close()
                    await asyncio.sleep(delay)
                    continue
            
            return resp
                
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            if attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                logger.warning(
                    f"Network error: {e}. Retrying after {delay}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(delay)
            else:
                raise
    
    raise RuntimeError(f"Failed to fetch {url} after {max_retries} attempts")


async def fetch_bitbucket_repository_commits(
    repo_full_name: str,
    access_token: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    max_commits: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch historical commits from a Bitbucket repository with pagination.
    
    Args:
        repo_full_name: Repository full name (workspace/repo)
        access_token: Bitbucket OAuth access token
        since: Only fetch commits after this date (optional)
        until: Only fetch commits before this date (optional)
        max_commits: Maximum total commits to fetch (None = unlimited)
    
    Returns:
        List of commit dictionaries from Bitbucket API
    """
    all_commits = []
    page = 1
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }
    
    url = f"{BITBUCKET_API}/repositories/{repo_full_name}/commits"
    
    async with aiohttp.ClientSession() as session:
        while True:
            params = {
                "pagelen": BITBUCKET_MAX_COMMITS_PER_PAGE,
                "page": page,
            }
            
            if since:
                params["since"] = since.isoformat()
            if until:
                params["until"] = until.isoformat()
            
            query_string = "&".join([f"{k}={v}" for k, v in params.items()])
            full_url = f"{url}?{query_string}"
            
            logger.info(f"Fetching Bitbucket commits page {page} for {repo_full_name}")
            
            resp = await fetch_with_retry(session, full_url, headers)
            
            try:
                if resp.status == 404:
                    logger.warning(f"Repository {repo_full_name} not found or no access")
                    break
                
                if resp.status != 200:
                    error_body = await resp.text()
                    raise RuntimeError(
                        f"Failed to fetch Bitbucket commits: {resp.status} - {error_body}"
                    )
                
                data = await resp.json()
            finally:
                resp.close()
            commits = data.get("values", [])
            
            if not commits:
                break
            
            all_commits.extend(commits)
            
            if max_commits and len(all_commits) >= max_commits:
                all_commits = all_commits[:max_commits]
                break
            
            next_url = data.get("next")
            if not next_url:
                break
            
            page += 1
            
            await asyncio.sleep(0.5)
    
    logger.info(f"Fetched {len(all_commits)} commits from Bitbucket {repo_full_name}")
    return all_commits


async def fetch_repository_commits(
    repo_full_name: str,
    installation_token: str,
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    per_page: int = MAX_COMMITS_PER_PAGE,
    max_commits: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    Fetch historical commits from a repository with pagination.
    
    Args:
        repo_full_name: Repository full name (owner/repo)
        installation_token: GitHub installation access token
        since: Only fetch commits after this date (optional)
        until: Only fetch commits before this date (optional)
        per_page: Number of commits per page (max 100)
        max_commits: Maximum total commits to fetch (None = unlimited)
    
    Returns:
        List of commit dictionaries from GitHub API
    """
    all_commits = []
    page = 1
    headers = {
        "Authorization": f"token {installation_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "layoff-ai-app",
    }
    
    url = f"{GITHUB_API}/repos/{repo_full_name}/commits"
    params = {
        "per_page": min(per_page, MAX_COMMITS_PER_PAGE),
        "page": page,
    }
    
    if since:
        params["since"] = since.isoformat()
    if until:
        params["until"] = until.isoformat()
    
    async with aiohttp.ClientSession() as session:
        while True:
            params["page"] = page
            full_url = f"{url}?per_page={params['per_page']}&page={page}"
            if since:
                full_url += f"&since={since.isoformat()}"
            if until:
                full_url += f"&until={until.isoformat()}"
            
            logger.info(f"Fetching commits page {page} for {repo_full_name}")
            
            resp = await fetch_with_retry(session, full_url, headers)
            
            try:
                if resp.status == 404:
                    logger.warning(f"Repository {repo_full_name} not found or no access")
                    break
                
                if resp.status != 200:
                    error_body = await resp.text()
                    raise RuntimeError(
                        f"Failed to fetch commits: {resp.status} - {error_body}"
                    )
                
                commits = await resp.json()
            finally:
                resp.close()
            
            if not commits:
                break
            
            all_commits.extend(commits)
            
            if isinstance(max_commits, str):
                try:
                    max_commits = int(max_commits)
                except:
                    print(f"[ERROR] MAX COMMITS : {max_commits} could not be parsed")
                    max_commits = 25
            if max_commits and len(all_commits) >= max_commits:
                all_commits = all_commits[:max_commits]
                break
            
            link_header = resp.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
            
            page += 1
            
            await asyncio.sleep(0.5)
    
    logger.info(f"Fetched {len(all_commits)} commits from {repo_full_name}")
    return all_commits


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
        
        
        result = session.execute(
            query,
            {"repo_full_name": repo_full_name, "installation_id": installation_id}
        ).first()
        
        
        if not result:
            print(f'[DEBUG] No result found, returning None')
            return None
        
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
        return result_dict
        
    except Exception as e:
        print(f'[DEBUG] Exception caught in get_repository_status_ch')
        logger.error(f"Error getting repository status from ClickHouse: {e}")
        import traceback
        traceback.print_exc()
        raise

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
        from services.clickhouse_service.ch_commit_processor import process_commit_from_webhook, process_bitbucket_commit_from_webhook
        
        if source_lower == "github":
            if not app_id or not private_key_pem:
                raise ValueError("app_id and private_key_pem are required for GitHub backfill")
            
            from services.git_diff import get_installation_token
            
            installation_token = await get_installation_token(
                app_id=app_id,
                private_key_pem=private_key_pem,
                installation_id=installation_id,
            )
            
            commits_data = await fetch_repository_commits(
                repo_full_name=repo_full_name,
                installation_token=installation_token,
                max_commits=max_commits,
            )
            
        else:
            from services.auth.bitbucket_oauth import get_access_token
            
            access_token = await get_access_token()
            
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
        
        batch_size = 10
        processed_count = 0
        skipped_count = 0
        
        for i in range(0, len(commits_data), batch_size):
            batch = commits_data[i:i + batch_size]
            
            tasks = []
            for commit_data in batch:
                if source_lower == "github":
                    webhook_format_commit = {
                        "id": commit_data["sha"],
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
                            skip_existing=True,
                        )
                    )
                else:
                    tasks.append(
                        process_bitbucket_commit_from_webhook(
                            commit_data=commit_data,
                            repo_full_name=repo_full_name,
                            repo_name=repo_name,
                            repo_url=repo_url,
                            workspace_id=installation_id,
                            session=session,
                            skip_existing=True,
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
            
            last_commit_hash = ""
            if batch:
                if source_lower == "github":
                    last_commit_hash = batch[0].get("sha", "")
                else:
                    last_commit_hash = batch[0].get("hash", "")
            
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
            
            await asyncio.sleep(1)
        
        repo_status = await get_repository_status_ch(
            session,
            repo_full_name,
            installation_id,
        )
        current_status = repo_status.get("sync_status") if repo_status else None
        
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
