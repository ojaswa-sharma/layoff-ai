"""
SQLAlchemy setup for ClickHouse integration.
This module provides SQLAlchemy engine, session factory, and FastAPI dependency
for ClickHouse database operations using the clickhouse-sqlalchemy dialect.
"""
import os
import logging
from typing import Generator
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base
from clickhouse_sqlalchemy import get_declarative_base

from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

Base = get_declarative_base()

engine = None
SessionLocal = None

def add_materialized_change_columns(engine):
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                ALTER TABLE commits
                ADD COLUMN IF NOT EXISTS additions Int32
                MATERIALIZED JSONExtractInt(changes, 'additions')
            """))
            conn.execute(text("""
                ALTER TABLE commits
                ADD COLUMN IF NOT EXISTS deletions Int32
                MATERIALIZED JSONExtractInt(changes, 'deletions')
            """))

            result = conn.execute(text("""
                SELECT count(*) 
                FROM system.tables 
                WHERE database = 'default' AND name = 'user_repo_agg_mv'
            """))
            exists = result.fetchone()[0]
            if exists == 0:
                conn.execute(text("""
                    CREATE MATERIALIZED VIEW user_repo_agg_mv
                    TO user_repo_agg
                    AS
                    SELECT
                        email,
                        anyState(author) AS author,
                        repository_name AS repo_name,
                        countState() AS commit_count,
                        sumState(additions) AS total_additions,
                        sumState(deletions) AS total_deletions,
                        maxState(date) AS last_commit_date
                    FROM commits
                    GROUP BY email, repo_name
                """))

        logger.info("Materialized columns and view ensured successfully")
    except Exception as e:
        logger.warning(f"Could not add materialized columns/view: {e}")

def init_ch_engine():
    global engine, SessionLocal, Base
    
    try:
        host = os.getenv("CLICKHOUSE_HOST")
        port = os.getenv("CLICKHOUSE_PORT", "9440")
        username = os.getenv("CLICKHOUSE_USERNAME", "default")
        password = os.getenv("CLICKHOUSE_PASSWORD")
        database = os.getenv("CLICKHOUSE_DATABASE", "default")
        secure = os.getenv("CLICKHOUSE_SECURE", "True") == "True"
        compression = os.getenv("CLICKHOUSE_COMPRESSION", "True") == "True"
        
        protocol = "clickhouse+native"
        
        if password:
            base_url = f"{protocol}://{username}:{password}@{host}:{port}/{database}"
        else:
            base_url = f"{protocol}://{username}@{host}:{port}/{database}"
        
        query_params = []
        if secure:
            query_params.append("secure=True")
            query_params.append("verify=False")
        
        connection_string = base_url
        if query_params:
            connection_string = f"{base_url}?{'&'.join(query_params)}"
        
        logger.info(f"Connecting to: {protocol}://{username}:***@{host}:{port}/{database}?{','.join(query_params)}")
        
        engine = create_engine(
            connection_string,
            echo=False,
            pool_pre_ping=True,
            pool_size=50,
            max_overflow=5,
            pool_timeout=30,
            pool_recycle=3600,
        )
        
        logger.info("Testing connection...")
        # with engine.connect() as conn:
        #     result = conn.execute(text("SELECT 1"))
        #     result.fetchone()
        # logger.info("Connection test successful")
        
        Base.metadata.create_all(bind=engine)
        
        add_materialized_change_columns(engine)
        
        SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=engine,
            expire_on_commit=False
        )
        
        logger.info(f"SQLAlchemy ClickHouse engine initialized successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize SQLAlchemy ClickHouse engine: {e}", exc_info=True)
        raise

def get_ch_session() -> Generator[Session, None, None]:
    """
    FastAPI dependency to get SQLAlchemy session for ClickHouse.
    Yields a database session and ensures it's closed after use.
    
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

def get_ch_session_direct() -> Session:
    """
    Get a ClickHouse session directly (not as a generator).
    Remember to close the session manually when done.
    """
    if SessionLocal is None:
        init_ch_engine()
    return SessionLocal()


REPOPULATE = """
INSERT INTO user_repo_agg
SELECT
    email,
    repository_name AS repo_name,
    anyState(author) AS author,
    countState() AS commit_count,
    sumState(additions) AS total_additions,
    sumState(deletions) AS total_deletions,
    maxState(date) AS last_commit_date
FROM commits
GROUP BY email, repository_name;

"""