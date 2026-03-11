"""
ClickHouse commit processing logic using SQLAlchemy ORM.

This module provides SQLAlchemy ORM-based implementations of commit processing
functions, maintaining the same interface as the MongoDB version.
"""
import logging
import asyncio
from typing import Optional, Tuple
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func, text
from models.commits import Commit, SyncStatus
from models.ch_models import CommitCH, RepoSyncEventCH, PRMergeCH, BranchRawCH
from services.git_diff import fetch_diff_from_webhook, fetch_bitbucket_diff, count_diff_stats
# from services.ai_service import summarize_and_upload
# from services.background_worker import get_worker_manager
from services.kafka.kafka_store import get_kafka_producer

logger = logging.getLogger(__name__)

ZEP_COMMIT_LIMIT = 20


async def check_commit_exists_ch(
    session: Session,
    commit_hash: str,
    repo_name: str,
    installation_id: int,
) -> bool:
    """
    Check if a commit already exists in ClickHouse (idempotency check).
    
    Checks both CommitCH and PRMergeCH tables.
    
    Args:
        session: SQLAlchemy session
        commit_hash: Commit hash to check
        repo_name: Repository name
        installation_id: Installation ID
        
    Returns:
        True if commit exists in either CommitCH or PRMergeCH, False otherwise
    """
    try:
        # Check in CommitCH table
        commit_count = session.query(func.count(CommitCH.commit_hash)).filter(
            CommitCH.commit_hash == commit_hash,
            CommitCH.repository_name == repo_name,
            CommitCH.installation_id == installation_id,
        ).scalar()
        
        if commit_count > 0:
            return True
        
        # Check in PRMergeCH table
        pr_merge_count = session.query(func.count(PRMergeCH.merge_commit_hash)).filter(
            PRMergeCH.merge_commit_hash == commit_hash,
            PRMergeCH.repository_name == repo_name,
            PRMergeCH.installation_id == installation_id,
        ).scalar()
        
        return pr_merge_count > 0
    except Exception as e:
        logger.error(f"Error checking commit existence: {e}")
        return False


async def get_commit_by_hash_ch(
    session: Session,
    commit_hash: str,
    repo_name: str,
    installation_id: int,
) -> Optional[CommitCH]:
    """
    Query the commits table in ClickHouse to retrieve a commit by hash.
    
    Args:
        session: SQLAlchemy session
        commit_hash: Commit hash (12 characters)
        repo_name: Repository name
        installation_id: Installation ID
        
    Returns:
        CommitCH record if found, None otherwise
    """
    try:
        # Validate commit_hash is a string
        if not isinstance(commit_hash, str):
            logger.error(
                f"Invalid commit_hash type: expected str, got {type(commit_hash).__name__}. "
                f"Value: {commit_hash}"
            )
            return None
        
        commit = session.query(CommitCH).filter(
            CommitCH.commit_hash == commit_hash,
            CommitCH.repository_name == repo_name,
            CommitCH.installation_id == installation_id,
        ).first()
        
        return commit
    except Exception as e:
        logger.error(f"Error querying commit by hash {commit_hash}: {e}", exc_info=True)
        return None


async def insert_commit_ch(
    session: Session,
    commit: Commit,
) -> bool:
    """
    Insert a commit into ClickHouse using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        commit: Commit model to insert
        
    Returns:
        True if successful, False otherwise
    """
    try:
        commit_ch = CommitCH.from_pydantic(commit)
        session.add(commit_ch)
        session.commit()
        
        logger.debug(f"Inserted commit {commit.commit_hash} into ClickHouse")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error inserting commit into ClickHouse: {e}")
        return False


