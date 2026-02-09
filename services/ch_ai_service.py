"""
ClickHouse AI service integration using SQLAlchemy ORM.

This module provides SQLAlchemy ORM-based storage for AI-generated commit analysis,
mirroring the MongoDB commit_summary collection functionality.
"""
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session
from models.ch_models import CommitAnalysisCH

logger = logging.getLogger(__name__)


async def check_commit_analysis_exists_ch(
    session: Session,
    commit_hash: str,
) -> bool:
    """
    Check if commit analysis already exists in ClickHouse.
    
    Args:
        session: SQLAlchemy session
        commit_hash: Commit hash to check
        
    Returns:
        True if analysis exists, False otherwise
    """
    try:
        count = session.query(CommitAnalysisCH).filter(
            CommitAnalysisCH.commit_hash == commit_hash,
        ).count()
        
        return count > 0
    except Exception as e:
        logger.error(f"Error checking commit analysis existence: {e}")
        return False


def insert_commit_analysis_ch(
    session: Session,
    analysis: Dict[str, Any],
    commit_hash: Optional[str] = None,
    email: Optional[str] = None,
    repo_name: Optional[str] = None,
) -> bool:
    """
    Insert commit analysis into ClickHouse commit_analysis table using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        analysis: Dictionary with analysis results (from ai_service)
        commit_hash: Optional commit hash (will use from analysis if not provided)
        email: Optional email (will use from analysis if not provided)
        repo_name: Optional repo name (will use from analysis if not provided)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Use provided values or extract from analysis dict
        final_commit_hash = commit_hash or analysis.get("commit_hash")
        final_email = email or analysis.get("mail")
        final_repo_name = repo_name or analysis.get("repo_name")
        
        if not final_commit_hash:
            logger.warning("Cannot insert commit analysis: missing commit_hash")
            return False
        
        # Check if already exists (idempotency)
        # exists = await check_commit_analysis_exists_ch(session, final_commit_hash)
        exists = False
        if exists:
            logger.debug(f"Commit analysis for {final_commit_hash} already exists, skipping")
            return False
        
        # Create model instance from dictionary
        analysis_ch = CommitAnalysisCH.from_dict(analysis)
        # Override with provided values if given
        if commit_hash:
            analysis_ch.commit_hash = commit_hash
        if email:
            analysis_ch.email = email
        if repo_name:
            analysis_ch.repo_name = repo_name
        
        session.add(analysis_ch)
        session.commit()
        
        logger.debug(f"Inserted commit analysis for {final_commit_hash} into ClickHouse")
        return True
    except Exception as e:
        session.rollback()
        logger.error(f"Error inserting commit analysis into ClickHouse: {e}")
        return False


async def get_commit_analysis_ch(
    session: Session,
    commit_hash: str,
) -> Optional[Dict[str, Any]]:
    """
    Get commit analysis from ClickHouse using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        commit_hash: Commit hash to look up
        
    Returns:
        Dictionary with analysis results or None if not found
    """
    try:
        analysis = session.query(CommitAnalysisCH).filter(
            CommitAnalysisCH.commit_hash == commit_hash,
        ).first()
        
        if not analysis:
            return None
        
        return analysis.to_dict()
    except Exception as e:
        logger.error(f"Error getting commit analysis from ClickHouse: {e}")
        return None
