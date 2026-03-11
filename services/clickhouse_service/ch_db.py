"""
ClickHouse database initialization and setup using SQLAlchemy.

This module handles ClickHouse connection initialization using SQLAlchemy.
Note: ClickHouse tables are assumed to already exist:
- commits
- pr_merges
- commit_analysis
- repo_sync_events
"""
import logging
from dependencies.ch_db import init_ch_engine

logger = logging.getLogger(__name__)


def init_ch():
    """
    Initialize ClickHouse connection using SQLAlchemy.
    
    This function initializes the SQLAlchemy engine and session factory.
    Unlike MongoDB, ClickHouse doesn't support unique constraints,
    so idempotency must be handled at the application level.
    """
    try:
        init_ch_engine()
        logger.info("ClickHouse SQLAlchemy initialization completed")
    except Exception as e:
        logger.error(f"ClickHouse SQLAlchemy initialization failed: {e}")
        raise