async def should_send_to_zep_ch(
    session: Session,
    repo_name: str,
    repo_full_name: str,
    installation_id: int,
    context: str = "webhook",
) -> Tuple[bool, bool]:
    """
    Check if we should send a commit to Zep based on repository status and 20-commit limit.
    
    SQLAlchemy ORM version of should_send_to_zep().
    
    Args:
        session: SQLAlchemy session
        repo_name: Repository name to check
        repo_full_name: Repository full name (owner/repo)
        installation_id: Installation/workspace ID
        context: Context of the call - "webhook" or "backfill"
    
    Returns:
        Tuple of (should_send: bool, marked_live: bool)
        - should_send: True if commit should be sent to Zep
        - marked_live: True if repository was just marked as LIVE (20th commit sent)
    """
    try:
        repo = session.query(RepoSyncEventCH).filter(
            RepoSyncEventCH.repository_full_name == repo_full_name,
            RepoSyncEventCH.installation_id == installation_id,
        ).first()
        
        current_status = repo.sync_status if repo else None
        
        if current_status == SyncStatus.LIVE.value and context == "backfill":
            logger.debug(
                f"Repository {repo_name} is LIVE, skipping Zep submission during backfill"
            )
            return False, False
        
        from models.ch_models import CommitAnalysisCH
        
        count = session.query(func.count(CommitAnalysisCH.commit_hash)).filter(
            CommitAnalysisCH.repo_name == repo_name,
        ).scalar()
        
        should_send = count < ZEP_COMMIT_LIMIT
        
        marked_live = False
        if should_send and count == ZEP_COMMIT_LIMIT - 1:
            try:
                if repo:
                    repo.sync_status = SyncStatus.LIVE.value
                    session.commit()
                    marked_live = True
                    logger.info(
                        f"Repository {repo_name} marked as LIVE after sending {ZEP_COMMIT_LIMIT} commits to Zep"
                    )
            except Exception as e:
                session.rollback()
                logger.warning(f"Failed to update repository status: {e}")
        
        if not should_send:
            logger.debug(
                f"Repository {repo_name} has reached Zep limit ({count}/{ZEP_COMMIT_LIMIT}), "
                "skipping Zep submission"
            )
        
        return should_send, marked_live
    except Exception as e:
        logger.error(f"Error checking Zep limit for {repo_name}: {e}")
        return True, False
    finally:
        session.close()


async def process_commit_ch(
    commit: Commit,
    session: Session,
    skip_existing: bool = True,
) -> Optional[Commit]:
    """
    Process and insert a commit into ClickHouse using SQLAlchemy ORM.
    
    This function:
    1. Checks if commit already exists (idempotency)
    2. Inserts commit into ClickHouse
    
    Args:
        commit: Commit model to process
        session: SQLAlchemy session
        skip_existing: If True, skip commits that already exist
        
    Returns:
        Commit model if successfully processed, None if skipped
    """
    try:
        if skip_existing:
            exists = await check_commit_exists_ch(
                session,
                commit.commit_hash,
                commit.repository_name,
                commit.installation_id or 0,
            )
            if exists:
                logger.debug(f"Commit {commit.commit_hash} already exists in ClickHouse, skipping")
                return None
        
        success = await insert_commit_ch(session, commit)
        if not success:
            return None
        
        return commit
        
    except Exception as e:
        logger.error(f"Error processing commit {commit.commit_hash}: {e}")
        return None
    finally:
        session.close()


