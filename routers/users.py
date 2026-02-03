from fastapi import APIRouter, Depends, Query
from services.db import get_mongo_db
from datetime import datetime, timezone, timedelta
from pymongo import DESCENDING
from services.zep_store import get_personalizer


router = APIRouter(prefix='/v1/users')

@router.get("/")
async def list_users(db=Depends(get_mongo_db), page=1, limit=10):
    try:
        commits_collection = db["commits"]

        pipeline = [
            # 1️⃣ Repo-level aggregation
            {
                "$group": {
                    "_id": {
                        "email": "$email",
                        "repo_name": "$repository_name"
                    },
                    "last_commit": {"$max": "$date"},
                    "repo_additions": {"$sum": "$changes.additions"},
                    "repo_deletions": {"$sum": "$changes.deletions"},
                    "repo_commits": {"$sum": 1}
                }
            },
            # 2️⃣ User-level aggregation (THIS is the key optimization)
            {
                "$group": {
                    "_id": "$_id.email",
                    "repos": {
                        "$push": {
                            "repo_name": "$_id.repo_name",
                            "last_commit": "$last_commit",
                            "repo_additions": "$repo_additions",
                            "repo_deletions": "$repo_deletions",
                            "repo_commits": "$repo_commits"
                        }
                    },
                    "total_additions": {"$sum": "$repo_additions"},
                    "total_deletions": {"$sum": "$repo_deletions"},
                    "total_commits": {"$sum": "$repo_commits"},
                    "last_commit": {"$max": "$last_commit"}
                }
            },
            {
                "$sort": {"_id": 1}
            }
        ]

        results = list(commits_collection.aggregate(pipeline))
        now = datetime.now(timezone.utc)

        users_data = []

        for doc in results:
            last_commit = doc["last_commit"]
            if last_commit.tzinfo is None:
                last_commit = last_commit.replace(tzinfo=timezone.utc)

            delta_hours = (now - last_commit).total_seconds() / 3600
            if delta_hours <= 6:
                user_status = "active"
            elif delta_hours <= 24:
                user_status = "idle"
            else:
                user_status = "inactive"

            repos = []
            for repo in doc["repos"]:
                repo_last_commit = repo["last_commit"]
                if repo_last_commit.tzinfo is None:
                    repo_last_commit = repo_last_commit.replace(tzinfo=timezone.utc)

                repo_delta = (now - repo_last_commit).total_seconds() / 3600
                if repo_delta <= 6:
                    repo_status = "active"
                elif repo_delta <= 24:
                    repo_status = "idle"
                else:
                    repo_status = "inactive"

                repos.append({
                    "repo_name": repo["repo_name"],
                    "last_commit": repo_last_commit,
                    "repo_additions": repo["repo_additions"],
                    "repo_deletions": repo["repo_deletions"],
                    "activity_status": repo_status
                })

            users_data.append({
                "email": doc["_id"],
                "repos": repos,
                "changes": {
                    "additions": doc["total_additions"],
                    "deletions": doc["total_deletions"]
                },
                "status": user_status,
                "total_commits": doc["total_commits"]
            })

        return users_data

    except Exception as e:
        return {"error": str(e)}


@router.get("/developer/{email}")
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

        commits_col = db["commits"]

        match_stage = {"email": email}
        project_data = None

        if project:
            match_stage["repository_name"] = project
            project_data = await personalizer.get_project_data(
                graph_id=f"{email}_{project}"
            )

        skip = (page - 1) * limit

        pipeline = [
            {"$match": match_stage},

            {
                "$lookup": {
                    "from": "commit_summary",
                    "localField": "commit_hash",
                    "foreignField": "commit_hash",
                    "as": "summary",
                }
            },
            {
                "$unwind": {
                    "path": "$summary",
                    "preserveNullAndEmptyArrays": True,
                }
            },

            {
                "$facet": {
                    # ---------------- COMMITS (paginated) ----------------
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
                                "commit_summary": "$summary.commit_summmary",
                            }
                        },
                    ],

                    # ---------------- PROJECT LIST ----------------
                    "projects": [
                        {
                            "$group": {
                                "_id": "$repository_name",
                                "commit_count": {"$sum": 1},
                                "last_commit": {"$max": "$date"},
                            }
                        },
                        {"$sort": {"last_commit": -1}},
                        {
                            "$project": {
                                "_id": 0,
                                "repository_name": "$_id",
                                "commit_count": 1,
                                "last_commit": 1,
                            }
                        },
                    ],

                    # ---------------- STATS ----------------
                    "department_counts": [
                        {
                            "$group": {
                                "_id": "$summary.department",
                                "count": {"$sum": 1},
                            }
                        }
                    ],

                    "work_type_counts": [
                        {
                            "$group": {
                                "_id": "$summary.work_type",
                                "count": {"$sum": 1},
                            }
                        }
                    ],

                    "real_vs_fake": [
                        {
                            "$group": {
                                "_id": "$summary.work_category",
                                "count": {"$sum": 1},
                            }
                        }
                    ],

                    "total_commits": [
                        {"$count": "count"}
                    ],
                }
            },
        ]

        result = list(commits_col.aggregate(pipeline))[0]

        response = {
            "user_data": user_data,

            "projects": result["projects"],

            "stats": {
                "departments": {
                    d["_id"]: d["count"]
                    for d in result["department_counts"]
                    if d["_id"]
                },
                "work_types": {
                    w["_id"]: w["count"]
                    for w in result["work_type_counts"]
                    if w["_id"]
                },
                "real_vs_fake": {
                    r["_id"]: r["count"]
                    for r in result["real_vs_fake"]
                    if r["_id"]
                },
                "total_commits": (
                    result["total_commits"][0]["count"]
                    if result["total_commits"]
                    else 0
                ),
            },

            "pagination": {
                "page": page,
                "limit": limit,
            },

            "commit_history": result["commits"],
        }

        if project:
            response["project_data"] = project_data

        return response

    except Exception as e:
        print(f"[ERROR] Error while getting developer data: {e}")
        return {"error": "Failed to fetch developer data"}
