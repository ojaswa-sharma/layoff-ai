"""
Bitbucket webhook router handling push events and repository setup.

This router processes:
- Push events: Real-time commit processing via webhooks
- Repository setup: Triggers historical backfill when repository is first connected
"""
from fastapi import APIRouter, Request, Depends, HTTPException
import os
import asyncio
from sqlalchemy.orm import Session
from models.commits import SyncStatus
from services.ch_commit_processor import process_bitbucket_commit_from_webhook
from services.ch_pr_merge_processor import process_bitbucket_pr_merge
from services.ch_backfill import get_repository_status_ch, update_repository_status_ch
from dependencies.ch_db import get_ch_session, SessionLocal
import logging
from datetime import datetime
import hashlib

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/bitbucket")

BACKFILL_MAX_COMMITS = int(os.getenv("BACKFILL_MAX_COMMITS", "100"))


@router.get('/test-token')
async def test_token():
    """Test endpoint to verify Bitbucket OAuth token retrieval."""
    try:
        from services.bitbucket_api import fetch_diff
        diff = await fetch_diff(
            "https://api.bitbucket.org/2.0/repositories/dpkgusain/test-repo-1/diff/6a9dbe2fba2d5b4cc6339e7a527a214ea9ef2d13..0f7a3c3e6b728df710d97e9073af7f4c206ab5f2"
        )
        print(diff)

        return {
            "success": True,
            "diff": diff
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "error_type": type(e).__name__
        }


@router.post('/webhook')
async def webhook_bitbucket(request: Request, session: Session = Depends(get_ch_session)):
    """
    Handle Bitbucket webhook events.
    
    Supports:
    - repo:push: Process commits from push events (real-time)
    - pullrequest:fulfilled: Process PR merge events (separate from commits)
    """
    try:
        # Get Bitbucket event type from headers
        event_type = request.headers.get("X-Event-Key", "repo:push")
        print(f"[EVENT] EVENT TYPE : {event_type}")
        
        request_data = await request.json()
        
        # Handle pull request fulfilled events (PR merges)
        if event_type == "pullrequest:fulfilled":
            return await handle_pullrequest_fulfilled_event(request_data, session)
        
        # Handle push events
        if event_type == "repo:push":
            print("PUSHED")
            # return await handle_push_event(request_data, mongo)
            return await handle_push_event(request_data, session)
        
        # Ignore other event types
        return {
            "message": f"Event type '{event_type}' not processed",
            "event_type": event_type,
        }
        
    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


async def handle_pullrequest_fulfilled_event(request_data: dict, session: Session):
    """
    Handle pullrequest:fulfilled webhook events - process PR merges separately from commits.
    
    PR merges are stored in pr_merges collection without diff/changes tracking.
    """
    # Extract repository information from Bitbucket webhook payload
    repository = request_data.get("repository", {})
    repo_full_name = repository.get("full_name", "")  # workspace/repo
    repo_name = repository.get("name", "")
    repo_url = repository.get("links", {}).get("html", {}).get("href", "")
    
    # Extract workspace information
    workspace = repository.get("workspace", {})
    workspace_slug = workspace.get("slug", "") or workspace.get("uuid", "")
    
    if not repo_full_name or not workspace_slug:
        logger.error("Missing repository or workspace info in PR merge webhook payload")
        raise HTTPException(status_code=400, detail="Missing repository or workspace information")
    
    # Convert workspace slug to integer for installation_id field (hash-based)
    workspace_id = int(hashlib.md5(workspace_slug.encode()).hexdigest()[:8], 16)
    
    # Extract PR data from webhook payload
    pr_data = request_data.get("pullrequest", {})
    
    if not pr_data:
        logger.warning("PR merge webhook missing pullrequest data")
        return {
            "message": "PR merge webhook missing pullrequest data",
            "event_type": "pullrequest:fulfilled",
        }
    
    result = await process_bitbucket_pr_merge(
        pr_data=pr_data,
        repo_full_name=repo_full_name,
        repo_name=repo_name,
        repo_url=repo_url,
        workspace_id=workspace_id,
        session=session,
        skip_existing=True,  # Idempotency: skip existing PR merges
    )
    
    if result is None:
        return {
            "message": "PR merge already exists or failed to process",
            "event_type": "pullrequest:fulfilled",
            "pr_number": pr_data.get("id"),
        }
    
    return {
        "message": "PR merge processed successfully",
        "event_type": "pullrequest:fulfilled",
        "pr_number": pr_data.get("id"),
        "merged_by": result.merged_by,
    }


