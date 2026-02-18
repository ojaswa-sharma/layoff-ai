"""
GitHub webhook router handling both real-time events and installation events.

This router processes:
- Push events: Real-time commit processing via webhooks
- Installation events: Triggers historical backfill when app is installed
"""
from fastapi import APIRouter, Request, Depends, HTTPException
import os
import asyncio
from dotenv import load_dotenv
from sqlalchemy.orm import Session
from models.commits import SyncStatus
from services.clickhouse_service.ch_commit_processor import process_commit_from_webhook
from services.clickhouse_service.ch_commit_processor import check_commit_exists_ch
from services.clickhouse_service.ch_commit_processor import update_branch_raw_from_commit
from services.clickhouse_service.ch_pr_merge_processor import process_github_pr_merge
from services.clickhouse_service.ch_backfill import get_repository_status_ch, update_repository_status_ch, backfill_repository_ch
from services.tech_stack_service import fetch_github_tech_stack
from services.clickhouse_service.ch_tech_stack import insert_or_update_tech_stack_ch
from dependencies.ch_db import get_ch_session, SessionLocal, get_ch_session_direct
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/github")

BACKFILL_MAX_COMMITS = os.getenv("BACKFILL_MAX_COMMITS", 100)

def get_github_credentials():
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
async def webhook_github(request: Request, session: Session = Depends(get_ch_session)):
    """
    Handle GitHub webhook events.
    
    Supports:
    - push: Process commits from push events (real-time)
    - pull_request: Process PR merge events (separate from commits)
    - installation.created: Trigger historical backfill
    - installation.deleted: Clean up repository tracking
    """
    try:
        event_type = request.headers.get("X-GitHub-Event", "push")
        print(f"[EVENT] EVENT TYPE : {event_type}")
        
        request_data = await request.json()
        
        if event_type == "installation":
            action = request_data.get("action")
            
            if action == "created":
                return await handle_installation_created(request_data, session)
            elif action == "deleted":
                return await handle_installation_deleted(request_data, session)
            else:
                return {"message": f"Ignoring installation action: {action}"}
        
        if event_type == "pull_request":
            print(f'[PR] hittttttttttttttttt')
            # print(f'[PR] : {request_data}')
            return await handle_pull_request_event(request_data, session)
        
        if event_type == "push":
            print(f'[PUSH] hittttttttttttttttt')
            # print(f'[PUSH] : {request_data}')
            return await handle_push_event(request_data, session)
        
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


async def handle_pull_request_event(request_data: dict, session: Session):
    """
    Handle pull_request webhook events - process all PR states (opened, closed, merged).
    """
    action = request_data.get("action")
    
    # Only process opened and closed actions
    if action not in ["opened", "closed"]:
        return {
            "message": f"PR action '{action}' not processed (only 'opened' and 'closed' are supported)",
            "action": action,
        }
    
    pr_data = request_data.get("pull_request", {})
    installation_id = request_data.get("installation", {}).get("id", 123)  # Fallback for testing
    repo_full_name = request_data.get("repository", {}).get("full_name", "")
    repo_name = request_data.get("repository", {}).get("name", "")
    repo_url = request_data.get("repository", {}).get("html_url", "")
    
    if not repo_full_name or not repo_name:
        logger.warning("Missing repository information in PR webhook")
        return {
            "message": "Missing repository information",
            "event_type": "pull_request",
            "action": action,
        }
    
    result = await process_github_pr_merge(
        pr_data=pr_data,
        repo_full_name=repo_full_name,
        repo_name=repo_name,
        repo_url=repo_url,
        installation_id=installation_id,
        session=session,
        skip_existing=False,  # Use upsert logic
    )
    
    if result is None:
        return {
            "message": "PR processing failed",
            "event_type": "pull_request",
            "action": action,
            "pr_number": pr_data.get("number"),
        }
    
    return {
        "message": f"PR {action} processed successfully",
        "event_type": "pull_request",
        "action": action,
        "pr_number": pr_data.get("number"),
        "status": result.status,
    }


