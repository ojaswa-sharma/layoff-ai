from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from dependencies.ch_db import get_ch_session
# from services.zep_store import get_personalizer
from services.clickhouse_service.ch_users import list_users_ch, list_users_paginated_ch, get_developer_ch
from services.graphiti.graphiti_store import get_graphitit_personalizer
import logging
from dependencies.auth import verify_auth_token

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix='/v1/users',
    dependencies=[Depends(verify_auth_token)]
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
):
    """
    List users with pagination and repository statistics.
    """
    try:
        result = await list_users_paginated_ch(session, page=page, limit=limit)
        return result
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
        # personalizer = get_personalizer()
        personalizer = get_graphitit_personalizer()

        # user_data = await personalizer.get_user_persona(
        #     user_id=f"user_{email}"
        # )

        project_data = None
        if project:
            project_data = await personalizer.get_project_data(
                graph_id=f"{email}_{project}"
            )

        # Get developer data from ClickHouse
        dev_data = await get_developer_ch(
            session=session,
            email=email,
            project=project,
            page=page,
            limit=limit,
        )

        # Build response matching the original format
        response = {
            "user_data": "TBD",
            "projects": dev_data.get("projects", []),
            "stats": dev_data.get("stats", {}),
            "pagination": dev_data.get("pagination", {}),
            "commit_history": dev_data.get("commit_history", []),
        }

        if project:
            response["project_data"] = project_data

        return response

    except Exception as e:
        logger.error(f"Error while getting developer data: {e}")
        return {"error": "Failed to fetch developer data"}
