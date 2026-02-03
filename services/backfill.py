"""
Historical commit backfill service for GitHub App installations.

This module handles fetching and processing historical commits when a GitHub App
is installed on a repository. It supports pagination, rate limiting, and
graceful error handling.
"""
import aiohttp
import asyncio
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime, timedelta
from services.git_diff import get_installation_token, fetch_diff_from_webhook, count_diff_stats
from models.commits import Commit, SyncStatus
from services.ai_service import summarize_and_upload

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
MAX_COMMITS_PER_PAGE = 100  # GitHub API max
MAX_DIFF_SIZE = 1_000_000  # 1MB limit for diff processing
MAX_COMMITS_DEFAULT = 1000  # Default limit for backfill
MAX_BACKFILL_DAYS = 365  # Default: 1 year of history


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
    """
    for attempt in range(max_retries):
        try:
            async with session.get(url, headers=headers) as resp:
                # Handle rate limiting
                if resp.status == 429:
                    retry_after = int(resp.headers.get("Retry-After", base_delay * (2 ** attempt)))
                    logger.warning(
                        f"Rate limited. Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})"
                    )
                    await asyncio.sleep(retry_after)
                    continue
                
                # Handle server errors
                if resp.status >= 500:
                    if attempt < max_retries - 1:
                        delay = base_delay * (2 ** attempt)
                        logger.warning(
                            f"Server error {resp.status}. Retrying after {delay}s (attempt {attempt + 1}/{max_retries})"
                        )
                        await asyncio.sleep(delay)
                        continue
                
                # For other errors, return immediately
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
            
            if resp.status == 404:
                logger.warning(f"Repository {repo_full_name} not found or no access")
                break
            
            if resp.status != 200:
                error_body = await resp.text()
                raise RuntimeError(
                    f"Failed to fetch commits: {resp.status} - {error_body}"
                )
            
            commits = await resp.json()
            
            if not commits:
                break
            
            all_commits.extend(commits)
            
            # Check if we've hit the max commits limit
            if max_commits and len(all_commits) >= max_commits:
                all_commits = all_commits[:max_commits]
                break
            
            # Check if there are more pages
            link_header = resp.headers.get("Link", "")
            if 'rel="next"' not in link_header:
                break
            
            page += 1
            
            # Rate limiting: small delay between pages
            await asyncio.sleep(0.5)
    
    logger.info(f"Fetched {len(all_commits)} commits from {repo_full_name}")
    return all_commits


async def process_commit(
    commit_data: Dict[str, Any],
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    installation_token: str,
    app_id: str,
    private_key_pem: str,
    mongo_db,
    skip_existing: bool = True,
) -> Optional[Commit]:
    """
    Process a single commit: fetch diff, create Commit model, store in DB.
    
    Returns the Commit model if successfully processed, None if skipped.
    """
    try:
        full_commit_hash = commit_data["sha"]
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
        
        # Fetch commit details to get full metadata
        commit_api_url = f"{GITHUB_API}/repos/{repo_full_name}/commits/{full_commit_hash}"
        
        # Fetch diff
        try:
            diff_text = await fetch_diff_from_webhook(
                commit_api_url, installation_id, app_id, private_key_pem
            )
            
            # Skip if diff is too large (likely binary or very large file)
            if len(diff_text) > MAX_DIFF_SIZE:
                logger.warning(
                    f"Commit {commit_hash} has diff > {MAX_DIFF_SIZE} bytes, skipping"
                )
                return None
                
        except Exception as e:
            logger.warning(f"Failed to fetch diff for commit {commit_hash}: {e}")
            # Continue with empty diff
            diff_text = ""
        
        # Extract commit metadata
        commit_info = commit_data.get("commit", {})
        author_info = commit_info.get("author", {})
        
        commit_model = Commit(
            commit_hash=commit_hash,
            message=commit_info.get("message", ""),
            author=author_info.get("name", "Unknown"),
            email=author_info.get("email", ""),
            date=datetime.fromisoformat(
                author_info.get("date", datetime.utcnow().isoformat()).replace("Z", "+00:00")
            ),
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
        logger.error(f"Error processing commit {commit_data.get('sha', 'unknown')}: {e}")
        return None


async def backfill_repository(
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    app_id: str,
    private_key_pem: str,
    mongo_db,
    max_commits: Optional[int] = None,
    max_days: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Backfill historical commits for a repository.
    
    Args:
        repo_full_name: Repository full name (owner/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        installation_id: GitHub installation ID
        app_id: GitHub App ID
        private_key_pem: GitHub App private key PEM content
        mongo_db: MongoDB database instance
        max_commits: Maximum number of commits to fetch (None = use default)
        max_days: Maximum days of history to fetch (None = use default)
    
    Returns:
        Dictionary with backfill statistics
    """
    logger.info(f"Starting backfill for repository: {repo_full_name}")
    
    # Update repository status to BACKFILLING
    mongo_db.repositories.update_one(
        {
            "repository_full_name": repo_full_name,
            "installation_id": installation_id,
        },
        {
            "$set": {
                "sync_status": SyncStatus.BACKFILLING.value,
                "backfill_started_at": datetime.utcnow(),
                "error_message": None,
            },
        },
        upsert=True,
    )
    
    try:
        # Get installation token
        installation_token = await get_installation_token(
            app_id=app_id,
            private_key_pem=private_key_pem,
            installation_id=installation_id,
        )
        
        # Calculate date cutoff if max_days is specified
        since = None
        if max_days:
            since = datetime.utcnow() - timedelta(days=max_days)
        
        # Fetch commits
        commits_data = await fetch_repository_commits(
            repo_full_name=repo_full_name,
            installation_token=installation_token,
            since=since,
            max_commits=max_commits or MAX_COMMITS_DEFAULT,
        )
        
        if not commits_data:
            logger.info(f"No commits found for {repo_full_name}")
            mongo_db.repositories.update_one(
                {
                    "repository_full_name": repo_full_name,
                    "installation_id": installation_id,
                },
                {
                    "$set": {
                        "sync_status": SyncStatus.LIVE.value,
                        "backfill_completed_at": datetime.utcnow(),
                        "total_commits_backfilled": 0,
                    },
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
            tasks = [
                process_commit(
                    commit_data=commit,
                    repo_full_name=repo_full_name,
                    repo_name=repo_name,
                    repo_url=repo_url,
                    installation_id=installation_id,
                    installation_token=installation_token,
                    app_id=app_id,
                    private_key_pem=private_key_pem,
                    mongo_db=mongo_db,
                    skip_existing=True,
                )
                for commit in batch
            ]
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Error in batch processing: {result}")
                    skipped_count += 1
                elif result is None:
                    skipped_count += 1
                else:
                    processed_count += 1
            
            # Update progress
            mongo_db.repositories.update_one(
                {
                    "repository_full_name": repo_full_name,
                    "installation_id": installation_id,
                },
                {
                    "$set": {
                        "total_commits_backfilled": processed_count,
                        "last_commit_processed": batch[0]["sha"] if batch else None,
                    },
                },
            )
            
            logger.info(
                f"Backfill progress for {repo_full_name}: "
                f"{processed_count} processed, {skipped_count} skipped"
            )
            
            # Small delay between batches to respect rate limits
            await asyncio.sleep(1)
        
        # Update repository status to LIVE
        mongo_db.repositories.update_one(
            {
                "repository_full_name": repo_full_name,
                "installation_id": installation_id,
            },
            {
                "$set": {
                    "sync_status": SyncStatus.LIVE.value,
                    "backfill_completed_at": datetime.utcnow(),
                    "total_commits_backfilled": processed_count,
                },
            },
        )
        
        logger.info(
            f"Backfill completed for {repo_full_name}: "
            f"{processed_count} processed, {skipped_count} skipped"
        )
        
        return {
            "status": "completed",
            "total_commits": len(commits_data),
            "processed_commits": processed_count,
            "skipped_commits": skipped_count,
        }
        
    except Exception as e:
        logger.error(f"Backfill failed for {repo_full_name}: {e}")
        
        # Update repository status to FAILED
        mongo_db.repositories.update_one(
            {
                "repository_full_name": repo_full_name,
                "installation_id": installation_id,
            },
            {
                "$set": {
                    "sync_status": SyncStatus.FAILED.value,
                    "error_message": str(e),
                },
            },
        )
        
        raise

