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
from sqlalchemy import func, and_, or_
from models.ch_models import CommitCH, CommitAnalysisCH
from sqlalchemy import func, select, literal_column

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
        # SQLAlchemy ORM query equivalent of MongoDB aggregation
        # Note: We need to process changes in Python since ClickHouse stores JSON as string
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
        
        # Get all commits to calculate additions/deletions
        all_commits = session.query(
            CommitCH.email,
            CommitCH.repository_name,
            CommitCH.changes,
        ).filter(
            CommitCH.changes.isnot(None),
            CommitCH.changes != '',
        ).all()
        
        # Aggregate changes by email and repo
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
            
            # Handle timezone-aware datetime
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



async def list_users_paginated_ch(session, page: int = 1, limit: int = 10):

    skip = (page - 1) * limit

    # additions = func.JSONExtractInt(CommitCH.changes, 'additions')
    # deletions = func.JSONExtractInt(CommitCH.changes, 'deletions')
    additions = CommitCH.additions
    deletions = CommitCH.deletions


    # Repo level aggregation
    repo_agg = (
        select(
            CommitCH.email.label("email"),
            CommitCH.repository_name.label("repo_name"),
            func.max(CommitCH.date).label("repo_last_commit"),
            func.sum(additions).label("repo_additions"),
            func.sum(deletions).label("repo_deletions"),
            func.count().label("repo_commits"),
        )
        .where(
            CommitCH.changes.isnot(None),
            CommitCH.changes != ''
        )
        .group_by(
            CommitCH.email,
            CommitCH.repository_name,
        )
        .subquery()
    )

    # User level aggregation + repo arrays
    user_agg = (
        select(
            repo_agg.c.email,
            func.max(repo_agg.c.repo_last_commit).label("last_commit"),
            func.sum(repo_agg.c.repo_additions).label("total_additions"),
            func.sum(repo_agg.c.repo_deletions).label("total_deletions"),
            func.sum(repo_agg.c.repo_commits).label("total_commits"),

            # Build repo objects directly in CH
            func.groupArray(
                func.map(
                    literal_column("'repo_name'"), repo_agg.c.repo_name,
                    literal_column("'last_commit'"), repo_agg.c.repo_last_commit,
                    literal_column("'repo_additions'"), repo_agg.c.repo_additions,
                    literal_column("'repo_deletions'"), repo_agg.c.repo_deletions,
                )
            ).label("repos"),

            # Total users count (window)
            func.count().over().label("total_items")
        )
        .group_by(repo_agg.c.email)
        .order_by(repo_agg.c.email)
        .offset(skip)
        .limit(limit)
    )

    rows = session.execute(user_agg).fetchall()

    if not rows:
        return {
            "page": page,
            "limit": limit,
            "total_items": 0,
            "total_pages": 0,
            "data": []
        }

    total_items = rows[0].total_items
    total_pages = (total_items + limit - 1) // limit

    now = datetime.now(timezone.utc)

    data = []
    for r in rows:

        last_commit = r.last_commit
        hours = (now - last_commit).total_seconds() / 3600
        status = "active" if hours <= 6 else "idle" if hours <= 24 else "inactive"

        repos = []
        for repo in r.repos:
            repo_last = repo["last_commit"]
            repo_hours = (now - repo_last).total_seconds() / 3600
            repo_status = "active" if repo_hours <= 6 else "idle" if repo_hours <= 24 else "inactive"

            repos.append({
                "repo_name": repo["repo_name"],
                "last_commit": repo_last.isoformat(),
                "repo_additions": repo["repo_additions"],
                "repo_deletions": repo["repo_deletions"],
                "activity_status": repo_status
            })

        data.append({
            "email": r.email,
            "repos": repos,
            "changes": {
                "additions": r.total_additions,
                "deletions": r.total_deletions,
            },
            "status": status,
            "total_commits": r.total_commits,
        })

    return {
        "page": page,
        "limit": limit,
        "total_items": total_items,
        "total_pages": total_pages,
        "data": data,
    }


