"""
GitHub webhook router handling both real-time events and installation events.

This router processes:
- Push events: Real-time commit processing via webhooks
- Installation events: Triggers historical backfill when app is installed
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from models.commits import Repository, SyncStatus
from services.commit_processor import process_commit_from_webhook
from services.pr_merge_processor import process_github_pr_merge
from services.backfill import backfill_repository
import os
from services.db import get_mongo_db
import asyncio
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/github")


def get_github_credentials():
    """Load GitHub App credentials from environment."""
    app_id = os.getenv("APP_ID")
    pem_path = os.getenv("GITHUB_PEM_PATH", "isometrik.pem")
    
    if not app_id:
        raise ValueError("APP_ID environment variable not set")
    
    if not os.path.exists(pem_path):
        raise FileNotFoundError(f"GitHub PEM file not found: {pem_path}")
    
    with open(pem_path, 'r') as file:
        pem_data = file.read()
    
    return app_id, pem_data


@router.post("/webhook")
async def webhook_github(request: Request, mongo=Depends(get_mongo_db)):
    """
    Handle GitHub webhook events.
    
    Supports:
    - push: Process commits from push events (real-time)
    - pull_request: Process PR merge events (separate from commits)
    - installation.created: Trigger historical backfill
    - installation.deleted: Clean up repository tracking
    """
    try:
        # Get GitHub event type from headers
        event_type = request.headers.get("X-GitHub-Event", "push")
        
        request_data = await request.json()
        
        # Handle installation events
        if event_type == "installation":
            action = request_data.get("action")
            
            if action == "created":
                return await handle_installation_created(request_data, mongo)
            elif action == "deleted":
                return await handle_installation_deleted(request_data, mongo)
            else:
                return {"message": f"Ignoring installation action: {action}"}
        
        # Handle pull request events (PR merges)
        if event_type == "pull_request":
            return await handle_pull_request_event(request_data, mongo)
        
        # Handle push events (existing functionality)
        if event_type == "push":
            return await handle_push_event(request_data, mongo)
        
        # Ignore other event types
        return {
            "message": f"Event type '{event_type}' not processed",
            "event_type": event_type,
        }
        
    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")
    except FileNotFoundError as e:
        logger.error(f"PEM file not found: {e}")
        raise HTTPException(status_code=500, detail="PEM file not found")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


async def handle_pull_request_event(request_data: dict, mongo):
    """
    Handle pull_request webhook events - process PR merges separately from commits.
    
    Only processes PRs that are merged (action: closed, merged: true).
    PR merges are stored in pr_merges collection without diff/changes tracking.
    """
    action = request_data.get("action")
    
    # Only process merged PRs
    if action != "closed":
        return {
            "message": f"PR action '{action}' not processed (only 'closed' with merged=true)",
            "action": action,
        }
    
    pr_data = request_data.get("pull_request", {})
    merged = pr_data.get("merged", False)
    
    if not merged:
        return {
            "message": "PR was closed but not merged, skipping",
            "action": action,
        }
    
    installation_id = request_data["installation"]["id"]
    repo_full_name = request_data["repository"]["full_name"]
    repo_name = request_data["repository"]["name"]
    repo_url = request_data["repository"]["html_url"]
    
    result = await process_github_pr_merge(
        pr_data=pr_data,
        repo_full_name=repo_full_name,
        repo_name=repo_name,
        repo_url=repo_url,
        installation_id=installation_id,
        mongo_db=mongo,
        skip_existing=True,  # Idempotency: skip existing PR merges
    )
    
    if result is None:
        return {
            "message": "PR merge already exists or failed to process",
            "event_type": "pull_request",
            "action": action,
            "pr_number": pr_data.get("number"),
        }
    
    return {
        "message": "PR merge processed successfully",
        "event_type": "pull_request",
        "action": action,
        "pr_number": pr_data.get("number"),
        "merged_by": result.merged_by,
    }


async def handle_push_event(request_data: dict, mongo):
    """
    Handle push webhook events - process commits in real-time.
    
    This maintains the existing webhook behavior while adding:
    - Idempotency checks
    - Lazy backfill triggering for repositories installed before this feature existed
    """
    installation_id = request_data["installation"]["id"]
    app_id, pem_data = get_github_credentials()
    
    repo_full_name = request_data["repository"]["full_name"]
    repo_name = request_data["repository"]["name"]
    repo_url = request_data["repository"]["html_url"]
    
    # Lazy backfill trigger: if repo doesn't exist or is not LIVE, trigger backfill
    # This handles repositories installed before the installation.created feature existed
    # Uses atomic update as a distributed lock to ensure only one backfill runs at a time
    
    # Check current repository status
    repo_status = mongo.repositories.find_one({
        "repository_full_name": repo_full_name,
        "installation_id": installation_id,
    })
    
    current_status = repo_status.get("sync_status") if repo_status else None
    
    # Trigger backfill if repository doesn't exist or is not LIVE
    # Skip if already BACKFILLING (another process is handling it)
    if current_status != SyncStatus.LIVE.value and current_status != SyncStatus.BACKFILLING.value:
        # Atomically try to set status to BACKFILLING (acts as distributed lock)
        # Query matches if: repo doesn't exist OR sync_status is not BACKFILLING
        # This ensures only one process can successfully set it to BACKFILLING
        updated_repo = mongo.repositories.find_one_and_update(
            {
                "repository_full_name": repo_full_name,
                "installation_id": installation_id,
                "$or": [
                    {"sync_status": {"$ne": SyncStatus.BACKFILLING.value}},
                    {"sync_status": {"$exists": False}},
                ],
            },
            {
                "$set": {
                    "repository_name": repo_name,
                    "repository_full_name": repo_full_name,
                    "repository_url": repo_url,
                    "installation_id": installation_id,
                    "sync_status": SyncStatus.BACKFILLING.value,
                    "backfill_started_at": datetime.utcnow(),
                    "error_message": None,
                },
            },
            upsert=True,
            return_document=True,
        )
        
        # If update succeeded (returned document with BACKFILLING status), trigger backfill
        if updated_repo and updated_repo.get("sync_status") == SyncStatus.BACKFILLING.value:
            logger.info(
                f"Lazy backfill triggered for {repo_full_name} "
                f"(installation {installation_id}) - previous status: {current_status or 'missing'}"
            )
            
            # Get backfill limits from environment
            max_commits = os.getenv("BACKFILL_MAX_COMMITS")
            max_days = os.getenv("BACKFILL_MAX_DAYS")
            
            # Trigger backfill asynchronously (non-blocking)
            asyncio.create_task(
                backfill_repository(
                    repo_full_name=repo_full_name,
                    repo_name=repo_name,
                    repo_url=repo_url,
                    installation_id=installation_id,
                    app_id=app_id,
                    private_key_pem=pem_data,
                    mongo_db=mongo,
                    max_commits=int(max_commits) if max_commits else None,
                    max_days=int(max_days) if max_days else None,
                )
            )
        else:
            # Another process is already backfilling (race condition handled)
            logger.debug(
                f"Backfill already in progress for {repo_full_name}, skipping trigger"
            )
    elif current_status == SyncStatus.BACKFILLING.value:
        # Backfill already in progress
        logger.debug(
            f"Received webhook for {repo_full_name} while backfill in progress. "
            "Processing commit anyway (idempotency will prevent duplicates)."
        )
    
    # Process commits using shared processor (always, regardless of backfill status)
    processed_count = 0
    skipped_count = 0
    
    for commit in request_data.get("commits", []):
        result = await process_commit_from_webhook(
            commit_data=commit,
            repo_full_name=repo_full_name,
            repo_name=repo_name,
            repo_url=repo_url,
            installation_id=installation_id,
            app_id=app_id,
            private_key_pem=pem_data,
            mongo_db=mongo,
            skip_existing=True,  # Idempotency: skip existing commits
        )
        
        if result is None:
            skipped_count += 1
        else:
            processed_count += 1
    
    return {
        "message": "Webhook processed successfully",
        "event_type": "push",
        "processed_commits": processed_count,
        "skipped_commits": skipped_count,
    }


async def handle_installation_created(request_data: dict, mongo):
    """
    Handle installation.created event - trigger historical backfill.
    
    When a GitHub App is installed, this function:
    1. Records the installation and repositories
    2. Triggers backfill for each installed repository
    3. Returns immediately (backfill runs asynchronously)
    
    Note: Re-installation on the same repository will trigger backfill again,
    but idempotency ensures no duplicate commits are stored.
    """
    installation_id = request_data["installation"]["id"]
    app_id, pem_data = get_github_credentials()
    
    repositories = request_data["installation"].get("repositories", [])
    
    if not repositories:
        logger.info(f"Installation {installation_id} has no repositories")
        return {
            "message": "Installation created with no repositories",
            "installation_id": installation_id,
        }
    
    # Record repositories and trigger backfill
    backfill_tasks = []
    
    for repo in repositories:
        repo_full_name = repo["full_name"]
        repo_name = repo["name"]
        repo_url = repo.get("html_url", f"https://github.com/{repo_full_name}")
        
        # Create repository record
        repository = Repository(
            repository_name=repo_name,
            repository_full_name=repo_full_name,
            repository_url=repo_url,
            installation_id=installation_id,
            sync_status=SyncStatus.BACKFILLING,
            backfill_started_at=datetime.utcnow(),
        )
        
        mongo.repositories.update_one(
            {
                "repository_full_name": repo_full_name,
                "installation_id": installation_id,
            },
            {"$set": repository.model_dump()},
            upsert=True,
        )
        
        # Trigger backfill asynchronously
        # Use environment variables for backfill limits if available
        max_commits = os.getenv("BACKFILL_MAX_COMMITS")
        max_days = os.getenv("BACKFILL_MAX_DAYS")
        
        task = asyncio.create_task(
            backfill_repository(
                repo_full_name=repo_full_name,
                repo_name=repo_name,
                repo_url=repo_url,
                installation_id=installation_id,
                app_id=app_id,
                private_key_pem=pem_data,
                mongo_db=mongo,
                max_commits=int(max_commits) if max_commits else None,
                max_days=int(max_days) if max_days else None,
            )
        )
        backfill_tasks.append(task)
        
        logger.info(
            f"Triggered backfill for {repo_full_name} (installation {installation_id})"
        )
    
    return {
        "message": "Installation processed, backfill started",
        "installation_id": installation_id,
        "repositories_count": len(repositories),
        "repositories": [repo["full_name"] for repo in repositories],
    }


async def handle_installation_deleted(request_data: dict, mongo):
    """
    Handle installation.deleted event - clean up repository tracking.
    
    Note: We don't delete commits, just update repository status.
    """
    installation_id = request_data["installation"]["id"]
    
    # Update all repositories for this installation
    result = mongo.repositories.update_many(
        {"installation_id": installation_id},
        {
            "$set": {
                "sync_status": SyncStatus.FAILED.value,
                "error_message": "Installation deleted",
            },
        },
    )
    
    logger.info(
        f"Marked {result.modified_count} repositories as deleted "
        f"for installation {installation_id}"
    )
    
    return {
        "message": "Installation deleted, repositories marked",
        "installation_id": installation_id,
        "repositories_updated": result.modified_count,
    }