from pymongo import MongoClient
import os
import logging

logger = logging.getLogger(__name__)

mongo_db = None

def init_mongo():
    """
    Initialize MongoDB connection and create necessary indexes.
    
    Creates unique indexes to ensure idempotency:
    - commits: (repository_name, commit_hash, installation_id)
    - repositories: (repository_full_name, installation_id)
    """
    global mongo_db
    client = MongoClient(host=os.getenv("MONGO_URL"))
    mongo_db = client["dev-tracker"]
    
    # Create unique index on commits for idempotency
    # This prevents duplicate commits from being inserted
    try:
        mongo_db.commits.create_index(
            [
                ("repository_name", 1),
                ("commit_hash", 1),
                ("installation_id", 1),
            ],
            unique=True,
            name="unique_commit_per_repo",
        )
        logger.info("Created unique index on commits collection")
    except Exception as e:
        logger.warning(f"Index creation (may already exist): {e}")
    
    # Create unique index on repositories
    try:
        mongo_db.repositories.create_index(
            [
                ("repository_full_name", 1),
                ("installation_id", 1),
            ],
            unique=True,
            name="unique_repo_per_installation",
        )
        logger.info("Created unique index on repositories collection")
    except Exception as e:
        logger.warning(f"Index creation (may already exist): {e}")
    
    # Create index for faster queries
    try:
        mongo_db.commits.create_index([("installation_id", 1)])
        mongo_db.commits.create_index([("repository_name", 1)])
        mongo_db.commits.create_index([("date", -1)])  # For date-based queries
        logger.info("Created additional indexes on commits collection")
    except Exception as e:
        logger.warning(f"Index creation (may already exist): {e}")

def get_mongo_db():
    global mongo_db
    yield mongo_db


