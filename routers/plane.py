"""
Plane webhook router handling webhooks from plane.so.

This router processes webhooks from plane.so.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from dependencies.ch_db import get_ch_session
from services.clickhouse_service.ch_work_item_processor import process_plane_work_item
import logging

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/plane")


def parse_plane_time(ts: str) -> datetime:
    if not ts:
        return None
    # Plane sends ISO with Z
    if ts.endswith("Z"):
        ts = ts.replace("Z", "+00:00")
    return datetime.fromisoformat(ts)

@router.post("/webhook")
async def webhook_plane(request: Request, session: Session = Depends(get_ch_session)):
    """
    Handle Plane webhook events.
    
    Supports:
    - issue.created: Process new work item creation
    - issue.updated: Process work item updates
    """
    try:
        request_data = await request.json()
        # logger.debug(f"[REQUEST DATA] : {request_data}")
        print(f"[REQUEST DATA] : {request_data}")
        
        event = request_data.get("event")
        action = request_data.get("action")
        
        if event == "issue":
            if action == "created":
                return await handle_work_item_created(request_data, session)
            elif action == "updated":
                return await handle_work_item_updated(request_data, session)
            else:
                return {
                    "message": f"Issue action '{action}' not processed (only 'created' and 'updated' are supported)",
                    "event": event,
                    "action": action,
                }
        
        return {
            "message": f"Event type '{event}' not processed",
            "event": event,
            "action": action,
        }
        
    except KeyError as e:
        logger.error(f"Missing required field: {e}")
        raise HTTPException(status_code=400, detail=f"Missing required field: {str(e)}")
    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing webhook: {str(e)}")


async def handle_work_item_created(request_data: dict, session: Session):
    """
    Handle work_item.created event - process new work item creation.
    """
    try:
        result = await process_plane_work_item(
            webhook_data=request_data,
            session=session,
            skip_existing=False,  # Use upsert logic
        )
        
        if result is None:
            return {
                "message": "Work item processing failed",
                "event": "issue",
                "action": "created",
                "work_item_id": request_data.get("data", {}).get("id"),
            }
        
        return {
            "message": "Work item created processed successfully",
            "event": "issue",
            "action": "created",
            "work_item_id": result.work_item_id,
            "status": result.status,
        }
    except Exception as e:
        logger.error(f"Error handling work item created: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing work item created: {str(e)}")


async def handle_work_item_updated(request_data: dict, session: Session):
    """
    Handle work_item.updated event - process work item updates.
    """
    try:
        data = request_data.get("data", {})
        activity = request_data.get("activity", {})

        field = activity.get("field")
        if field and field.endswith("_id"):
            return None

        # Ignore low-level ID changes
        if field and field.endswith("_id"):
            return None

        # Ignore auto updates right after creation
        if activity.get("field") == "assignees":
            created = parse_plane_time(data["created_at"])
            updated = parse_plane_time(data["updated_at"])
            if (updated - created).total_seconds() < 1:
                return None

        result = await process_plane_work_item(
            webhook_data=request_data,
            session=session,
            skip_existing=False,  # Use upsert logic
        )
        
        if result is None:
            return {
                "message": "Work item processing failed",
                "event": "issue",
                "action": "updated",
                "work_item_id": request_data.get("data", {}).get("id"),
            }
        
        return {
            "message": "Work item updated processed successfully",
            "event": "issue",
            "action": "updated",
            "work_item_id": result.work_item_id,
            "status": result.status,
        }
    except Exception as e:
        logger.error(f"Error handling work item updated: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error processing work item updated: {str(e)}")
