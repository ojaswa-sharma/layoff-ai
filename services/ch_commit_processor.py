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
from sqlalchemy import func
from models.commits import Commit, SyncStatus
from models.ch_models import CommitCH, RepoSyncEventCH
from services.git_diff import fetch_diff_from_webhook, fetch_bitbucket_diff, count_diff_stats
from services.ai_service import summarize_and_upload
from services.ch_ai_service import insert_commit_analysis_ch

logger = logging.getLogger(__name__)

ZEP_COMMIT_LIMIT = 20  # Maximum number of commits to send to Zep per repository
# MAX_DIFF_SIZE = 1_000_000  # 1MB limit for diff processing


async def check_commit_exists_ch(
    session: Session,
    commit_hash: str,
    repo_name: str,
    installation_id: int,
) -> bool:
    """
    Check if a commit already exists in ClickHouse (idempotency check).
    
    Args:
        session: SQLAlchemy session
        commit_hash: Commit hash to check
        repo_name: Repository name
        installation_id: Installation ID
        
    Returns:
        True if commit exists, False otherwise
    """
    try:
        count = session.query(func.count(CommitCH.commit_hash)).filter(
            CommitCH.commit_hash == commit_hash,
            CommitCH.repository_name == repo_name,
            CommitCH.installation_id == installation_id,
        ).scalar()
        
        return count > 0
    except Exception as e:
        logger.error(f"Error checking commit existence: {e}")
        return False


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
    context: str = "webhook",  # "webhook" or "backfill"
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
        # Fetch repository status from ClickHouse
        repo = session.query(RepoSyncEventCH).filter(
            RepoSyncEventCH.repository_full_name == repo_full_name,
            RepoSyncEventCH.installation_id == installation_id,
        ).first()
        
        current_status = repo.sync_status if repo else None
        
        # If status is LIVE and called from backfill context, skip Zep
        if current_status == SyncStatus.LIVE.value and context == "backfill":
            logger.debug(
                f"Repository {repo_name} is LIVE, skipping Zep submission during backfill"
            )
            return False, False
        
        # Count commits that have been sent to Zep (exist in commit_analysis table)
        from models.ch_models import CommitAnalysisCH
        
        count = session.query(func.count(CommitAnalysisCH.commit_hash)).filter(
            CommitAnalysisCH.repo_name == repo_name,
        ).scalar()
        
        should_send = count < ZEP_COMMIT_LIMIT
        
        # If we're about to send the 20th commit, mark repository as LIVE
        marked_live = False
        if should_send and count == ZEP_COMMIT_LIMIT - 1:
            # This will be the 20th commit, mark repository as LIVE
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
        # On error, default to allowing submission to avoid blocking commits
        return True, False


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
        # Check if commit already exists (idempotency)
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
        
        # Insert into ClickHouse
        success = await insert_commit_ch(session, commit)
        if not success:
            return None
        
        return commit
        
    except Exception as e:
        logger.error(f"Error processing commit {commit.commit_hash}: {e}")
        return None


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
        
        # Check if commit already exists (idempotency)
        if skip_existing:
            exists = await check_commit_exists_ch(
                session,
                commit_hash,
                repo_name,
                installation_id,
            )
            if exists:
                logger.debug(f"Commit {commit_hash} already exists, skipping")
                return None
        
        # Fetch diff from GitHub API
        commit_api_url = f"https://api.github.com/repos/{repo_full_name}/commits/{full_commit_hash}"
        
        try:
            print(f"[DEBUG] Fetching diff from GitHub API")
            diff_text = await fetch_diff_from_webhook(
                commit_api_url, installation_id, app_id, private_key_pem
            )
            
            # Skip if diff is too large
            # if len(diff_text) > MAX_DIFF_SIZE:
            #     logger.warning(
            #         f"Commit {commit_hash} has diff > {MAX_DIFF_SIZE} bytes, skipping"
            #     )
            #     return None
                
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
            # diff=diff_text,
            installation_id=installation_id,
            changes=count_diff_stats(diff_text=diff_text) if diff_text else None,
        )
        
        # Store in ClickHouse
        success = await insert_commit_ch(session, commit_model)
        if not success:
            return None
        
        # Trigger AI analysis asynchronously only if we haven't reached the Zep limit
        should_send= True
        asyncio.create_task(summarize_and_upload(diff_text, commit_model.author, commit_model.email, repo_name, commit_model.message, session, commit_hash, commit_date))
            # Create a new session for the async task since the current one will be closed            
