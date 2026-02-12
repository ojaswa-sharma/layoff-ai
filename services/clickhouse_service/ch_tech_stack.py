"""
ClickHouse operations for repository tech stack data.

This module provides functions to store and retrieve tech stack information
(languages, topics) for repositories in ClickHouse.
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func
from models.ch_models import RepositoryTechStackCH

logger = logging.getLogger(__name__)


async def insert_or_update_tech_stack_ch(
    session: Session,
    repository_full_name: str,
    repository_name: str,
    installation_id: int,
    languages: Optional[Dict[str, int]] = None,
    topics: Optional[list[str]] = None,
    source: str = "github",
) -> bool:
    try:

        repository_full_name = repository_full_name or ""
        repository_name = repository_name or repository_full_name.split("/")[-1]
        source = source
        languages = languages or {}
        topics = topics or []

        tech_stack_dict = {
            "repository_full_name": repository_full_name,
            "installation_id": installation_id,
            "repository_name": repository_name,
            "languages": languages,
            "topics": topics,
            "last_updated": datetime.now(timezone.utc),
            "source": source,
        }

        print("==============================================")
        print("==============================================")
        print("tech_stack_dict: ", tech_stack_dict)
        print("==============================================")
        print("==============================================")

        tech_stack_ch = RepositoryTechStackCH.from_dict(tech_stack_dict)

        session.add(tech_stack_ch)
        session.commit()

        logger.info(f"Inserted tech stack for {repository_full_name}")
        return True

    except Exception as e:
        session.rollback()
        logger.error(f"Error inserting tech stack for {repository_full_name}: {e}", exc_info=True)
        return False



async def get_tech_stack_ch(
    session: Session,
    repository_full_name: str,
    installation_id: int,
) -> Optional[Dict[str, Any]]:
    """
    Retrieve tech stack data from ClickHouse.
    
    Args:
        session: SQLAlchemy ClickHouse session
        repository_full_name: Repository full name (owner/repo)
        installation_id: Installation/workspace ID
    
    Returns:
        Dictionary with tech stack data, or None if not found
    """
    try:
        tech_stack = session.query(RepositoryTechStackCH).filter(
            RepositoryTechStackCH.repository_full_name == repository_full_name,
            RepositoryTechStackCH.installation_id == installation_id,
        ).first()
        
        if tech_stack:
            return tech_stack.to_dict()
        return None
    except Exception as e:
        logger.error(f"Error retrieving tech stack for {repository_full_name}: {e}", exc_info=True)
        return None

