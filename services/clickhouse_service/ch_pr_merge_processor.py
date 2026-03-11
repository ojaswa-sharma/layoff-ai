import logging
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
import aiohttp
from models.commits import PRMerge
from models.ch_models import PRMergeCH
from services.clickhouse_service.ch_commit_processor import get_commit_by_hash_ch
from services.bitbucket_api import fetch_commit_by_hash
from services.git_diff import get_installation_token, GITHUB_API

logger = logging.getLogger(__name__)


def normalize_email(email: Optional[str]) -> Optional[str]:
    """
    Normalize email address to lowercase and remove spaces from username part.
    """
    if not email:
        return email
    
    email = email.strip()
    if not email:
        return email
    
    # Split email into username and domain
    if "@" in email:
        username, domain = email.rsplit("@", 1)
        # Remove spaces and convert to lowercase for username
        username = username.replace(" ", "").lower()
        # Convert domain to lowercase
        domain = domain.lower()
        return f"{username}@{domain}"
    else:
        # If no @ found, just lowercase and remove spaces
        return email.replace(" ", "").lower()


async def get_commit_author_email(
    session: Session,
    commit_hash: str,
    repo_full_name: str,
    repo_name: str,
    workspace_id: int,
) -> Optional[str]:
    """
    Get commit author email by trying database first, then Bitbucket API.
    
    Args:
        session: SQLAlchemy session
        commit_hash: Commit hash (12 characters or full hash)
        repo_full_name: Repository full name (workspace/repo)
        repo_name: Repository name only
        workspace_id: Workspace/installation ID
        
    Returns:
        Normalized author email if found, None otherwise
    """
    try:
        # Normalize commit hash to 12 characters for database lookup
        commit_hash_short = commit_hash[:12] if len(commit_hash) > 12 else commit_hash
        
        # First, try to get commit from database
        commit_ch = await get_commit_by_hash_ch(
            session=session,
            commit_hash=commit_hash_short,
            repo_name=repo_name,
            installation_id=workspace_id,
        )
        
        if commit_ch and commit_ch.email:
            logger.debug(f"Found commit {commit_hash_short} in database, email: {commit_ch.email}")
            return normalize_email(commit_ch.email)
        
        # If not found in database, fetch from Bitbucket API
        logger.debug(f"Commit {commit_hash_short} not found in database, fetching from Bitbucket API")
        commit_data = await fetch_commit_by_hash(
            repo_full_name=repo_full_name,
            commit_hash=commit_hash,
        )
        
        if not commit_data:
            logger.warning(f"Commit {commit_hash} not found in Bitbucket API")
            return None
        
        # Extract author email from Bitbucket commit data
        author_info = commit_data.get("author", {})
        author_raw = author_info.get("raw", "")
        author_email = ""
        
        # Parse author email from raw format: "Name <email@example.com>"
        if " <" in author_raw and author_raw.endswith(">"):
            parts = author_raw.rsplit(" <", 1)
            author_email = parts[1].rstrip(">")
        elif author_info.get("user", {}).get("email"):
            # Fallback to user email if available
            author_email = author_info.get("user", {}).get("email", "")
        
        if not author_email:
            logger.warning(f"Could not extract email from commit {commit_hash} author info")
            return None
        
        logger.debug(f"Extracted email from Bitbucket API for commit {commit_hash}: {author_email}")
        return normalize_email(author_email)
        
    except Exception as e:
        logger.error(f"Error getting commit author email for {commit_hash}: {e}", exc_info=True)
        return None