#             async def analyze_and_store():
#                 ch_session = SessionLocal()
#                 try:
#                     # Call the AI summarization (this doesn't need DB)
#                     from services.ai_service import summarie_diff, get_openai
#                     diff = await summarie_diff(
#                         get_openai(), diff_text, commit_model.author, 
#                         commit_model.email, repo_name, commit_model.message
#                     )
                    
#                     # Add metadata
#                     diff["mail"] = commit_model.email
#                     diff["repo_name"] = repo_name
#                     diff["commit_hash"] = commit_hash
                    
#                     # Send to Zep
#                     zep = get_personalizer()
#                     msg = botMessage(role="norole", content=f"""
# Repository: {repo_name}
# Developer: {commit_model.author}
# Commit hash : {commit_hash}

# Commit Summary:
# {diff.get("commit_summmary")}

# Performance Assessment:
# {diff.get("commiters_performance")}
# """)
                    
#                     # Store in ClickHouse and send to Zep
#                     await asyncio.gather(
#                         zep.add_message(
#                             user_id=f"user_{commit_model.email}",
#                             message=msg,
#                             thread_id=repo_name,
#                             first_name=commit_model.author,
#                             email=commit_model.email,
#                             repo_name=repo_name
#                         ),
#                         insert_commit_analysis_ch(
#                             ch_session,
#                             diff,
#                             commit_hash=commit_hash,
#                             email=commit_model.email,
#                             repo_name=repo_name,
#                         ),
#                         zep.add_to_graph(
#                             graph_id=f"{commit_model.email}_{repo_name}",
#                             message=msg.content
#                         )
#                     )
#                 finally:
#                     ch_session.close()
            
        #     asyncio.create_task(analyze_and_store())
        # else:
        #     logger.info(
        #         f"Commit {commit_hash} for repository {repo_name} stored in database but skipped Zep submission "
        #         f"(limit of {ZEP_COMMIT_LIMIT} commits reached or repository is LIVE)"
        #     )
        
        # return commit_model
        
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
    
    Returns:
        Commit model if successfully processed, None if skipped
    """
    try:
        # Bitbucket commit hash is in 'hash' field
        full_commit_hash = commit_data.get("hash", "")
        if not full_commit_hash:
            logger.warning("Commit missing hash field")
            return None
        
        commit_hash = full_commit_hash[:12]
        
        # Check if commit already exists (idempotency)
        # Use workspace_id as installation_id equivalent for Bitbucket
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
        
        # Fetch diff from Bitbucket API
        try:
            diff_text = await fetch_bitbucket_diff(
                repo_full_name=repo_full_name,
                commit_hash=full_commit_hash,
            )
            
            # Skip if diff is too large
            # if len(diff_text) > MAX_DIFF_SIZE:
            #     logger.warning(
            #         f"Commit {commit_hash} has diff > {MAX_DIFF_SIZE} bytes, skipping"
            #     )
            #     return None
                
        except Exception as e:
            logger.warning(f"Failed to fetch diff for commit {commit_hash}: {e}")
            # Continue with empty diff
            diff_text = ""
        
        # Parse date from webhook timestamp
        # Bitbucket uses 'date' field in ISO format
        timestamp_str = commit_data.get("date")
        if timestamp_str:
            try:
                if timestamp_str.endswith("Z"):
                    timestamp_str = timestamp_str.replace("Z", "+00:00")
                elif "+" not in timestamp_str and "-" not in timestamp_str[-6:]:
                    # If no timezone, assume UTC
                    timestamp_str = timestamp_str + "+00:00"
                commit_date = datetime.fromisoformat(timestamp_str)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse timestamp {timestamp_str}: {e}, using current time")
                commit_date = datetime.utcnow()
        else:
            commit_date = datetime.utcnow()
        
        # Extract author info from Bitbucket format
        author_info = commit_data.get("author", {})
        author_name = author_info.get("raw", "Unknown")
        author_email = ""
        
        # Bitbucket author.raw format: "Name <email@example.com>"
        if " <" in author_name and author_name.endswith(">"):
            parts = author_name.rsplit(" <", 1)
            author_name = parts[0]
            author_email = parts[1].rstrip(">")
        
        # Get commit message
        message = commit_data.get("message", "")
        # Bitbucket messages may have multiple lines, take first line as summary
        if "\n" in message:
            message = message.split("\n")[0]
        
        # Create Commit model from webhook data
        # Use workspace_id as installation_id for Bitbucket
        commit_model = Commit(
            commit_hash=commit_hash,
            message=message,
            author=author_name,
            email=author_email,
            date=commit_date,
            repository_name=repo_name,
            repository_url=repo_url,
            # diff=diff_text,
            installation_id=workspace_id,
            changes=count_diff_stats(diff_text=diff_text) if diff_text else None,
        )
        
        # Store in ClickHouse
        success = await insert_commit_ch(session, commit_model)
        if not success:
            return None
        
        # Trigger AI analysis asynchronously only if we haven't reached the Zep limit
        should_send, marked_live = await should_send_to_zep_ch(
            session, repo_name, repo_full_name, workspace_id, context="webhook"
        )
        if should_send:
            # Create a new session for the async task since the current one will be closed
            from dependencies.ch_db import SessionLocal
            from services.zep_store import get_personalizer, botMessage
            
            async def analyze_and_store():
                ch_session = SessionLocal()
                try:
                    # Call the AI summarization (this doesn't need DB)
                    from services.ai_service import summarie_diff, get_openai
                    diff = await summarie_diff(
                        get_openai(), diff_text, commit_model.author, 
                        commit_model.email, repo_name, commit_model.message
                    )
                    
                    # Add metadata
                    diff["mail"] = commit_model.email
                    diff["repo_name"] = repo_name
                    diff["commit_hash"] = commit_hash
                    
                    # Send to Zep
                    zep = get_personalizer()
                    msg = botMessage(role="norole", content=f"""
