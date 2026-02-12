"""
ClickHouse user query operations using SQLAlchemy ORM.

This module provides SQLAlchemy ORM-based implementations of user listing and
developer detail queries, converting MongoDB aggregation pipelines to ORM queries.
"""
import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from sqlalchemy import func, and_, or_, text
from models.ch_models import CommitCH, CommitAnalysisCH, UserRepoAggregate
from sqlalchemy import func, select, literal_column, case
from datetime import datetime, timezone
from fastapi.concurrency import run_in_threadpool


logger = logging.getLogger(__name__)


def _parse_changes_json(changes_str: Optional[str]) -> Dict[str, int]:
    """Parse changes JSON string and return additions/deletions."""
    if not changes_str:
        return {"additions": 0, "deletions": 0}
    
    try:
        changes_dict = json.loads(changes_str)
        return {
            "additions": changes_dict.get("additions", 0) or 0,
            "deletions": changes_dict.get("deletions", 0) or 0,
        }
    except:
        return {"additions": 0, "deletions": 0}


async def list_users_ch(
    session: Session,
    page: int = 1,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """
    List users with their repository statistics using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        page: Page number (not used in this implementation, returns all)
        limit: Limit results (not used in this implementation, returns all)
        
    Returns:
        List of user dictionaries with repository statistics
    """
    try:
        results = session.query(
            CommitCH.email,
            CommitCH.repository_name,
            func.max(CommitCH.date).label('last_commit_date'),
        ).filter(
            CommitCH.changes.isnot(None),
            CommitCH.changes != '',
        ).group_by(
            CommitCH.email,
            CommitCH.repository_name,
        ).order_by(
            CommitCH.email,
            func.max(CommitCH.date).desc(),
        ).all()
        
        all_commits = session.query(
            CommitCH.email,
            CommitCH.repository_name,
            CommitCH.changes,
        ).filter(
            CommitCH.changes.isnot(None),
            CommitCH.changes != '',
        ).all()
        
        changes_by_repo = {}
        commit_counts_by_repo = {}
        for commit in all_commits:
            key = (commit.email, commit.repository_name)
            if key not in changes_by_repo:
                changes_by_repo[key] = {"additions": 0, "deletions": 0}
                commit_counts_by_repo[key] = 0
            changes = _parse_changes_json(commit.changes)
            changes_by_repo[key]["additions"] += changes["additions"]
            changes_by_repo[key]["deletions"] += changes["deletions"]
            commit_counts_by_repo[key] += 1
        
        now = datetime.now(timezone.utc)
        users_data = {}
        
        for row in results:
            email = row.email
            repo_name = row.repository_name
            last_commit = row.last_commit_date
            changes = changes_by_repo.get((email, repo_name), {"additions": 0, "deletions": 0})
            
            total_additions = changes["additions"]
            total_deletions = changes["deletions"]
            
            if isinstance(last_commit, datetime):
                if last_commit.tzinfo is None:
                    last_commit = last_commit.replace(tzinfo=timezone.utc)
            else:
                try:
                    last_commit = datetime.fromisoformat(str(last_commit))
                    if last_commit.tzinfo is None:
                        last_commit = last_commit.replace(tzinfo=timezone.utc)
                except:
                    last_commit = now
            
            delta_hours = (now - last_commit).total_seconds() / 3600
            if delta_hours <= 6:
                status = "active"
            elif delta_hours <= 24:
                status = "idle"
            else:
                status = "inactive"
            
            repo_commits = commit_counts_by_repo.get((email, repo_name), 0)
            
            if email not in users_data:
                users_data[email] = {
                    "email": email,
                    "repos": [],
                    "changes": {
                        "additions": 0,
                        "deletions": 0,
                    },
                    "status": "inactive",
                    "total_commits": 0,
                }
            
            users_data[email]["repos"].append({
                "repo_name": repo_name,
                "last_commit": last_commit.isoformat() if isinstance(last_commit, datetime) else str(last_commit),
                "repo_additions": total_additions,
                "repo_deletions": total_deletions,
                "activity_status": status,
            })
            users_data[email]["changes"]["additions"] += total_additions
            users_data[email]["changes"]["deletions"] += total_deletions
            users_data[email]["total_commits"] += repo_commits
            
            if users_data[email]["status"] == "inactive":
                users_data[email]["status"] = status
            elif users_data[email]["status"] == "idle" and status == "active":
                users_data[email]["status"] = status
        
        return list(users_data.values())
        
    except Exception as e:
        logger.error(f"Error listing users from ClickHouse: {e}")
        return []

def aggregate(session, user_agg):
    
    return session.execute(user_agg).fetchall()

async def list_users_paginated_ch(session, page: int = 1, limit: int = 10, search : str = None, order_by = "author", order_dir = "ASC"):
    skip = (page - 1) * limit

    base_query = f"""
    SELECT
        email,
        projects,
        total_users
    FROM (
        SELECT
            email,
            groupArray(
                (
                    repo_name,
                    author,
                    commit_count,
                    total_additions,
                    total_deletions,
                    last_commit_date
                )
            ) AS projects,
            count(*) OVER() AS total_users
        FROM (
            SELECT
                email,
                repo_name,
                anyMerge(author) AS author,
                countMerge(commit_count) AS commit_count,
                sumMerge(total_additions) AS total_additions,
                sumMerge(total_deletions) AS total_deletions,
                maxMerge(last_commit_date) AS last_commit_date
            FROM user_repo_agg
            GROUP BY email, repo_name
        ) AS merged
    """

    if search is not None:
        base_query += " WHERE match(author, :search)"

    base_query += f"""
        GROUP BY email
        ORDER BY email
        LIMIT {limit} OFFSET {skip}
    ) AS final_users
    """

    query = text(base_query)
    params = {}
    if search is not None:
        params["search"] = f"(?i){search}"


    rows = await run_in_threadpool(session.execute, query, params)
    results = rows.fetchall()

    if not results:
        return {
            "page": page,
            "limit": limit,
            "total_items": 0,
            "total_pages": 0,
            "data": []
        }

    now = datetime.utcnow()
    data = []
    total_items = results[0].total_users
    total_pages = (total_items + limit - 1) // limit

    for r in results:
        email = r.email
        repos = []
        total_additions = 0
        total_deletions = 0
        total_commits = 0
        last_commit = None

        for proj in r.projects:
            repo_name, author, commit_count, additions, deletions, last_commit_date = proj
            total_additions += additions
            total_deletions += deletions
            total_commits += commit_count
            if not last_commit or last_commit_date > last_commit:
                last_commit = last_commit_date

            repo_hours = (now - last_commit_date).total_seconds() / 3600
            repo_status = "active" if repo_hours <= 6 else "idle" if repo_hours <= 24 else "inactive"

            repos.append({
                "repo_name": repo_name,
                "last_commit": last_commit_date.isoformat(),
                "repo_additions": additions,
                "repo_deletions": deletions,
                "activity_status": repo_status,
            })

        hours = (now - last_commit).total_seconds() / 3600
        user_status = "active" if hours <= 6 else "idle" if hours <= 24 else "inactive"

        data.append({
            "email": email,
            "author": r.projects[0][1],
            "repos": repos,
            "changes": {"additions": total_additions, "deletions": total_deletions},
            "total_commits": total_commits,
            "status": user_status
        })

    return {
        "page": page,
        "limit": limit,
        "total_items": total_items,
        "total_pages": total_pages,
        "data": data
    }

def make_aware(dt):
    """Convert naive datetime to UTC-aware datetime"""
    if dt and isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

async def get_developer_ch(
    session,
    email: str,
    project: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> Dict[str, Any]:

    try:
        offset = (page - 1) * limit
        project_param = project or ""

        sql = text(f"""
        WITH
            :email_param AS email_param,
            :project_param AS project_param

        SELECT
            ch.commit_hash AS commit_hash,
            ch.message AS commit_title,
            ch.date AS commit_date,
            ch.repository_name AS repository_name,
            ch.changes AS changes,

            ca.department AS department,
            ca.work_type AS work_type,
            ca.work_category AS work_category,
            ca.commiters_performance AS performance,
            ca.commit_summary AS commit_summary,

            totals.total_commits AS total_commits,
            stats.departments AS departments,
            stats.work_types AS work_types,
            stats.work_categories AS work_categories,
            projects.projects AS projects

        FROM
        (
            SELECT 
                commit_hash,
                message,
                date,
                repository_name,
                changes
            FROM commits
            WHERE email = email_param
              AND (project_param = '' OR repository_name = project_param)
            ORDER BY date DESC
            LIMIT {limit} OFFSET {offset}
        ) AS ch

        LEFT JOIN commit_analysis AS ca
            ON ch.commit_hash = ca.commit_hash
           AND ca.email = email_param

        CROSS JOIN
        (
            SELECT count() AS total_commits
            FROM commits
            WHERE email = email_param
              AND (project_param = '' OR repository_name = project_param)
        ) AS totals

        CROSS JOIN
        (
            SELECT
                groupArray((department, dept_count)) AS departments,
                groupArray((work_type, wt_count)) AS work_types,
                groupArray((work_category, wc_count)) AS work_categories
            FROM
            (
                SELECT department, count() AS dept_count,
                       NULL AS work_type, NULL AS wt_count,
                       NULL AS work_category, NULL AS wc_count
                FROM commit_analysis
                WHERE email = email_param
                GROUP BY department

                UNION ALL

                SELECT NULL, NULL,
                       work_type, count(),
                       NULL, NULL
                FROM commit_analysis
                WHERE email = email_param
                GROUP BY work_type

                UNION ALL

                SELECT NULL, NULL,
                       NULL, NULL,
                       work_category, count()
                FROM commit_analysis
                WHERE email = email_param
                GROUP BY work_category
            )
        ) AS stats

        CROSS JOIN
        (
            SELECT
                groupArray(
                    (
                        repo_name,
                        commit_count,
                        last_commit
                    )
                ) AS projects
            FROM
            (
                SELECT
                    repo_name,
                    countMerge(commit_count) AS commit_count,
                    maxMerge(last_commit_date) AS last_commit
                FROM user_repo_agg
                WHERE email = email_param
                  AND (project_param = '' OR repo_name = project_param)
                GROUP BY repo_name
                ORDER BY last_commit DESC
            )
        ) AS projects
        """)

        result = session.execute(
            sql,
            {
                "email_param": email,
                "project_param": project_param,
                "limit": limit,
                "offset": offset,
            },
        ).fetchall()

        if not result:
            return {
                "projects": [],
                "stats": {
                    "departments": {},
                    "work_types": {},
                    "real_vs_fake": {},
                    "total_commits": 0,
                },
                "pagination": {"page": page, "limit": limit},
                "commit_history": [],
            }

        first_row = result[0]._mapping

        # ---- Stats ----
        departments = {k: v for k, v in (first_row["departments"] or []) if k}
        work_types = {k: v for k, v in (first_row["work_types"] or []) if k}
        real_vs_fake = {k: v for k, v in (first_row["work_categories"] or []) if k}

        # ---- Projects ----
        projects_list = []
        for repo_name, count, last_commit in first_row["projects"] or []:
            projects_list.append({
                "repository_name": repo_name,
                "commit_count": count,
                "last_commit": (
                    make_aware(last_commit).isoformat()
                    if last_commit else None
                ),
            })

        # ---- Commit history ----
        commit_history = []
        for row in result:
            r = row._mapping
            changes = _parse_changes_json(r["changes"])

            commit_history.append({
                "commit_hash": r["commit_hash"],
                "commit_title": r["commit_title"],
                "date": (
                    make_aware(r["commit_date"]).isoformat()
                    if r["commit_date"] else None
                ),
                "repository_name": r["repository_name"],
                "department": r["department"],
                "work_type": r["work_type"],
                "work_category": r["work_category"],
                "performance": r["performance"],
                "additions": changes["additions"],
                "deletions": changes["deletions"],
                "commit_summary": r["commit_summary"],
            })

        return {
            "projects": projects_list,
            "stats": {
                "departments": departments,
                "work_types": work_types,
                "real_vs_fake": real_vs_fake,
                "total_commits": first_row["total_commits"],
            },
            "pagination": {"page": page, "limit": limit},
            "commit_history": commit_history,
        }

    except Exception as e:
        logger.error(f"Error getting developer data from ClickHouse: {e}")
        return {"error": "Failed to fetch developer data"}
