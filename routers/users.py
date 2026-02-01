from fastapi import APIRouter, Depends
from services.db import get_mongo_db
from datetime import datetime, timezone, timedelta
from pymongo import DESCENDING

router = APIRouter(prefix='/v1/users')

@router.get('/')
async def list_users(db = Depends(get_mongo_db)):
    try:
        commits_collection = db['commits']

        pipeline = [
            {
                "$group": {
                    "_id": {
                        "email": "$email",
                        "repo_name": "$repository_name"
                    },
                    "last_commit_date": {"$max": "$date"},
                    "total_additions": {"$sum": "$changes.additions"},
                    "total_deletions": {"$sum": "$changes.deletions"},
                    "commit_count": {"$sum": 1}
                }
            },
            {
                "$sort": {"_id.email": 1, "last_commit_date": DESCENDING}
            }
        ]

        results = list(commits_collection.aggregate(pipeline))
        now = datetime.now(timezone.utc)

        users_data = {}
        now = datetime.now(timezone.utc)
        overall_negs = 0
        overall_plus = 0
        overall_status = "inactive"
        for doc in results:
            email = doc["_id"]["email"]
            repo_name = doc["_id"]["repo_name"]
            last_commit = doc["last_commit_date"]

            if last_commit.tzinfo is None:
                last_commit = last_commit.replace(tzinfo=timezone.utc)

            delta_hours = (now - last_commit).total_seconds() / 3600
            if delta_hours <= 6:
                status = "active"
                overall_status = "active"
            elif delta_hours <= 24:
                status = "idle"
                if overall_status != "active":
                    overall_status = "idle"
            else:
                status = "inactive"


            if email not in users_data:
                users_data[email] = {
                    "email": email,
                    "repos": []
                }
            overall_negs += int(doc["total_deletions"] or 0)
            overall_plus += int(doc["total_additions"] or 0)

            users_data[email]["repos"].append({
                "repo_name": repo_name,
                "last_commit": last_commit,
                "total_additions": doc["total_additions"],
                "total_deletions": doc["total_deletions"],
                "activity_status": status
            })

        return {"user_data" : users_data.values(), "overall" : {"additions" : overall_plus, "neg" : overall_negs, "status" : overall_status}}

    except Exception as e:
        return {"error": str(e)}