async def handle_push_event(request_data: dict, session: Session):
    """
    Handle push webhook events - process commits in real-time.
    
    This maintains the existing webhook behavior while adding:
    - Idempotency checks
    - Lazy backfill triggering for repositories installed before this feature existed
    """
    try:
        installation_id = request_data["installation"]["id"]
        app_id, pem_data = get_github_credentials()
        
        repo_full_name = request_data["repository"]["full_name"]
        repo_name = request_data["repository"]["name"]
        repo_url = request_data["repository"]["html_url"]
        
        
        repo_status = await get_repository_status_ch(
            session,
            repo_full_name,
            installation_id,
        )
        
        current_status = repo_status.get("sync_status") if repo_status else None
        
        if current_status != SyncStatus.LIVE.value and current_status != SyncStatus.BACKFILLING.value:
            if not repo_status or repo_status.get("sync_status") != SyncStatus.BACKFILLING.value:
                success = await update_repository_status_ch(
                    session,
                    repo_full_name,
                    installation_id,
                    {
                        "repository_name": repo_name,
                        "sync_status": SyncStatus.BACKFILLING.value,
                        "backfill_started_at": datetime.utcnow(),
                        "error_message": None,
                    },
                )
                
                if success:
                    logger.info(
                        f"Lazy backfill triggered for {repo_full_name} "
                        f"(installation {installation_id}) - previous status: {current_status or 'missing'}"
                    )
                    
                    async def run_backfill():
                        ch_session = get_ch_session_direct()

                        try:
                            await backfill_repository_ch(
                                repo_full_name=repo_full_name,
                                repo_name=repo_name,
                                repo_url=repo_url,
                                installation_id=installation_id,
                                app_id=app_id,
                                private_key_pem=pem_data,
                                session=ch_session,
                                max_commits=BACKFILL_MAX_COMMITS,
                            )
                        except Exception as e:
                            logger.error(f"Error in async backfill for {repo_full_name}: {e}", exc_info=True)
                        finally:
                            ch_session.close()
                    
                    asyncio.create_task(run_backfill())
            else:
                logger.debug(
                    f"Backfill already in progress for {repo_full_name}, skipping trigger"
                )
        elif current_status == SyncStatus.BACKFILLING.value:
            logger.debug(
                f"Received webhook for {repo_full_name} while backfill in progress. "
                "Processing commit anyway (idempotency will prevent duplicates)."
            )
        
        processed_count = 0
        skipped_count = 0
        
        # Extract branch name from ref (format: refs/heads/branch-name)
        ref = request_data.get("ref", "")
        branch_name = None
        if ref.startswith("refs/heads/"):
            branch_name = ref.replace("refs/heads/", "")
        elif ref.startswith("refs/"):
            # Handle other ref types (tags, etc.) - extract branch name if possible
            parts = ref.split("/")
            if len(parts) >= 3 and parts[1] == "heads":
                branch_name = "/".join(parts[2:])
        
        for commit in request_data.get("commits", []):

            # for commit in payload["commits"]:
            # msg = commit.get("message", "")
            # if msg.startswith("Merge pull request"):
            #     continue  # skip merge commit

            # if len(commit.get('parents', [])) > 1:
            #     print(f"[DEBUG] Skipping merge commit: {commit.get('id')}")
            #     continue  # skip merge commit
            
            full_commit_hash = commit["id"]
            commit_hash = full_commit_hash[:12]

            exists = await check_commit_exists_ch(
                session,
                commit_hash,
                repo_name,
                installation_id,
            )
            if exists:
                logger.debug(f"Commit {commit_hash} already exists, skipping")
                break

            result = await process_commit_from_webhook(
                commit_data=commit,
                repo_full_name=repo_full_name,
                repo_name=repo_name,
                repo_url=repo_url,
                installation_id=installation_id,
                app_id=app_id,
                private_key_pem=pem_data,
                session=session,
                skip_existing=True,
                branch_name=branch_name,
            )


            try:
                # Extract email and commit_date from commit data
                commit_email = commit.get("author", {}).get("email", "")
                timestamp_str = commit.get("timestamp")
                if timestamp_str:
                    try:
                        if timestamp_str.endswith("Z"):
                            timestamp_str = timestamp_str.replace("Z", "+00:00")
                        commit_date = datetime.fromisoformat(timestamp_str)
                    except (ValueError, AttributeError):
                        commit_date = datetime.utcnow()
                else:
                    commit_date = datetime.utcnow()
                
                # Update branch_raw table
                await update_branch_raw_from_commit(
                    session=session,
                    email=commit_email,
                    repository_full_name=repo_full_name,
                    branch_name=branch_name,
                    commit_date=commit_date,
                    installation_id=installation_id,
                    commit_hash=commit_hash,
                )
            except Exception as e:
                # Log error but don't fail the webhook
                logger.warning(f"Failed to update branch_raw for commit {commit_hash}: {e}", exc_info=True)
            
            if result is None:
                skipped_count += 1
            else:
                processed_count += 1
        
        try:
            tech_stack_data = await fetch_github_tech_stack(
                repo_full_name=repo_full_name,
                app_id=app_id,
                private_key_pem=pem_data,
                installation_id=installation_id,
            )
            
            if tech_stack_data:
                try:
                    await insert_or_update_tech_stack_ch(
                        session=session,
                        repository_full_name=repo_full_name,
                        repository_name=repo_name,
                        installation_id=installation_id,
                        languages=tech_stack_data.get("languages"),
                        topics=tech_stack_data.get("topics"),
                        source=tech_stack_data.get("source", "github"),
                    )
                    logger.info(f"Tech stack updated for {repo_full_name}")
                except Exception as e:
                    print(f"[ERROR] Something went wrong while fetching tech stack : {e}")
        except Exception as e:
            logger.warning(f"Failed to fetch/update tech stack for {repo_full_name}: {e}", exc_info=True)
        
        return {
            "message": "Webhook processed successfully",
            "event_type": "push",
            "processed_commits": processed_count,
            "skipped_commits": skipped_count,
        }
    except Exception as e:
        print(f'[ERROR] Error while pushing from github : {e}')
    finally:
        session.close()

