"""
Jira webhook router handling webhooks from Jira.

This router processes webhooks from Jira.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from dotenv import load_dotenv
from datetime import datetime
from sqlalchemy.orm import Session
from dependencies.ch_db import get_ch_session
from services.clickhouse_service.ch_work_item_processor import process_jira_work_item
import logging

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/jira")


@router.post("/webhook")
async def webhook_jira(request: Request, session: Session = Depends(get_ch_session)):
    """
    Handle Jira webhook events.
    
    Supports:
    - jira:issue_created: Process new work item creation
    - jira:issue_updated: Process work item updates
    - jira:issue_deleted: Process work item deletion
    """
    try:
        request_data = await request.json()
        logger.debug(f"[REQUEST DATA] : {request_data}")
        print(f"[REQUEST DATA] : {request_data}")
        
        webhook_event = request_data.get("webhookEvent")
        issue_event_type = request_data.get("issue_event_type_name")
        
        # Determine event type from webhookEvent or issue_event_type_name
        if webhook_event == "jira:issue_created" or issue_event_type == "issue_created":
            return await handle_work_item_created(request_data, session)
        elif webhook_event == "jira:issue_updated" or issue_event_type == "issue_updated":
            return await handle_work_item_updated(request_data, session)
        elif webhook_event == "jira:issue_deleted" or issue_event_type == "issue_deleted":
            return await handle_work_item_deleted(request_data, session)
        else:
            return {
                "message": f"Event type '{webhook_event}' or '{issue_event_type}' not processed",
                "webhookEvent": webhook_event,
                "issue_event_type_name": issue_event_type,
            }
        
    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


async def handle_work_item_created(request_data: dict, session: Session):
    """
    Handle jira:issue_created event - process new work item creation.
    """
    try:
        result = await process_jira_work_item(
            webhook_data=request_data,
            session=session,
            skip_existing=False,  # Use upsert logic
        )
        
        if result is None:
            return {
                "message": "Work item processing failed",
                "webhookEvent": "jira:issue_created",
                "work_item_id": request_data.get("issue", {}).get("key"),
            }
        
        return {
            "message": "Work item created processed successfully",
            "webhookEvent": "jira:issue_created",
            "work_item_id": result.work_item_id,
            "status": result.status,
        }
    except Exception as e:
        logger.error(f"Error handling work item created: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing work item created: {str(e)}")


async def handle_work_item_updated(request_data: dict, session: Session):
    """
    Handle jira:issue_updated event - process work item updates.
    """
    try:
        result = await process_jira_work_item(
            webhook_data=request_data,
            session=session,
            skip_existing=False,  # Use upsert logic
        )
        
        if result is None:
            return {
                "message": "Work item processing failed",
                "webhookEvent": "jira:issue_updated",
                "work_item_id": request_data.get("issue", {}).get("key"),
            }
        
        return {
            "message": "Work item updated processed successfully",
            "webhookEvent": "jira:issue_updated",
            "work_item_id": result.work_item_id,
            "status": result.status,
        }
    except Exception as e:
        logger.error(f"Error handling work item updated: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing work item updated: {str(e)}")


async def handle_work_item_deleted(request_data: dict, session: Session):
    """
    Handle jira:issue_deleted event - process work item deletion.
    
    For delete events, we'll update the status to "Deleted" as a soft-delete approach,
    since ClickHouse ReplacingMergeTree will handle deduplication based on last_updated_at.
    """
    try:
        issue = request_data.get("issue", {})
        user = request_data.get("user", {})
        
        # Extract work item ID and workspace ID
        work_item_id = issue.get("key")
        project = issue.get("project", {})
        workspace_id = project.get("key")
        
        if not work_item_id or not workspace_id:
            logger.warning("Jira delete event missing required IDs")
            return {
                "message": "Delete event missing required IDs",
                "webhookEvent": "jira:issue_deleted",
            }
        
        # Extract assignee info
        assignee = issue.get("assignee")
        assignee_email = None
        assignee_name = None
        if assignee and isinstance(assignee, dict):
            assignee_email = assignee.get("accountId")
            assignee_name = assignee.get("displayName")
        
        # Extract assigner info (from user object in webhook)
        assigner_email = None
        assigner_name = None
        if user and isinstance(user, dict):
            assigner_email = user.get("accountId")
            assigner_name = user.get("displayName")
        
        # Parse dates - Jira uses ISO format with timezone
        def parse_jira_date(date_str: str) -> datetime:
            if not date_str:
                return datetime.utcnow()
            try:
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse Jira date {date_str}: {e}, using current time")
                return datetime.utcnow()
        
        created_at_str = issue.get("created")
        updated_at_str = issue.get("updated")
        
        created_at = parse_jira_date(created_at_str) if created_at_str else datetime.utcnow()
        last_updated_at = parse_jira_date(updated_at_str) if updated_at_str else datetime.utcnow()
        
        # Process with status="Deleted" to mark as deleted
        # We'll create a work item with deleted status and preserve assignee/assigner info
        from models.commits import WorkItem
        from services.clickhouse_service.ch_work_item_processor import process_work_item_ch
        
        deleted_work_item = WorkItem(
            work_item_id=work_item_id,
            workspace_id=workspace_id,
            title=issue.get("summary", ""),
            description=issue.get("description"),
            status="Deleted",
            assignee_email=assignee_email,
            assignee_name=assignee_name,
            assigner_email=assigner_email,
            assigner_name=assigner_name,
            created_at=created_at,
            last_updated_at=last_updated_at,
            project_id=project.get("id") or project.get("key"),
            source="jira",
        )
        
        result = await process_work_item_ch(
            deleted_work_item,
            session,
            skip_existing=False,
        )
        
        if result is None:
            return {
                "message": "Work item deletion processing failed",
                "webhookEvent": "jira:issue_deleted",
                "work_item_id": work_item_id,
            }
        
        return {
            "message": "Work item deleted processed successfully",
            "webhookEvent": "jira:issue_deleted",
            "work_item_id": result.work_item_id,
            "status": result.status,
        }
    except Exception as e:
        logger.error(f"Error handling work item deleted: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing work item deleted: {str(e)}")