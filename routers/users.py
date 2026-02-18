from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from dependencies.ch_db import get_ch_session
from services.clickhouse_service.ch_users import list_users_ch, list_users_paginated_ch, get_developer_ch
from services.clickhouse_service.ch_pr_query import get_prs_ch
from services.clickhouse_service.ch_branch_query import get_user_branches
from services.graphiti.graphiti_store import get_graphitit_personalizer
from fastapi.responses import ORJSONResponse
import logging
from datetime import datetime
from dependencies.auth import verify_auth_token
from models.orders import OrderBy, OrderDir

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix='/v1/users',
    # dependencies=[Depends(verify_auth_token)]
)

@router.get("/")
async def list_users(
    session: Session = Depends(get_ch_session),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
):
    """
    List all users with their repository statistics.
    
    Note: This endpoint returns all users without pagination.
    For paginated results, use /list endpoint.
    """
    try:
        users_data = await list_users_ch(session, page=page, limit=limit)
        return users_data
    except Exception as e:
        logger.error(f"Error listing users: {e}")
        return {"error": str(e)}

@router.get("/list")
async def list_users_paginated(
    session: Session = Depends(get_ch_session),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    search : str = Query(None),
    order_by : OrderBy = Query(OrderBy.email),
    order_dir : OrderDir = Query(OrderDir.asc)
):
    """
    List users with pagination and repository statistics.
    """
    try:
        result = await list_users_paginated_ch(session, page=page, limit=limit, search=search, order_by=order_by.value, order_dir=order_dir.value)
        return ORJSONResponse(content = result)
    except Exception as e:
        logger.error(f"Error listing paginated users: {e}")
        return {"error": str(e)}



@router.get("/developer/{email}")
async def get_developer(
    email: str,
    project: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    session: Session = Depends(get_ch_session),
):
    """
    Get detailed developer information including commit history, statistics, and AI-generated insights.
    """
    try:
        personalizer = get_graphitit_personalizer()

        project_data = None
        if project:
            project_data = await personalizer.get_project_data(
                graph_id=f"{email}_{project}"
            )

        dev_data = await get_developer_ch(
            session=session,
            email=email,
            project=project,
            page=page,
            limit=limit,
        )

        # tech_stack_data = await get_tech_stack_ch(
        #     session=session,
        #     repository_full_name=dev_data.get("repository_full_name", ""),
        #     installation_id=dev_data.get("installation_id", 0),
        # )

        response = {
            "user_data": "TBD",
            "projects": dev_data.get("projects", []),
            "stats": dev_data.get("stats", {}),
            "pagination": dev_data.get("pagination", {}),
            "commit_history": dev_data.get("commit_history", []),
            # "tech_stack_data": tech_stack_data,
        }

        if project:
            response["project_data"] = project_data

        return ORJSONResponse(content=response)

    except Exception as e:
        logger.error(f"Error while getting developer data: {e}")
        return {"error": "Failed to fetch developer data"}


@router.get("/prs")
async def list_prs(
    session: Session = Depends(get_ch_session),
    repository_full_name: str = Query(None, description="Filter by repository full name (owner/repo)"),
    status: str = Query(None, description="Filter by PR status: open, closed, or merged"),
    created_by_email: str = Query(None, description="Filter by PR creator email"),
    date_from: str = Query(None, description="Filter PRs updated after this date (ISO format)"),
    date_to: str = Query(None, description="Filter PRs updated before this date (ISO format)"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Number of results per page"),
):
    """
    List pull requests with filtering and pagination.
    
    Returns PR data including:
    - PR number
    - Title
    - Project (repository name)
    - Status (open, closed, merged)
    - Created by (username and email)
    - Changes (additions and deletions)
    - Branch name
    - Last updated timestamp
    
    Query Parameters:
    - repository_full_name: Filter by repository (e.g., "owner/repo")
    - status: Filter by status ("open", "closed", "merged")
    - created_by_email: Filter by PR creator email (for searching PRs by user)
    - date_from: Filter PRs updated after this date (ISO 8601 format)
    - date_to: Filter PRs updated before this date (ISO 8601 format)
    - page: Page number (default: 1)
    - limit: Results per page (default: 20, max: 100)
    """
    try:
        # Parse date strings if provided
        date_from_dt = None
        date_to_dt = None
        
        if date_from:
            try:
                date_from_dt = datetime.fromisoformat(date_from.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date_from format. Use ISO 8601 format (e.g., 2026-02-17T05:47:25Z)"
                )
        
        if date_to:
            try:
                date_to_dt = datetime.fromisoformat(date_to.replace("Z", "+00:00"))
            except ValueError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid date_to format. Use ISO 8601 format (e.g., 2026-02-17T05:47:25Z)"
                )
        
        # Validate status if provided
        if status and status not in ["open", "closed", "merged"]:
            raise HTTPException(
                status_code=400,
                detail="Invalid status. Must be one of: open, closed, merged"
            )
        
        # Query PRs
        result = await get_prs_ch(
            session=session,
            repository_full_name=repository_full_name,
            status=status,
            created_by_email=created_by_email,
            date_from=date_from_dt,
            date_to=date_to_dt,
            page=page,
            limit=limit,
        )
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing PRs: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error querying PRs: {str(e)}")


@router.get("/{email}/branches")
async def get_user_branch_analytics(
    email: str,
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Results per page"),
    session: Session = Depends(get_ch_session),
):
    """
    Get branch analytics for a specific user.
    
    Returns branch information including:
    - branch_name: Name of the branch
    - repository_full_name: Full repository name (owner/repo)
    - commit_count: Number of commits by this user on this branch
    - last_commit_date: Date and time of the most recent commit
    """
    try:
        result = await get_user_branches(
            session=session,
            email=email,
            page=page,
            limit=limit,
        )
        return result
    except Exception as e:
        logger.error(f"Error fetching branch analytics for {email}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching branch analytics: {str(e)}")
