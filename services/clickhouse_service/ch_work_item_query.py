"""
ClickHouse work item query operations using SQLAlchemy ORM.

This module provides functions to query Plane work item data with filtering and pagination.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from models.ch_models import WorkItemCH

logger = logging.getLogger(__name__)


async def get_work_items_ch(
    session: Session,
    assignee_email: str,
    status: Optional[str] = None,
    workspace_id: Optional[str] = None,
    project_id: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Query work items from ClickHouse with filtering and pagination.
    
    Args:
        session: SQLAlchemy session
        assignee_email: Filter by assignee email (required)
        status: Filter by work item status (optional)
        workspace_id: Filter by workspace ID (optional)
        project_id: Filter by project ID (optional)
        date_from: Filter work items updated after this date
        date_to: Filter work items updated before this date
        page: Page number (1-indexed)
        limit: Number of results per page (max 100)
        
    Returns:
        Dictionary with 'work_items' list and 'pagination' info
    """
    try:
        # Clamp limit to max 100
        limit = min(limit, 100)
        offset = (page - 1) * limit
        
        # Build query
        query = session.query(WorkItemCH)
        
        # Apply filters
        filters = []
        
        # Required filter: assignee_email
        filters.append(WorkItemCH.assignee_email == assignee_email)
        
        if status:
            filters.append(WorkItemCH.status == status)
        
        if workspace_id:
            filters.append(WorkItemCH.workspace_id == workspace_id)
        
        if project_id:
            filters.append(WorkItemCH.project_id == project_id)
        
        if date_from:
            if date_from.tzinfo is None:
                date_from = date_from.replace(tzinfo=timezone.utc)
            filters.append(WorkItemCH.last_updated_at >= date_from)
        
        if date_to:
            if date_to.tzinfo is None:
                date_to = date_to.replace(tzinfo=timezone.utc)
            filters.append(WorkItemCH.last_updated_at <= date_to)
        
        if filters:
            query = query.filter(and_(*filters))
        
        # Get total count for pagination
        total_count = query.count()
        
        # Apply ordering and pagination
        query = query.order_by(WorkItemCH.last_updated_at.desc())
        query = query.offset(offset).limit(limit)
        
        # Execute query
        results = query.all()
        
        # Format results
        work_items = []
        for item in results:
            work_item_dict = {
                "work_item_id": item.work_item_id,
                "workspace_id": item.workspace_id,
                "title": item.title,
                "description": item.description,
                "status": item.status,
                "assignee_email": item.assignee_email,
                "assignee_name": item.assignee_name,
                "assigner_email": item.assigner_email,
                "assigner_name": item.assigner_name,
                "project_id": item.project_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "last_updated_at": item.last_updated_at.isoformat() if item.last_updated_at else None,
            }
            work_items.append(work_item_dict)
        
        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        
        return {
            "work_items": work_items,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "total_pages": total_pages,
            }
        }
        
    except Exception as e:
        logger.error(f"Error querying work items: {e}", exc_info=True)
        return {
            "work_items": [],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": 0,
                "total_pages": 0,
            }
        }

