"""
SQLAlchemy setup for ClickHouse integration.

This module provides SQLAlchemy engine, session factory, and FastAPI dependency
for ClickHouse database operations using the clickhouse-sqlalchemy dialect.
"""
import os
import logging
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# SQLAlchemy declarative base for ClickHouse models
Base = declarative_base()

# Global engine and session factory
engine = None
SessionLocal = None


def init_ch_engine():
    """
    Initialize SQLAlchemy engine for ClickHouse.
    
    Uses environment variables:
    - CLICKHOUSE_HOST
    - CLICKHOUSE_PORT
    - CLICKHOUSE_USERNAME
    - CLICKHOUSE_PASSWORD
    - CLICKHOUSE_SECURE (True/False)
    
    Connection string format: clickhouse://[user[:password]@][host][:port][/database]
    """
    global engine, SessionLocal, Base
    
    try:
        host = os.getenv("CLICKHOUSE_HOST")
        port = os.getenv("CLICKHOUSE_PORT")
        username = os.getenv("CLICKHOUSE_USERNAME")
        password = os.getenv("CLICKHOUSE_PASSWORD")
        secure = os.getenv("CLICKHOUSE_SECURE", "False") == "True"
        
        # Build connection string
        # For secure connections, use clickhouses://
        # protocol = "clickhouses" if secure else "clickhouse"
        protocol= "clickhousedb"
        
        if password:
            connection_string = f"{protocol}://{username}:{password}@{host}:{port}/default"
        else:
            connection_string = f"{protocol}://{username}@{host}:{port}/default"
        
        # Create engine
        # Note: clickhouse-sqlalchemy may require specific parameters
        engine = create_engine(
            connection_string,
            echo=False,  # Set to True for SQL query logging
            pool_pre_ping=True,  # Verify connections before using
            connect_args={
                "secure": secure,
            }
        )

        Base.metadata.create_all(bind=engine)

        
        # Create session factory
        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine
        )
        
        logger.info("SQLAlchemy ClickHouse engine initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize SQLAlchemy ClickHouse engine: {e}")
        raise


def get_ch_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency to get SQLAlchemy session for ClickHouse.
    
    Yields a database session and ensures it's closed after use.
    Similar to get_mongo_db() pattern.
    
    Usage:
        @router.get("/endpoint")
        async def endpoint(session: Session = Depends(get_ch_session)):
            # Use session here
            pass
    """
    if SessionLocal is None:
        init_ch_engine()
    
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def get_ch_db():
    """
    Alias for get_ch_session() for backward compatibility.
    """
    return get_ch_session()