async def update_branch_raw_from_commit(
    session: Session,
    email: str,
    repository_full_name: str,
    branch_name: str,
    commit_date: datetime,
    installation_id: int,
    commit_hash: Optional[str] = None,
) -> bool:
    """
    Insert or update BranchRawCH table with commit data.
    
    This function ensures a row exists in BranchRawCH for tracking purposes.
    Commit counts and last commit dates are calculated and stored in UserBranchAggregateCH
    via materialized views, not in BranchRawCH.
    
    Args:
        session: SQLAlchemy session
        email: Committer email
        repository_full_name: Repository full name (owner/repo)
        branch_name: Branch name
        commit_date: Commit date
        installation_id: Installation ID
        commit_hash: Optional commit hash (shortened, 12 chars)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Skip if branch_name or email is None or empty
        if not branch_name or not email:
            logger.debug(f"Skipping branch update: branch_name={branch_name}, email={email}")
            return False
        
        # Check if row exists
        existing = session.query(BranchRawCH).filter(
            BranchRawCH.repository_full_name == repository_full_name,
            BranchRawCH.branch_name == branch_name,
            BranchRawCH.email == email,
        ).first()
        
        if existing:
            # Row already exists - no need to update since commit_count and last_commit_date
            # are calculated in UserBranchAggregateCH via materialized views
            # Optionally update commit_date to latest value
            date_str = commit_date.strftime("%Y-%m-%d %H:%M:%S")
            repo_escaped = repository_full_name.replace("'", "''")
            branch_escaped = branch_name.replace("'", "''")
            email_escaped = email.replace("'", "''")
            
            update_sql = text(f"""
                ALTER TABLE branches_raw
                UPDATE 
                    commit_date = '{date_str}'
                WHERE 
                    repository_full_name = '{repo_escaped}'
                    AND branch_name = '{branch_escaped}'
                    AND email = '{email_escaped}'
            """)
            
            session.execute(update_sql)
            session.commit()
            
            logger.debug(
                f"Updated branch_raw commit date: {repository_full_name}/{branch_name} "
                f"for {email}"
            )
        else:
            # Insert new row
            branch_record = BranchRawCH(
                repository_full_name=repository_full_name,
                branch_name=branch_name,
                email=email,
                commit_date=commit_date,
                installation_id=installation_id,
                fetched_at=datetime.utcnow(),
            )
            session.add(branch_record)
            session.commit()
            
            logger.debug(
                f"Inserted new branch_raw: {repository_full_name}/{branch_name} "
                f"for {email}"
            )
        
        return True
        
    except Exception as e:
        session.rollback()
        logger.error(
            f"Error updating branch_raw for {repository_full_name}/{branch_name} "
            f"(email: {email}): {e}",
            exc_info=True
        )
        return False


async def process_commit_from_webhook(
    commit_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    installation_id: int,
    app_id: str,
    private_key_pem: str,
    session: Session,
    skip_existing: bool = True,
    branch_name: Optional[str] = None,
) -> Optional[Commit]:
    """
    Process a commit from a GitHub webhook event using ClickHouse.
    
    This function:
    1. Checks if commit already exists (idempotency)
    2. Fetches the diff from GitHub API
    3. Creates a Commit model
    4. Stores it in ClickHouse
    5. Triggers AI analysis asynchronously
    
    Args:
        commit_data: Commit data from webhook payload
        repo_full_name: Repository full name (owner/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        installation_id: GitHub installation ID
        app_id: GitHub App ID
        private_key_pem: GitHub App private key PEM content
        session: SQLAlchemy session
        skip_existing: If True, skip commits that already exist
    
    Returns:
        Commit model if successfully processed, None if skipped
    """
    try:
        full_commit_hash = commit_data["id"]
        commit_hash = full_commit_hash[:12]

        print("commit_hash===============: ", commit_hash)
        
        if skip_existing:
            exists = await check_commit_exists_ch(
                session,
                commit_hash,
                repo_name,
                installation_id,
            )
            print("exists===============: ", exists)
            if exists:
                logger.debug(f"Commit {commit_hash} already exists, skipping")
                return None
        
        commit_api_url = f"https://api.github.com/repos/{repo_full_name}/commits/{full_commit_hash}"
        
        try:
            print(f"[DEBUG] Fetching diff from GitHub API")
            diff_text = await fetch_diff_from_webhook(
                commit_api_url, installation_id, app_id, private_key_pem
            )
            
                
        except Exception as e:
            logger.warning(f"Failed to fetch diff for commit {commit_hash}: {e}")
            diff_text = ""
        
        timestamp_str = commit_data.get("timestamp")
        if timestamp_str:
            try:
                if timestamp_str.endswith("Z"):
                    timestamp_str = timestamp_str.replace("Z", "+00:00")
                commit_date = datetime.fromisoformat(timestamp_str)
            except (ValueError, AttributeError):
                logger.warning(f"Could not parse timestamp {timestamp_str}, using current time")
                commit_date = datetime.utcnow()
        else:
            commit_date = datetime.utcnow()
        changes = count_diff_stats(diff_text=diff_text) if diff_text else None
        commit_model = Commit(
            commit_hash=commit_hash,
            message=commit_data.get("message", ""),
            author=commit_data.get("author", {}).get("name", "Unknown"),
            email=commit_data.get("author", {}).get("email", ""),
            date=commit_date,
            repository_name=repo_name,
            repository_url=repo_url,
            installation_id=installation_id,
            # changes=count_diff_stats(diff_text=diff_text) if diff_text else None,
            changes=changes,
            branch_name=branch_name,
        )
        
        success = await insert_commit_ch(session, commit_model)
        if not success:
            return None
        
        should_send = True
        if should_send:
            kafka_producer = get_kafka_producer()
            await kafka_producer.add_task(
                [
                    diff_text, 
                    commit_model.author, 
                    commit_model.email, 
                    repo_name, 
                    commit_model.message, 
                    None, 
                    commit_hash, 
                    commit_date,
                    changes.get("additions"),
                    changes.get("deletions")
                ]
            )
            
                    
                    


                    
            
        
        
    except Exception as e:
        logger.error(f"Error processing commit {commit_data.get('id', 'unknown')}: {e}")
        return None


async def process_bitbucket_commit_from_webhook(
    commit_data: dict,
    repo_full_name: str,
    repo_name: str,
    repo_url: str,
    workspace_id: int,
    session: Session,
    skip_existing: bool = True,
    branch_name: Optional[str] = None,
) -> Optional[Commit]:
    """
    Process a Bitbucket commit from a webhook event using ClickHouse.
    
    This function:
    1. Checks if commit already exists (idempotency)
    2. Fetches the diff from Bitbucket API
    3. Creates a Commit model
    4. Stores it in ClickHouse
    5. Triggers AI analysis asynchronously
    
    Args:
        commit_data: Commit data from webhook payload
        repo_full_name: Repository full name (workspace/repo)
        repo_name: Repository name only
        repo_url: Repository HTML URL
        workspace_id: Bitbucket workspace identifier (used as installation_id equivalent)
        session: SQLAlchemy session
        skip_existing: If True, skip commits that already exist
        branch_name: Optional branch name for the commit
    
    Returns:
        Commit model if successfully processed, None if skipped
    """
    try:
        full_commit_hash = commit_data.get("hash", "")
        if not full_commit_hash:
            logger.warning("Commit missing hash field")
            return None
        
        commit_hash = full_commit_hash[:12]
        
        if skip_existing:
            exists = await check_commit_exists_ch(
                session,
                commit_hash,
                repo_name,
                workspace_id,
            )
            if exists:
                logger.debug(f"Commit {commit_hash} already exists, skipping")
                return None
        
        try:
            diff_text = await fetch_bitbucket_diff(
                repo_full_name=repo_full_name,
                commit_hash=full_commit_hash,
            )
            
                
        except Exception as e:
            logger.warning(f"Failed to fetch diff for commit {commit_hash}: {e}")
            diff_text = ""
        
        timestamp_str = commit_data.get("date")
        if timestamp_str:
            try:
                if timestamp_str.endswith("Z"):
                    timestamp_str = timestamp_str.replace("Z", "+00:00")
                elif "+" not in timestamp_str and "-" not in timestamp_str[-6:]:
                    timestamp_str = timestamp_str + "+00:00"
                commit_date = datetime.fromisoformat(timestamp_str)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse timestamp {timestamp_str}: {e}, using current time")
                commit_date = datetime.utcnow()
        else:
            commit_date = datetime.utcnow()
        
        author_info = commit_data.get("author", {})
        author_name = author_info.get("raw", "Unknown")
        author_email = ""
        
        if " <" in author_name and author_name.endswith(">"):
            parts = author_name.rsplit(" <", 1)
            author_name = parts[0]
            author_email = parts[1].rstrip(">")
        
        message = commit_data.get("message", "")
        if "\n" in message:
            message = message.split("\n")[0]
        changes = count_diff_stats(diff_text=diff_text) if diff_text else None
        commit_model = Commit(
            commit_hash=commit_hash,
            message=message,
            author=author_name,
            email=author_email,
            date=commit_date,
            repository_name=repo_name,
            repository_url=repo_url,
            installation_id=workspace_id,
            changes=changes,
            branch_name=branch_name,
        )
        
        success = await insert_commit_ch(session, commit_model)
        if not success:
            return None
        
        should_send = True
        if should_send:
            kafka_producer = get_kafka_producer()
            await kafka_producer.add_task(
                [
                    diff_text, 
                    commit_model.author, 
                    commit_model.email, 
                    repo_name, 
                    commit_model.message, 
                    None, 
                    commit_hash, 
                    commit_date,
                    changes.get("additions"),
                    changes.get("deletions")
                ]
            )
        
    except Exception as e:
        logger.error(f"Error processing Bitbucket commit {commit_data.get('hash', 'unknown')}: {e}", exc_info=True)
        return None