async def get_github_commit_author_email(
    session: Session,
    commit_hash: str,
    repo_full_name: str,
    repo_name: str,
    installation_id: int,
    app_id: str,
    private_key_pem: str,
) -> Optional[str]:
    """
    Get commit author email by trying database first, then GitHub API.
    
    Args:
        session: SQLAlchemy session
        commit_hash: Commit hash (12 characters or full hash)
        repo_full_name: Repository full name (owner/repo)
        repo_name: Repository name only
        installation_id: GitHub installation ID
        app_id: GitHub App ID
        private_key_pem: GitHub App private key PEM content
        
    Returns:
        Normalized author email if found, None otherwise
    """
    try:
        # Normalize commit hash to 12 characters for database lookup
        commit_hash_short = commit_hash[:12] if len(commit_hash) > 12 else commit_hash
        
        # First, try to get commit from database
        commit_ch = await get_commit_by_hash_ch(
            session=session,
            commit_hash=commit_hash_short,
            repo_name=repo_name,
            installation_id=installation_id,
        )
        
        if commit_ch and commit_ch.email:
            logger.debug(f"Found commit {commit_hash_short} in database, email: {commit_ch.email}")
            return normalize_email(commit_ch.email)
        
        # If not found in database, fetch from GitHub API
        logger.debug(f"Commit {commit_hash_short} not found in database, fetching from GitHub API")
        
        installation_token = await get_installation_token(
            app_id=app_id,
            private_key_pem=private_key_pem,
            installation_id=installation_id,
        )
        
        commit_url = f"{GITHUB_API}/repos/{repo_full_name}/commits/{commit_hash}"
        headers = {
            "Authorization": f"token {installation_token}",
            "Accept": "application/vnd.github+json",
            "User-Agent": "layoff-ai-app",
        }
        
        async with aiohttp.ClientSession(headers=headers) as client:
            async with client.get(commit_url) as response:
                if response.status == 404:
                    logger.warning(f"Commit {commit_hash} not found in GitHub API")
                    return None
                response.raise_for_status()
                commit_data = await response.json()
        
        # Extract author email from GitHub commit data
        # GitHub API returns email in commit.author.email or commit.commit.author.email
        author_email = None
        if commit_data.get("author") and commit_data["author"].get("email"):
            author_email = commit_data["author"]["email"]
        elif commit_data.get("commit", {}).get("author", {}).get("email"):
            author_email = commit_data["commit"]["author"]["email"]
        
        if not author_email:
            logger.warning(f"Could not extract email from commit {commit_hash} author info")
            return None
        
        logger.debug(f"Extracted email from GitHub API for commit {commit_hash}: {author_email}")
        return normalize_email(author_email)
        
    except Exception as e:
        logger.error(f"Error getting GitHub commit author email for {commit_hash}: {e}", exc_info=True)
        return None


async def check_pr_exists_ch(
    session: Session,
    repository_url: str,
    pr_number: int,
    installation_id: int,
) -> bool:
    """
    Check if a PR already exists in ClickHouse by (repository_url, pr_number, installation_id).        
    Returns:
        True if PR exists, False otherwise
    """
    try:
        count = session.query(func.count(PRMergeCH.pr_number)).filter(
            PRMergeCH.repository_url == repository_url,
            PRMergeCH.pr_number == pr_number,
            PRMergeCH.installation_id == installation_id,
        ).scalar()
        
        return count > 0
    except Exception as e:
        logger.error(f"Error checking PR existence: {e}")
        return False


async def upsert_pr_ch(
    session: Session,
    pr_merge: PRMerge,
) -> bool:
    """
    Upsert a PR into ClickHouse using SQLAlchemy ORM.       
    Returns:
        True if successful, False otherwise
    """
    try:
        pr_merge_ch = PRMergeCH.from_pydantic(pr_merge)
        session.add(pr_merge_ch)
        session.commit()
        
        logger.info(
            f"Upserted PR event in ClickHouse: PR #{pr_merge.pr_number} "
            f"status={pr_merge.status}"
        )
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error upserting PR into ClickHouse: {e}")
        return False


