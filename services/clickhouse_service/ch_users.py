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
import asyncio
import orjson


logger = logging.getLogger(__name__)


def _parse_changes_json(changes_str: Optional[str]) -> Dict[str, int]:
    """Parse changes JSON string and return additions/deletions."""
    if not changes_str:
        return {"additions": 0, "deletions": 0}
    
    try:
        changes_dict = orjson.loads(changes_str)
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

async def list_users_paginated_ch(session, page: int = 1, limit: int = 10, search: str = None, order_by="author", order_dir="ASC", _session = None):
    skip = (page - 1) * limit

    VALID_ORDER_BY = {"author", "email", "total_additions", "total_removed", "total_commits", "last_commit"}
    VALID_ORDER_DIR = {"ASC", "DESC"}

    if order_by not in VALID_ORDER_BY:
        order_by = "author"
    if order_dir.upper() not in VALID_ORDER_DIR:
        order_dir = "ASC"

    ORDER_BY_MAP = {
        "author":          "author",
        "email":           "email",
        "total_additions": "total_additions",
        "total_removed":   "total_deletions",
        "total_commits":   "total_commits",
        "last_commit":     "last_commit",
    }
    sql_order_col = ORDER_BY_MAP[order_by]

    having_clause = "HAVING match(author, :search)" if search is not None else ""

    count_query = text(f"""
        SELECT uniq(email) AS total_users
        FROM (
            SELECT
                email,
                anyMerge(author) AS author
            FROM user_repo_agg
            GROUP BY email
        )
        {"WHERE match(author, :search)" if search is not None else ""}
    """)

    if order_by in {"total_additions", "total_removed", "total_commits", "last_commit"}:
        data_query = text(f"""
            SELECT *
            FROM (
                SELECT
                    email,
                    any(author)           AS author,
                    sum(commit_count)     AS total_commits,
                    sum(repo_additions)   AS total_additions,
                    sum(repo_deletions)   AS total_deletions,
                    max(last_commit_date) AS last_commit,
                    groupArray((
                        repo_name,
                        commit_count,
                        repo_additions,
                        repo_deletions,
                        last_commit_date
                    )) AS projects
                FROM (
                    SELECT
                        email,
                        anyMerge(author)           AS author,
                        repo_name,
                        countMerge(commit_count)   AS commit_count,
                        sumMerge(total_additions)  AS repo_additions,
                        sumMerge(total_deletions)  AS repo_deletions,
                        maxMerge(last_commit_date) AS last_commit_date
                    FROM user_repo_agg
                    GROUP BY email, repo_name
                    {having_clause}
                ) AS per_repo
                GROUP BY email
            )
            ORDER BY {sql_order_col} {order_dir}
            LIMIT {limit} OFFSET {skip}
        """)
    else:
        data_query = text(f"""
            SELECT
                email,
                any(author)           AS author,
                max(last_commit_date) AS last_commit,
                groupArray((
                    repo_name,
                    commit_count,
                    repo_additions,
                    repo_deletions,
                    last_commit_date
                )) AS projects
            FROM (
                SELECT
                    email,
                    anyMerge(author)           AS author,
                    repo_name,
                    countMerge(commit_count)   AS commit_count,
                    sumMerge(total_additions)  AS repo_additions,
                    sumMerge(total_deletions)  AS repo_deletions,
                    maxMerge(last_commit_date) AS last_commit_date
                FROM user_repo_agg
                GROUP BY email, repo_name
                {having_clause}
            ) AS per_repo
            GROUP BY email
            ORDER BY {sql_order_col} {order_dir}
            LIMIT {limit} OFFSET {skip}
        """)

    params = {}
    if search is not None:
        params["search"] = f"(?i){search}"

    count_result_thread =  run_in_threadpool(session.execute, count_query, params)
    data_result_thread =  run_in_threadpool(_session.execute, data_query, params)
    count_result, data_result = await asyncio.gather(count_result_thread, data_result_thread)
    total_items = count_result.fetchone().total_users

    if total_items == 0:
        return {
            "page": page,
            "limit": limit,
            "total_items": 0,
            "total_pages": 0,
            "data": []
        }

    results = data_result.fetchall()

    total_pages = (total_items + limit - 1) // limit
    now = datetime.utcnow()
    data = []

    for r in results:
        repos = []

        for proj in r.projects:
            repo_name, commit_count, additions, deletions, last_commit_date = proj

            repo_hours = (now - last_commit_date).total_seconds() / 3600
            repo_status = "active" if repo_hours <= 6 else "idle" if repo_hours <= 24 else "inactive"

            repos.append({
                "repo_name": repo_name,
                "last_commit": last_commit_date.isoformat(),
                "repo_additions": additions,
                "repo_deletions": deletions,
                "activity_status": repo_status,
            })

        total_additions = sum(p[2] for p in r.projects)
        total_deletions = sum(p[3] for p in r.projects)
        total_commits   = sum(p[1] for p in r.projects)

        last_commit = r.last_commit
        hours = (now - last_commit).total_seconds() / 3600
        user_status = "active" if hours <= 6 else "idle" if hours <= 24 else "inactive"

        data.append({
            "email": r.email,
            "author": r.author,
            "repos": repos,
            "changes": {"additions": total_additions, "deletions": total_deletions},
            "total_commits": total_commits,
            "last_commit": last_commit.isoformat(),
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
        project_filter = project or ""

        commits_sql = text(f"""
            SELECT
                commit_hash,
                commit_title,
                commit_date,
                repo_name                                       AS repository_name,
                additions,
                deletions,
                department,
                work_type,
                work_category,
                commiters_performance                           AS performance,
                commit_summary,
                count() OVER ()                                 AS total_filtered_commits
            FROM commit_analysis
            WHERE email = :email
              AND (:project = '' OR repo_name = :project)
            ORDER BY commit_date DESC
            LIMIT {limit} OFFSET {offset}
        """)

        stats_sql = text("""
            SELECT
                groupUniqArrayIf((dimension_value, cnt), dimension_type = 'department')    AS departments,
                groupUniqArrayIf((dimension_value, cnt), dimension_type = 'work_type')     AS work_types,
                groupUniqArrayIf((dimension_value, cnt), dimension_type = 'work_category') AS real_vs_fake,
                groupUniqArrayIf((dimension_value, cnt), dimension_type = 'commit_hour')   AS commit_hours
            FROM (
                SELECT
                    dimension_type,
                    dimension_value,
                    countMerge(cnt_state) AS cnt
                FROM user_stats_agg
                WHERE email = :email
                GROUP BY dimension_type, dimension_value
            )
        """)

        projects_sql = text("""
                    SELECT
                        repo_name,
                        commit_count,
                        last_commit,
                        sum(commit_count) OVER () AS total_commits
                    FROM (
                        SELECT
                            repo_name,
                            countMerge(commit_count)   AS commit_count,
                            maxMerge(last_commit_date) AS last_commit
                        FROM user_repo_agg
                        WHERE email = :email
                        GROUP BY repo_name
                    )
                    ORDER BY last_commit DESC
                """)

        commit_rows = [
            row._mapping
            for row in (await run_in_threadpool(session.execute, commits_sql, {"email": email, "project": project_filter})).fetchall()
        ]
        stats_row = (await run_in_threadpool(session.execute, stats_sql, {"email": email})).fetchone()
        project_rows = (await run_in_threadpool(session.execute, projects_sql, {"email": email})).fetchall()

        if not commit_rows and not project_rows:
            return {
                "projects":            [],
                "stats":               {"departments": {}, "work_types": {}, "real_vs_fake": {}, "commit_hours": {}, "total_commits": 0},
                "pagination":          {"page": page, "limit": limit, "total_commits": 0},
                "commit_history":      [],
                "commits_per_project": {},
            }

        projects_list = [
            {
                "repository_name": r.repo_name,
                "commit_count":    r.commit_count,
                "last_commit":     make_aware(r.last_commit).isoformat() if r.last_commit else None,
            }
            for r in project_rows
        ]

        commits_per_project = {r.repo_name: r.commit_count for r in project_rows}

        s = stats_row._mapping if stats_row else {}
        stats = {
            "total_commits": project_rows[0].total_commits if project_rows else 0,
            "departments":   dict(s.get("departments",  [])),
            "work_types":    dict(s.get("work_types",   [])),
            "real_vs_fake":  dict(s.get("real_vs_fake", [])),
            "commit_hours":  dict(s.get("commit_hours", [])),
        }

        commit_history = [
            {
                "commit_hash":     r["commit_hash"],
                "commit_title":    r["commit_title"],
                "date":            make_aware(r["commit_date"]).isoformat() if r["commit_date"] else None,
                "repository_name": r["repository_name"],
                "department":      r["department"],
                "work_type":       r["work_type"],
                "work_category":   r["work_category"],
                "performance":     r["performance"],
                "additions":       r["additions"],
                "deletions":       r["deletions"],
                "commit_summary":  r["commit_summary"],
            }
            for r in commit_rows
        ]

        return {
            "projects":            projects_list,
            "stats":               stats,
            "pagination":          {"page": page, "limit": limit, "total_commits": commit_rows[0]["total_filtered_commits"] if commit_rows else 0},
            "commit_history":      commit_history,
            "commits_per_project": commits_per_project,
        }

    except Exception as e:
        logger.error(f"Error getting developer data from ClickHouse: {e}")
        return {"error": "Failed to fetch developer data"}