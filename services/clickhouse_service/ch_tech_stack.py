"""
ClickHouse operations for repository tech stack data.

This module provides functions to store and retrieve tech stack information
(languages, topics) for repositories in ClickHouse.
"""
import logging
from typing import Dict, Any, Optional
from datetime import datetime
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
    """
    Insert or update tech stack data in ClickHouse.
    
    Since ClickHouse MergeTree doesn't support UPDATE operations,
    this function deletes existing records and inserts new ones.
    
    Args:
        session: SQLAlchemy ClickHouse session
        repository_full_name: Repository full name (owner/repo)
        repository_name: Repository name only
        installation_id: Installation/workspace ID
        languages: Dictionary mapping language names to bytes of code
        topics: List of topic strings
        source: Source platform ("github" or "bitbucket")
    
    Returns:
        True if successful, False otherwise
    """
    try:
        # Delete existing record if it exists
        # ClickHouse doesn't support UPDATE, so we delete and re-insert
        existing = session.query(RepositoryTechStackCH).filter(
            RepositoryTechStackCH.repository_full_name == repository_full_name,
            RepositoryTechStackCH.installation_id == installation_id,
        ).first()
        
        if existing:
            session.delete(existing)
            session.commit()
        
        # Create new record
        tech_stack_dict = {
            "repository_full_name": repository_full_name,
            "installation_id": installation_id,
            "repository_name": repository_name,
            "languages": languages or {},
            "topics": topics or [],
            "last_updated": datetime.utcnow(),
            "source": source,
        }
        
        tech_stack_ch = RepositoryTechStackCH.from_dict(tech_stack_dict)
        session.add(tech_stack_ch)
        session.commit()
        
        logger.info(f"Inserted/updated tech stack for {repository_full_name}")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error inserting/updating tech stack for {repository_full_name}: {e}", exc_info=True)
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