async def process_pr_ch(
    pr_merge: PRMerge,
    session: Session,
    skip_existing: bool = False,
) -> Optional[PRMerge]:
    """
    Process and upsert a PR into ClickHouse using SQLAlchemy ORM.
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        if skip_existing:
            exists = await check_pr_exists_ch(
                session,
                pr_merge.repository_url,
                pr_merge.pr_number,
                pr_merge.installation_id,
            )
            if exists:
                logger.debug(
                    f"PR #{pr_merge.pr_number} already exists in ClickHouse, skipping"
                )
                return None
        
        success = await upsert_pr_ch(session, pr_merge)
        
        if not success:
            return None
        
        return pr_merge
        
    except Exception as e:
        logger.error(
            f"Error processing PR {pr_merge.pr_number}: {e}",
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
    skip_existing: bool = False,
    app_id: Optional[str] = None,
    private_key_pem: Optional[str] = None,
) -> Optional[PRMerge]:
    """
    Process a GitHub PR event (opened, closed, merged) using ClickHouse.
    """
    try:
        print("pr func called for github")
        pr_number = pr_data.get("number")
        pr_title = pr_data.get("title", "")
        pr_state = pr_data.get("state", "open")  # "open", "closed"
        merged = pr_data.get("merged", False)
        
        if not pr_number:
            logger.warning("PR event missing PR number")
            return None
        
        # Determine status: "open", "closed", or "merged"
        if pr_state == "open":
            status = "open"
        elif merged:
            status = "merged"
        else:
            status = "closed"
        
        # Extract merge commit hash (only for merged PRs)
        merge_commit_hash = pr_data.get("merge_commit_sha")
        merge_commit_hash_short = merge_commit_hash[:12] if merge_commit_hash else None
        
        # Extract source commit hash from head to get author email
        head_info = pr_data.get("head", {})
        source_commit_hash = head_info.get("sha", "") if head_info else ""
        
        # Try to get commit author email from source commit
        created_by_email = None
        if source_commit_hash and app_id and private_key_pem:
            created_by_email = await get_github_commit_author_email(
                session=session,
                commit_hash=source_commit_hash,
                repo_full_name=repo_full_name,
                repo_name=repo_name,
                installation_id=installation_id,
                app_id=app_id,
                private_key_pem=private_key_pem,
            )
        
        # Fallback to PR author email if commit email not found
        if not created_by_email:
            user_info = pr_data.get("user", {})
            created_by_name = user_info.get("login", "Unknown") if user_info else "Unknown"
            created_by_email = user_info.get("email", "") if user_info else ""
            
            # Normalize email: lowercase and remove spaces
            created_by_email = normalize_email(created_by_email) if created_by_email else None
        else:
            # Extract created_by name from PR author (email already normalized by helper function)
            user_info = pr_data.get("user", {})
            created_by_name = user_info.get("login", "Unknown") if user_info else "Unknown"
        
        if not created_by_email:
            created_by_email = "Unknown"
        
        # Extract merged_by info (only for merged PRs)
        merged_by_info = pr_data.get("merged_by", {})
        merged_by_name = merged_by_info.get("login") if merged_by_info else None
        merged_by_email = merged_by_info.get("email") if merged_by_info else None
        
        # Normalize merged_by email if present (no fake email generation)
        if merged_by_email:
            merged_by_email = normalize_email(merged_by_email)
        else:
            merged_by_email = None
        
        # Extract branch name (head_info already extracted above)
        branch = head_info.get("ref") if head_info else None
        
        # Extract additions and deletions
        additions = pr_data.get("additions")
        deletions = pr_data.get("deletions")
        
        # Extract dates
        created_at_str = pr_data.get("created_at")
        updated_at_str = pr_data.get("updated_at")
        merged_at_str = pr_data.get("merged_at")
        
        # Parse dates
        def parse_date(date_str: str) -> datetime:
            if not date_str:
                return datetime.utcnow()
            try:
                if date_str.endswith("Z"):
                    date_str = date_str.replace("Z", "+00:00")
                return datetime.fromisoformat(date_str)
            except (ValueError, AttributeError):
                logger.warning(f"Could not parse date {date_str}, using current time")
                return datetime.utcnow()
        
        # Use merged_at for merged PRs, created_at for opened, updated_at for closed
        if merged_at_str:
            date = parse_date(merged_at_str)
        elif created_at_str:
            date = parse_date(created_at_str)
        else:
            date = datetime.utcnow()
        
        updated_at = parse_date(updated_at_str) if updated_at_str else date
        
        pr_merge_model = PRMerge(
            pr_number=pr_number,
            pr_title=pr_title,
            status=status,
            created_by=created_by_name,
            created_by_email=created_by_email,
            repository_name=repo_name,
            repository_url=repo_url,
            date=date,
            updated_at=updated_at,
            installation_id=installation_id,
            source="github",
            merge_commit_hash=merge_commit_hash_short,
            merged_by=merged_by_name,
            merged_by_email=merged_by_email,
            branch=branch,
            additions=additions,
            deletions=deletions,
        )

        print("pr_merge_model for github ===============: ", pr_merge_model)
        
        result = await process_pr_ch(
            pr_merge_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing GitHub PR {pr_data.get('number', 'unknown')}: {e}", exc_info=True)
        return None


async def process_bitbucket_pr_merge(
    pr_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    workspace_id: int,
    session: Session,
    skip_existing: bool = False,
) -> Optional[PRMerge]:
    """
    Process a Bitbucket PR event (created, updated, fulfilled, rejected) using ClickHouse.
    Returns:
        PRMerge model if successfully processed, None if skipped
    """
    try:
        pr_number = pr_data.get("id")
        pr_title = pr_data.get("title", "")
        
        if not pr_number:
            logger.warning("PR event missing PR ID")
            return None
        
        # Extract PR state and map to our status values
        pr_state = pr_data.get("state", "").upper()  # Bitbucket uses uppercase: "OPEN", "MERGED", "DECLINED", "SUPERSEDED"
        
        # Map Bitbucket states to our status values
        if pr_state == "OPEN":
            status = "open"
        elif pr_state == "MERGED":
            status = "merged"
        elif pr_state in ["DECLINED", "SUPERSEDED"]:
            status = "closed"
        else:
            # Default to open if state is unknown
            logger.warning(f"Unknown PR state '{pr_state}' for PR #{pr_number}, defaulting to 'open'")
            status = "open"
        
        # Extract merge commit hash (only for merged PRs)
        merge_commit_info = pr_data.get("merge_commit")
        if not merge_commit_info:
            merge_commit_info = pr_data.get("destination", {}).get("commit", {})
        
        merge_commit_hash = merge_commit_info.get("hash", "") if merge_commit_info else ""
        merge_commit_hash_short = merge_commit_hash[:12] if merge_commit_hash else None
        
        # Extract source commit hash to get author email
        source_info = pr_data.get("source", {})
        source_commit_info = source_info.get("commit", {}) if source_info else {}
        # Handle both dict (commit object) and string (hash) cases
        if isinstance(source_commit_info, dict):
            source_commit_hash = source_commit_info.get("hash", "")
        else:
            source_commit_hash = str(source_commit_info) if source_commit_info else ""
        
        # Try to get commit author email from source commit
        created_by_email = None
        if source_commit_hash:
            created_by_email = await get_commit_author_email(
                session=session,
                commit_hash=source_commit_hash,
                repo_full_name=repo_full_name,
                repo_name=repo_name,
                workspace_id=workspace_id,
            )
        
        # Fallback to PR author email if commit email not found
        if not created_by_email:
            author_info = pr_data.get("author", {})
            created_by_name = author_info.get("display_name", "Unknown") if author_info else "Unknown"
            created_by_email = author_info.get("email", "") if author_info else ""
            
            if not created_by_email and "raw" in author_info:
                raw_author = author_info.get("raw", "")
                if " <" in raw_author and raw_author.endswith(">"):
                    parts = raw_author.rsplit(" <", 1)
                    created_by_name = parts[0]
                    created_by_email = parts[1].rstrip(">")
            
            # Normalize email: lowercase and remove spaces (no fake email generation)
            created_by_email = normalize_email(created_by_email) if created_by_email else None
        else:
            # Extract created_by name from PR author (email already normalized by helper function)
            author_info = pr_data.get("author", {})
            created_by_name = author_info.get("display_name", "Unknown") if author_info else "Unknown"
        
        # Extract merged_by info (only for merged PRs)
        merged_by_name = None
        merged_by_email = None
        
        if status == "merged":
            # Check if there's separate merge information
            merge_info = pr_data.get("merge_commit", {}).get("author", {}) if pr_data.get("merge_commit") else {}
            if merge_info:
                merged_by_name = merge_info.get("display_name", created_by_name)
                merged_by_email = merge_info.get("email", created_by_email)
            else:
                # Default to author if no merge info
                merged_by_name = created_by_name
                merged_by_email = created_by_email
        
        # Normalize merged_by email if present
        if merged_by_email:
            merged_by_email = normalize_email(merged_by_email)
        
        # Extract branch name (source_info already extracted above, reuse it)
        branch_info = source_info.get("branch", {}) if source_info else {}
        branch = branch_info.get("name") if branch_info else None
        
        # Extract additions and deletions (may not be available in webhook payload)
        # Bitbucket webhook may not include diff stats, so these will be None
        additions = pr_data.get("summary", {}).get("additions") if pr_data.get("summary") else None
        deletions = pr_data.get("summary", {}).get("deletions") if pr_data.get("summary") else None
        
        # Extract dates
        created_at_str = pr_data.get("created_on")
        updated_at_str = pr_data.get("updated_on")
        closed_date_str = pr_data.get("closed_date")
        
        # Parse dates
        def parse_date(date_str: str) -> datetime:
            if not date_str:
                return datetime.utcnow()
            try:
                if date_str.endswith("Z"):
                    date_str = date_str.replace("Z", "+00:00")
                elif "+" not in date_str and "-" not in date_str[-6:]:
                    date_str = date_str + "+00:00"
                return datetime.fromisoformat(date_str)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse date {date_str}: {e}, using current time")
                return datetime.utcnow()
        
        # Use closed_date for closed/merged PRs, created_on for opened
        if closed_date_str:
            date = parse_date(closed_date_str)
        elif created_at_str:
            date = parse_date(created_at_str)
        else:
            date = datetime.utcnow()
        
        updated_at = parse_date(updated_at_str) if updated_at_str else date
        
        pr_merge_model = PRMerge(
            pr_number=pr_number,
            pr_title=pr_title,
            status=status,
            created_by=created_by_name,
            created_by_email=created_by_email,
            repository_name=repo_name,
            repository_url=repo_url,
            date=date,
            updated_at=updated_at,
            installation_id=workspace_id,
            source="bitbucket",
            merge_commit_hash=merge_commit_hash_short,
            merged_by=merged_by_name,
            merged_by_email=merged_by_email,
            branch=branch,
            additions=additions,
            deletions=deletions,
        )
        
        result = await process_pr_ch(
            pr_merge_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing Bitbucket PR {pr_data.get('id', 'unknown')}: {e}", exc_info=True)
        return None
