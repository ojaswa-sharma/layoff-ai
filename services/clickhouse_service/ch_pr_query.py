"""
ClickHouse PR query operations using SQLAlchemy ORM.

This module provides functions to query PR data with filtering and pagination.
"""
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_
from models.ch_models import PRMergeCH

logger = logging.getLogger(__name__)


async def get_prs_ch(
    session: Session,
    repository_full_name: Optional[str] = None,
    status: Optional[str] = None,
    created_by_email: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Query PRs from ClickHouse with filtering and pagination.
    
    Args:
        session: SQLAlchemy session
        repository_full_name: Filter by repository full name (owner/repo)
        status: Filter by PR status ("open", "closed", "merged")
        created_by_email: Filter by PR creator email
        date_from: Filter PRs updated after this date
        date_to: Filter PRs updated before this date
        page: Page number (1-indexed)
        limit: Number of results per page (max 100)
        
    Returns:
        Dictionary with 'prs' list and 'pagination' info
    """
    try:
        # Clamp limit to max 100
        limit = min(limit, 100)
        offset = (page - 1) * limit
        
        # Build query
        query = session.query(PRMergeCH)
        
        # Apply filters
        filters = []
        
        if repository_full_name:
            # Match by repository_url or repository_name
            filters.append(
                or_(
                    PRMergeCH.repository_url.like(f"%{repository_full_name}%"),
                    PRMergeCH.repository_name == repository_full_name.split("/")[-1] if "/" in repository_full_name else repository_full_name
                )
            )
        
        if status:
            filters.append(PRMergeCH.status == status)
        
        if created_by_email:
            filters.append(PRMergeCH.created_by_email == created_by_email)
        
        if date_from:
            if date_from.tzinfo is None:
                date_from = date_from.replace(tzinfo=timezone.utc)
            filters.append(PRMergeCH.updated_at >= date_from)
        
        if date_to:
            if date_to.tzinfo is None:
                date_to = date_to.replace(tzinfo=timezone.utc)
            filters.append(PRMergeCH.updated_at <= date_to)
        
        if filters:
            query = query.filter(and_(*filters))
        
        # Get total count for pagination
        total_count = query.count()
        
        # Apply ordering and pagination
        query = query.order_by(PRMergeCH.updated_at.desc())
        query = query.offset(offset).limit(limit)
        
        # Execute query
        results = query.all()
        
        # Format results
        prs = []
        for pr in results:
            pr_dict = {
                "pr_number": pr.pr_number,
                "title": pr.pr_title,
                "project": pr.repository_name,
                "status": pr.status,
                "created_by": pr.created_by,
                "created_by_email": pr.created_by_email,
                "changes": {
                    "additions": pr.additions if pr.additions is not None else 0,
                    "deletions": pr.deletions if pr.deletions is not None else 0,
                },
                "branch": pr.branch,
                "last_updated_at": pr.updated_at.isoformat() if pr.updated_at else None,
            }
            prs.append(pr_dict)
        
        # Calculate pagination info
        total_pages = (total_count + limit - 1) // limit if total_count > 0 else 0
        
        return {
            "prs": prs,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total_count,
                "total_pages": total_pages,
            }
        }
        
    except Exception as e:
        logger.error(f"Error querying PRs: {e}", exc_info=True)
        return {
            "prs": [],
            "pagination": {
                "page": page,
                "limit": limit,
                "total": 0,
                "total_pages": 0,
            }
        }

