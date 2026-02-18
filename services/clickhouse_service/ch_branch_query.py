"""
ClickHouse branch analytics query service.

This module provides optimized queries for branch analytics using FINAL
and finalizeAggregation for proper aggregation handling.
"""
import logging
from typing import Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy import text

logger = logging.getLogger(__name__)


async def get_user_branches(
    session: Session,
    email: str,
    page: int = 1,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Get branch analytics for a specific user.
    
    This function:
    1. Queries user_branch_agg with FINAL for deduplication
    2. Uses finalizeAggregation for aggregate functions
    3. Returns only branch_name, repository_full_name, commit_count, and last_commit_date
    
    Args:
        session: SQLAlchemy session
        email: User email address
        page: Page number (1-indexed)
        limit: Results per page
        
    Returns:
        Dictionary with:
        - branches: List of branch data (branch_name, repository_full_name, commit_count, last_commit_date)
        - pagination: Pagination metadata
    """
    try:
        offset = (page - 1) * limit
        
        # Build optimized query with FINAL and finalizeAggregation
        query = text("""
            SELECT
                uba.repository_full_name,
                uba.branch_name,
                finalizeAggregation(uba.commit_count) AS commit_count,
                finalizeAggregation(uba.last_commit_date) AS last_commit_date
            FROM user_branch_agg AS uba FINAL
            WHERE uba.email = :email
            ORDER BY last_commit_date DESC
            LIMIT :limit OFFSET :offset
        """)
            # ORDER BY finalizeAggregation(uba.last_commit_date) DESC
        
        result = session.execute(
            query,
            {
                "email": email,
                "limit": limit,
                "offset": offset,
            }
        )
        
        branches = []
        for row in result:
            branches.append({
                "branch_name": row.branch_name,
                "repository_full_name": row.repository_full_name,
                "commit_count": row.commit_count or 0,
                "last_commit_date": row.last_commit_date.isoformat() if row.last_commit_date else None,
            })
        
        # Get total count for pagination
        count_query = text("""
            SELECT count(*) as total
            FROM user_branch_agg FINAL
            WHERE email = :email
        """)
        
        count_result = session.execute(count_query, {"email": email})
        total = count_result.fetchone().total if count_result else 0
        
        return {
            "branches": branches,
            "pagination": {
                "page": page,
                "limit": limit,
                "total": total,
                "pages": (total + limit - 1) // limit if total > 0 else 0,
            },
        }
        
    except Exception as e:
        logger.error(f"Error querying user branches for {email}: {e}", exc_info=True)
        raise

