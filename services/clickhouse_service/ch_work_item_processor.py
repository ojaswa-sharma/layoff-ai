"""
ClickHouse operations for Plane work items.

This module provides functions to process and store work item data from Plane webhooks
into ClickHouse.
"""
import logging
from typing import Optional
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.commits import WorkItem
from models.ch_models import WorkItemCH

logger = logging.getLogger(__name__)


async def check_work_item_exists_ch(
    session: Session,
    work_item_id: str,
    workspace_id: str,
) -> bool:
    """
    Check if a work item already exists in ClickHouse by (work_item_id, workspace_id).
    
    Returns:
        True if work item exists, False otherwise
    """
    try:
        count = session.query(func.count(WorkItemCH.work_item_id)).filter(
            WorkItemCH.work_item_id == work_item_id,
            WorkItemCH.workspace_id == workspace_id,
        ).scalar()
        
        return count > 0
    except Exception as e:
        logger.error(f"Error checking work item existence: {e}")
        return False


async def upsert_work_item_ch(
    session: Session,
    work_item: WorkItem,
) -> bool:
    """
    Upsert a work item into ClickHouse using SQLAlchemy ORM.
    
    Returns:
        True if successful, False otherwise
    """
    try:
        work_item_ch = WorkItemCH.from_pydantic(work_item)
        session.add(work_item_ch)
        session.commit()
        
        logger.info(
            f"Upserted work item in ClickHouse: {work_item.work_item_id} "
            f"status={work_item.status}"
        )
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error upserting work item into ClickHouse: {e}")
        return False


async def process_work_item_ch(
    work_item: WorkItem,
    session: Session,
    skip_existing: bool = False,
) -> Optional[WorkItem]:
    """
    Process and upsert a work item into ClickHouse using SQLAlchemy ORM.
    
    Returns:
        WorkItem model if successfully processed, None if skipped
    """
    try:
        if skip_existing:
            exists = await check_work_item_exists_ch(
                session,
                work_item.work_item_id,
                work_item.workspace_id,
            )
            if exists:
                logger.debug(
                    f"Work item {work_item.work_item_id} already exists in ClickHouse, skipping"
                )
                return None
        
        success = await upsert_work_item_ch(session, work_item)
        
        if not success:
            return None
        
        return work_item
        
    except Exception as e:
        logger.error(
            f"Error processing work item {work_item.work_item_id}: {e}",
            exc_info=True
        )
        return None