async def handle_push_event(request_data: dict, session: Session):
    """
    Handle push webhook events - process commits in real-time.
    
    This maintains similar behavior to GitHub webhook handling:
    - Idempotency checks
    - Lazy backfill triggering for repositories not yet synced
    """
    # Extract repository information from Bitbucket webhook payload
    repository = request_data.get("repository", {})
    repo_full_name = repository.get("full_name", "")  # workspace/repo
    repo_name = repository.get("name", "")
    repo_url = repository.get("links", {}).get("html", {}).get("href", "")
    
    # Extract workspace information
    workspace = repository.get("workspace", {})
    workspace_slug = workspace.get("slug", "") or workspace.get("uuid", "")
    
    if not repo_full_name or not workspace_slug:
        logger.error("Missing repository or workspace info in webhook payload")
        raise HTTPException(status_code=400, detail="Missing repository or workspace information")
    
    # Convert workspace slug to integer for installation_id field (hash-based)
    # This ensures compatibility with the Commit model which expects int
    workspace_id = int(hashlib.md5(workspace_slug.encode()).hexdigest()[:8], 16)
    
    # Lazy backfill trigger: if repo doesn't exist or is not LIVE, trigger backfill
    # Uses atomic update as a distributed lock to ensure only one backfill runs at a time
    
    # Check current repository status
    repo_status = await get_repository_status_ch(
        session,
        repo_full_name,
        workspace_id,
    )
    
    current_status = repo_status.get("sync_status") if repo_status else None
    
    # Trigger backfill if repository doesn't exist or is not LIVE
    # Skip if already BACKFILLING (another process is handling it)
    if current_status != SyncStatus.LIVE.value and current_status != SyncStatus.BACKFILLING.value:
        # Try to set status to BACKFILLING (acts as distributed lock)
        # For ClickHouse, we check and update atomically
        if not repo_status or repo_status.get("sync_status") != SyncStatus.BACKFILLING.value:
            success = await update_repository_status_ch(
                session,
                repo_full_name,
                workspace_id,
                {
                    "repository_name": repo_name,
                    "sync_status": SyncStatus.BACKFILLING.value,
                    "backfill_started_at": datetime.utcnow(),
                    "error_message": None,
                },
            )
            
            # If update succeeded, trigger backfill
            if success:
                logger.info(
                    f"Lazy backfill triggered for Bitbucket {repo_full_name} "
                    f"(workspace {workspace_id}) - previous status: {current_status or 'missing'}"
                )
                
                # Trigger backfill asynchronously (create new session for async task)
                async def run_backfill():
                    ch_session = SessionLocal()
                    try:
                        from services.ch_backfill import backfill_repository_ch
                        await backfill_repository_ch(
                            repo_full_name=repo_full_name,
                            repo_name=repo_name,
                            repo_url=repo_url,
                            installation_id=workspace_id,
                            session=ch_session,
                            source="bitbucket",
                            max_commits=BACKFILL_MAX_COMMITS,
                        )
                    except Exception as e:
                        logger.error(f"Error in async backfill for Bitbucket {repo_full_name}: {e}", exc_info=True)
                    finally:
                        ch_session.close()
                
                asyncio.create_task(run_backfill())
        else:
            # Another process is already backfilling (race condition handled)
            logger.debug(
                f"Backfill already in progress for Bitbucket {repo_full_name}, skipping trigger"
            )
    elif current_status == SyncStatus.BACKFILLING.value:
        # Backfill already in progress
        logger.debug(
            f"Received webhook for Bitbucket {repo_full_name} while backfill in progress. "
            "Processing commit anyway (idempotency will prevent duplicates)."
        )
    
    # Process commits from push changes
    # Bitbucket push webhook structure: push.changes[].commits[]
    processed_count = 0
    skipped_count = 0
    
    push_data = request_data.get("push", {})
    changes = push_data.get("changes", [])
    
    for change in changes:
        commits = change.get("commits", [])
        
        for commit in commits:
            result = await process_bitbucket_commit_from_webhook(
                commit_data=commit,
                repo_full_name=repo_full_name,
                repo_name=repo_name,
                repo_url=repo_url,
                workspace_id=workspace_id,
                session=session,
                skip_existing=True,  # Idempotency: skip existing commits
            )
            
            if result is None:
                skipped_count += 1
            else:
                processed_count += 1
    
    return {
        "message": "Webhook processed successfully",
        "event_type": "repo:push",
        "processed_commits": processed_count,
        "skipped_commits": skipped_count,
    }