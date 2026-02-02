from fastapi import APIRouter, Depends, Query
from services.db import get_mongo_db
from datetime import datetime, timezone, timedelta
from pymongo import DESCENDING
from services.zep_store import get_personalizer


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

        for doc in results:
            email = doc["_id"]["email"]
            repo_name = doc["_id"]["repo_name"]
            last_commit = doc["last_commit_date"]

            if last_commit.tzinfo is None:
                last_commit = last_commit.replace(tzinfo=timezone.utc)

            delta_hours = (now - last_commit).total_seconds() / 3600
            if delta_hours <= 6:
                status = "active"
            elif delta_hours <= 24:
                status = "idle"
            else:
                status = "inactive"


            if email not in users_data:
                users_data[email] = {
                    "email": email,
                    "repos": [],
                    "changes" : {
                        "additions" : 0,
                        "deletions" : 0
                    },
                    "status" : "inactive"
                }

            users_data[email]["repos"].append({
                "repo_name": repo_name,
                "last_commit": last_commit,
                "repo_additions": doc["total_additions"],
                "repo_deletions": doc["total_deletions"],
                "activity_status": status,
            })
            users_data[email]["changes"]["additions"] += doc["total_additions"]
            users_data[email]["changes"]["deletions"] += doc["total_deletions"]
            if users_data[email]["status"] == "inactive":
                users_data[email]["status"] = status
            elif users_data[email]["status"] == "idle" and status == "active":
                users_data[email]["status"] = status

        return list(users_data.values())

    except Exception as e:
        return {"error": str(e)}


@router.get('/developer/{email}')
async def get_developer(
    email: str,
    project: str | None = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=50),
    db=Depends(get_mongo_db),
):
    try:
        personalizer = get_personalizer()

        user_data = await personalizer.get_user_persona(
            user_id=f"user_{email}"
        )

        project_data = None
        if project:
            project_data = await personalizer.get_project_data(
                graph_id=f"{email}_{project}"
            )

        commits_col = db["commits"]
        summaries_col = db["commit_summary"]

        match_stage = {
            "email": email
        }
        if project:
            match_stage["repository_name"] = project

        skip = (page - 1) * limit

        pipeline = [
            {"$match": match_stage},

            {
                "$lookup": {
                    "from": "commit_summary",
                    "localField": "commit_hash",
                    "foreignField": "commit_hash",
                    "as": "summary"
                }
            },
            {"$unwind": {"path": "$summary", "preserveNullAndEmptyArrays": True}},

            {
                "$facet": {
                    "commits": [
                        {"$sort": {"date": -1}},
                        {"$skip": skip},
                        {"$limit": limit},
                        {
                            "$project": {
                                "_id": 0,
                                "commit_hash": 1,
                                "commit_title": "$message",
                                "date": 1,
                                "repository_name": 1,
                                "department": "$summary.department",
                                "work_type": "$summary.work_type",
                                "work_category": "$summary.work_category",
                                "performance": "$summary.commiters_performance",
                                "additions": "$changes.additions",
                                "deletions": "$changes.deletions",
                                "commit_summary" : "$summary.commit_summmary"
                            }
                        }
                    ],

                    "department_counts": [
                        {
                            "$group": {
                                "_id": "$summary.department",
                                "count": {"$sum": 1}
                            }
                        }
                    ],

                    "work_type_counts": [
                        {
                            "$group": {
                                "_id": "$summary.work_type",
                                "count": {"$sum": 1}
                            }
                        }
                    ],

                    "real_vs_fake": [
                        {
                            "$group": {
                                "_id": "$summary.work_category",
                                "count": {"$sum": 1}
                            }
                        }
                    ],

                    "total_commits": [
                        {"$count": "count"}
                    ]
                }
            }
        ]

        result = list(commits_col.aggregate(pipeline))[0]

        return {
            "user_data": user_data,
            "project_data": project_data,

            "stats": {
                "departments": {
                    d["_id"]: d["count"]
                    for d in result["department_counts"] if d["_id"]
                },
                "work_types": {
                    w["_id"]: w["count"]
                    for w in result["work_type_counts"] if w["_id"]
                },
                "real_vs_fake": {
                    r["_id"]: r["count"]
                    for r in result["real_vs_fake"] if r["_id"]
                },
                "total_commits": (
                    result["total_commits"][0]["count"]
                    if result["total_commits"] else 0
                )
            },

            "pagination": {
                "page": page,
                "limit": limit
            },

            "commit_history": result["commits"]
        }

    except Exception as e:
        print(f"[ERROR] Error while getting developer data: {e}")
        return {"error": "Failed to fetch developer data"}