async def process_plane_work_item(
    webhook_data: dict,
    session: Session,
    skip_existing: bool = False,
) -> Optional[WorkItem]:
    """
    Process a Plane work item webhook event (created or updated).
    
    Extracts data from webhook payload and creates WorkItem model.
    
    Args:
        webhook_data: The webhook payload dictionary
        session: SQLAlchemy session
        skip_existing: If True, skip if work item already exists
        
    Returns:
        WorkItem model if successfully processed, None if skipped or failed
    """
    try:
        data = webhook_data.get("data", {})
        activity = webhook_data.get("activity", {})

        field = activity.get("field")
        if field and field.endswith("_id"):
            return None
        
        # Extract work item ID and workspace ID
        work_item_id = data.get("id")
        workspace_id = webhook_data.get("workspace_id")
        
        if not work_item_id or not workspace_id:
            logger.warning("Work item event missing required IDs")
            return None
        
        # Extract title
        title = data.get("name", "")
        
        # Extract description (prefer stripped, fallback to HTML)
        description = data.get("description_stripped") or data.get("description_html") or ""
        
        # Extract status from state
        state = data.get("state", {})
        status = state.get("name", "Unknown") if isinstance(state, dict) else "Unknown"
        
        # Extract assignee info (from assignees array)
        assignees = data.get("assignees", [])
        assignee_email = None
        assignee_name = None
        if assignees and len(assignees) > 0:
            assignee = assignees[0]
            assignee_email = assignee.get("email")
            assignee_name = assignee.get("display_name")
        
        # Extract assigner info (from activity.actor - only present on updates)
        assigner_email = None
        assigner_name = None
        actor = activity.get("actor", {})
        if actor:
            assigner_email = actor.get("email")
            assigner_name = actor.get("display_name")
        
        # Extract project ID
        project_id = data.get("project")
        
        # Parse dates
        def parse_date(date_str: str) -> datetime:
            if not date_str:
                return datetime.utcnow()
            try:
                if date_str.endswith("Z"):
                    date_str = date_str.replace("Z", "+00:00")
                return datetime.fromisoformat(date_str)
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse date {date_str}: {e}, using current time")
                return datetime.utcnow()
        
        created_at_str = data.get("created_at")
        updated_at_str = data.get("updated_at")
        
        created_at = parse_date(created_at_str) if created_at_str else datetime.utcnow()
        last_updated_at = parse_date(updated_at_str) if updated_at_str else created_at
        
        # Create WorkItem model with source="plane"
        work_item_model = WorkItem(
            work_item_id=work_item_id,
            workspace_id=workspace_id,
            title=title,
            description=description if description else None,
            status=status,
            assignee_email=assignee_email,
            assignee_name=assignee_name,
            assigner_email=assigner_email,
            assigner_name=assigner_name,
            created_at=created_at,
            last_updated_at=last_updated_at,
            project_id=project_id,
            source="plane",
        )
        
        result = await process_work_item_ch(
            work_item_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing Plane work item: {e}", exc_info=True)
        return None


async def process_jira_work_item(
    webhook_data: dict,
    session: Session,
    skip_existing: bool = False,
) -> Optional[WorkItem]:
    """
    Process a Jira work item webhook event (created, updated, or deleted).
    
    Extracts data from webhook payload and creates WorkItem model.
    
    Args:
        webhook_data: The webhook payload dictionary
        session: SQLAlchemy session
        skip_existing: If True, skip if work item already exists
        
    Returns:
        WorkItem model if successfully processed, None if skipped or failed
    """
    try:
        issue = webhook_data.get("issue", {})
        user = webhook_data.get("user", {})
        
        # Extract work item ID and workspace ID
        work_item_id = issue.get("key")  # e.g., "SCRUM-5"
        project = issue.get("project", {})
        workspace_id = project.get("key")  # e.g., "SCRUM"
        
        if not work_item_id or not workspace_id:
            logger.warning("Jira work item event missing required IDs")
            return None
        
        # Extract title
        title = issue.get("summary", "")
        
        # Extract description
        description = issue.get("description", "")
        
        # Extract status
        status_obj = issue.get("status", {})
        status = status_obj.get("name", "Unknown") if isinstance(status_obj, dict) else "Unknown"
        
        # Extract assignee info
        assignee = issue.get("assignee")
        assignee_email = None
        assignee_name = None
        if assignee and isinstance(assignee, dict):
            # Jira uses accountId (no emailAddress in webhook)
            assignee_email = assignee.get("accountId")
            assignee_name = assignee.get("displayName")
        
        # Extract assigner info (from user object in webhook)
        assigner_email = None
        assigner_name = None
        if user and isinstance(user, dict):
            assigner_email = user.get("accountId")
            assigner_name = user.get("displayName")
        
        # Extract project ID
        project_id = project.get("id") or project.get("key")
        
        # Parse dates - Jira uses ISO format with timezone (e.g., "2026-02-20T12:00:42.088+0530")
        def parse_jira_date(date_str: str) -> datetime:
            if not date_str:
                return datetime.utcnow()
            try:
                # Jira dates are in ISO format with timezone offset
                return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            except (ValueError, AttributeError) as e:
                logger.warning(f"Could not parse Jira date {date_str}: {e}, using current time")
                return datetime.utcnow()
        
        created_at_str = issue.get("created")
        updated_at_str = issue.get("updated")
        
        created_at = parse_jira_date(created_at_str) if created_at_str else datetime.utcnow()
        last_updated_at = parse_jira_date(updated_at_str) if updated_at_str else created_at
        
        # Create WorkItem model with source="jira"
        work_item_model = WorkItem(
            work_item_id=work_item_id,
            workspace_id=workspace_id,
            title=title,
            description=description if description else None,
            status=status,
            assignee_email=assignee_email,
            assignee_name=assignee_name,
            assigner_email=assigner_email,
            assigner_name=assigner_name,
            created_at=created_at,
            last_updated_at=last_updated_at,
            project_id=project_id,
            source="jira",
        )
        
        result = await process_work_item_ch(
            work_item_model,
            session,
            skip_existing=skip_existing,
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error processing Jira work item: {e}", exc_info=True)
        return None