Repository: {repo_name}
Developer: {commit_model.author}
Commit hash : {commit_hash}

Commit Summary:
{diff.get("commit_summmary")}

Performance Assessment:
{diff.get("commiters_performance")}
""")
                    
                    # Store in ClickHouse and send to Zep
                    await asyncio.gather(
                        zep.add_message(
                            user_id=f"user_{commit_model.email}",
                            message=msg,
                            thread_id=repo_name,
                            first_name=commit_model.author,
                            email=commit_model.email,
                            repo_name=repo_name
                        ),
                        insert_commit_analysis_ch(
                            ch_session,
                            diff,
                            commit_hash=commit_hash,
                            email=commit_model.email,
                            repo_name=repo_name,
                        ),
                        zep.add_to_graph(
                            graph_id=f"{commit_model.email}_{repo_name}",
                            message=msg.content
                        )
                    )
                finally:
                    ch_session.close()
            
            asyncio.create_task(analyze_and_store())
        else:
            logger.info(
                f"Commit {commit_hash} for repository {repo_name} stored in database but skipped Zep submission "
                f"(limit of {ZEP_COMMIT_LIMIT} commits reached or repository is LIVE)"
            )
        
        return commit_model
        
    except Exception as e:
        logger.error(f"Error processing Bitbucket commit {commit_data.get('hash', 'unknown')}: {e}", exc_info=True)
        return None
