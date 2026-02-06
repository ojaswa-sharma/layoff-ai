from pymongo import MongoClient
import os
import logging

logger = logging.getLogger(__name__)

mongo_db = None

def ensure_index(collection, keys, name=None, **kwargs):
    existing = collection.index_information()

    if name and name in existing:
        return

    for idx_name, info in existing.items():
        if info.get("key") == keys:
            return
    collection.create_index(keys, name=name, **kwargs)

    print(f"Index added for {kwargs.get('name')}")

def init_mongo():
    global mongo_db
    client = MongoClient(os.getenv("MONGO_URL"))
    mongo_db = client["dev-tracker"]

    # Idempotency index
    ensure_index(
        mongo_db.commits,
        [
            ("repository_name", 1),
            ("commit_hash", 1),
            ("installation_id", 1),
        ],
        name="unique_commit_per_repo",
        unique=True
    )

    # Core aggregation indexes
    ensure_index(
        mongo_db.commits,
        [
            ("email", 1),
            ("repository_name", 1),
            ("date", -1),
        ],
        name="email_repo_date_idx"
    )

    ensure_index(
        mongo_db.commits,
        [
            ("email", 1),
            ("date", -1),
        ],
        name="email_date_idx"
    )

    # Repo uniqueness
    ensure_index(
        mongo_db.repositories,
        [
            ("repository_full_name", 1),
            ("installation_id", 1),
        ],
        name="unique_repo_per_installation",
        unique=True
    )

    logger.info("Mongo indexes initialized")

def get_mongo_db():
    global mongo_db
    yield mongo_db