async def get_developer_ch(
    session: Session,
    email: str,
    project: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Get developer details with commit history and statistics using SQLAlchemy ORM.
    
    Args:
        session: SQLAlchemy session
        email: Developer email
        project: Optional project/repository name filter
        page: Page number for pagination
        limit: Number of commits per page
        
    Returns:
        Dictionary with developer data, projects, stats, and commit history
    """
    try:
        skip = (page - 1) * limit
        
        # Build filter conditions
        filters = [CommitCH.email == email]
        if project:
            filters.append(CommitCH.repository_name == project)
        
        # Get paginated commits with JOIN to commit_analysis
        commits_query = session.query(
            CommitCH.commit_hash,
            CommitCH.message.label('commit_title'),
            CommitCH.date,
            CommitCH.repository_name,
            CommitAnalysisCH.department,
            CommitAnalysisCH.work_type,
            CommitAnalysisCH.work_category,
            CommitAnalysisCH.commiters_performance.label('performance'),
            CommitCH.changes,
            CommitAnalysisCH.commit_summary,
        ).outerjoin(
            CommitAnalysisCH,
            CommitCH.commit_hash == CommitAnalysisCH.commit_hash,
        ).filter(
            *filters
        ).order_by(
            CommitCH.date.desc()
        ).offset(skip).limit(limit)
        
        commits_result = commits_query.all()
        
        commit_history = []
        for row in commits_result:
            changes = _parse_changes_json(row.changes)
            
            commit_history.append({
                "commit_hash": row.commit_hash,
                "commit_title": row.commit_title,
                "date": row.date.isoformat() if isinstance(row.date, datetime) else str(row.date),
                "repository_name": row.repository_name,
                "department": row.department,
                "work_type": row.work_type,
                "work_category": row.work_category,
                "performance": row.performance,
                "additions": changes["additions"],
                "deletions": changes["deletions"],
                "commit_summary": row.commit_summary,
            })
        
        # Get projects list
        projects_query = session.query(
            CommitCH.repository_name,
            func.count(CommitCH.commit_hash).label('commit_count'),
            func.max(CommitCH.date).label('last_commit'),
        ).filter(
            *filters
        ).group_by(
            CommitCH.repository_name
        ).order_by(
            func.max(CommitCH.date).desc()
        )
        
        projects_result = projects_query.all()
        
        projects = []
        for row in projects_result:
            projects.append({
                "repository_name": row.repository_name,
                "commit_count": row.commit_count,
                "last_commit": row.last_commit.isoformat() if isinstance(row.last_commit, datetime) else str(row.last_commit),
            })
        
        # Get stats - department counts
        dept_query = session.query(
            CommitAnalysisCH.department,
            func.count(CommitAnalysisCH.commit_hash).label('count'),
        ).join(
            CommitCH,
            CommitAnalysisCH.commit_hash == CommitCH.commit_hash,
        ).filter(
            *filters,
            CommitAnalysisCH.department.isnot(None),
            CommitAnalysisCH.department != '',
        ).group_by(
            CommitAnalysisCH.department
        )
        
        dept_result = dept_query.all()
        departments = {row.department: row.count for row in dept_result if row.department}
        
        # Get stats - work type counts
        work_type_query = session.query(
            CommitAnalysisCH.work_type,
            func.count(CommitAnalysisCH.commit_hash).label('count'),
        ).join(
            CommitCH,
            CommitAnalysisCH.commit_hash == CommitCH.commit_hash,
        ).filter(
            *filters,
            CommitAnalysisCH.work_type.isnot(None),
            CommitAnalysisCH.work_type != '',
        ).group_by(
            CommitAnalysisCH.work_type
        )
        
        work_type_result = work_type_query.all()
        work_types = {row.work_type: row.count for row in work_type_result if row.work_type}
        
        # Get stats - real vs fake
        real_fake_query = session.query(
            CommitAnalysisCH.work_category,
            func.count(CommitAnalysisCH.commit_hash).label('count'),
        ).join(
            CommitCH,
            CommitAnalysisCH.commit_hash == CommitCH.commit_hash,
        ).filter(
            *filters,
            CommitAnalysisCH.work_category.isnot(None),
            CommitAnalysisCH.work_category != '',
        ).group_by(
            CommitAnalysisCH.work_category
        )
        
        real_fake_result = real_fake_query.all()
        real_vs_fake = {row.work_category: row.count for row in real_fake_result if row.work_category}
        
        # Get total commits count
        total_count = session.query(func.count(CommitCH.commit_hash)).filter(
            *filters
        ).scalar()
        
        response = {
            "projects": projects,
            "stats": {
                "departments": departments,
                "work_types": work_types,
                "real_vs_fake": real_vs_fake,
                "total_commits": total_count or 0,
            },
            "pagination": {
                "page": page,
                "limit": limit,
            },
            "commit_history": commit_history,
        }
        
        return response
        
    except Exception as e:
        logger.error(f"Error getting developer data from ClickHouse: {e}")
        return {"error": "Failed to fetch developer data"}