async def handle_installation_created(request_data: dict, session: Session):
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
    
    for repo in repositories:
        repo_full_name = repo["full_name"]
        repo_name = repo["name"]
        
        await update_repository_status_ch(
            session,
            repo_full_name,
            installation_id,
            {
                "repository_name": repo_name,
                "sync_status": SyncStatus.BACKFILLING.value,
                "event_time": datetime.utcnow(),
            },
        )
        
        repo_url_value = repo.get("html_url", f"https://github.com/{repo_full_name}")
        async def run_backfill(rf_name: str, r_name: str, r_url: str):
            ch_session = SessionLocal()
            try:
                await backfill_repository_ch(
                    repo_full_name=rf_name,
                    repo_name=r_name,
                    repo_url=r_url,
                    installation_id=installation_id,
                    session=ch_session,
                    source="github",
                    max_commits=BACKFILL_MAX_COMMITS,
                    app_id=app_id,
                    private_key_pem=pem_data,
                )
            except Exception as e:
                logger.error(f"Error in async backfill for {rf_name}: {e}", exc_info=True)
            finally:
                ch_session.close()
        
        asyncio.create_task(run_backfill(repo_full_name, repo_name, repo_url_value))
        
        logger.info(
            f"Triggered backfill for {repo_full_name} (installation {installation_id})"
        )
    
    return {
        "message": "Installation processed, backfill started",
        "installation_id": installation_id,
        "repositories_count": len(repositories),
        "repositories": [repo["full_name"] for repo in repositories],
    }


async def handle_installation_deleted(request_data: dict, session: Session):
    """
    Handle installation.deleted event - clean up repository tracking.
    
    Note: We don't delete commits, just update repository status.
    """
    installation_id = request_data["installation"]["id"]
    
    from models.ch_models import RepoSyncEventCH
    
    repos = session.query(RepoSyncEventCH).filter(
        RepoSyncEventCH.installation_id == installation_id,
    ).all()
    
    updated_count = 0
    for repo in repos:
        repo.sync_status = SyncStatus.FAILED.value
        repo.error_message = "Installation deleted"
        updated_count += 1
    
    session.commit()
    
    logger.info(
        f"Marked {updated_count} repositories as deleted "
        f"for installation {installation_id}"
    )
    
    return {
        "message": "Installation deleted, repositories marked",
        "installation_id": installation_id,
        "repositories_updated": updated_count,
    }