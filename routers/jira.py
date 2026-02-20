"""
Jira webhook router handling webhooks from Jira.

This router processes webhooks from Jira.
"""
from fastapi import APIRouter, Request, Depends, HTTPException
from dotenv import load_dotenv
from datetime import datetime, timezone, timedelta
from sqlalchemy.orm import Session
from dependencies.ch_db import get_ch_session
# from services.clickhouse_service.ch_work_item_processor import process_jira_work_item
import logging

logger = logging.getLogger(__name__)

load_dotenv()

router = APIRouter(prefix="/jira")


@router.post("/webhook")
async def webhook_jira(request: Request, session: Session = Depends(get_ch_session)):
    """
    Handle Jira webhook events.
    
    Supports:
    - issue.created: Process new work item creation
    - issue.updated: Process work item updates
    - issue.deleted: Process work item deletion
    """
    
    request_data = await request.json()
    logger.debug(f"[REQUEST DATA] : {request_data}")
    print(f"[REQUEST DATA] : {request_data}")
        


async def handle_work_item_created(request_data: dict, session: Session):
    """
    Handle work_item.created event - process new work item creation.
    """
    ...


async def handle_work_item_updated(request_data: dict, session: Session):
    """
    Handle work_item.updated event - process work item updates.
    """
    ...