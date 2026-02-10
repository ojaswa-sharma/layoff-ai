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

    additions = CommitCH.additions
    deletions = CommitCH.deletions

    # Repo level aggregation
    repo_agg = (
        select(
            func.any(CommitCH.author).label("author"),
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

    # User level aggregation with separate arrays
    user_agg = (
        select(
            func.any(repo_agg.c.author).label("author"),
            repo_agg.c.email,
            func.max(repo_agg.c.repo_last_commit).label("last_commit"),
            func.sum(repo_agg.c.repo_additions).label("total_additions"),
            func.sum(repo_agg.c.repo_deletions).label("total_deletions"),
            func.sum(repo_agg.c.repo_commits).label("total_commits"),

            # Use separate arrays to avoid type mismatch
            func.groupArray(repo_agg.c.repo_name).label("repo_names"),
            func.groupArray(repo_agg.c.repo_last_commit).label("repo_last_commits"),
            func.groupArray(repo_agg.c.repo_additions).label("repo_additions_list"),
            func.groupArray(repo_agg.c.repo_deletions).label("repo_deletions_list"),

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

    now = datetime.utcnow()

    data = []
    for r in rows:

        last_commit = r.last_commit
        hours = (now - last_commit).total_seconds() / 3600
        status = "active" if hours <= 6 else "idle" if hours <= 24 else "inactive"

        # Reconstruct repos from parallel arrays
        repos = []
        for name, commit, additions, deletions in zip(
            r.repo_names,
            r.repo_last_commits,
            r.repo_additions_list,
            r.repo_deletions_list
        ):
            repo_hours = (now - commit).total_seconds() / 3600
            repo_status = "active" if repo_hours <= 6 else "idle" if repo_hours <= 24 else "inactive"

            repos.append({
                "repo_name": name,
                "last_commit": commit.isoformat(),
                "repo_additions": additions,
                "repo_deletions": deletions,
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
            "author" : r.author
        })

    return {
        "page": page,
        "limit": limit,
        "total_items": total_items,
        "total_pages": total_pages,
        "data": data,
    }

from sqlalchemy import select, case, literal_column
from datetime import datetime, timezone

def make_aware(dt):
    """Convert naive datetime to UTC-aware datetime"""
    if dt and isinstance(dt, datetime) and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt

async def get_developer_ch(
    session: Session,
    email: str,
    project: Optional[str] = None,
    page: int = 1,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Get developer details with commit history and statistics using a single query.
    
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
        
        # Single comprehensive query using window functions
        query = (
            select(
                # Commit data for pagination
                CommitCH.commit_hash,
                CommitCH.message.label('commit_title'),
                CommitCH.date,
                CommitCH.repository_name,
                CommitCH.changes,
                CommitAnalysisCH.department,
                CommitAnalysisCH.work_type,
                CommitAnalysisCH.work_category,
                CommitAnalysisCH.commiters_performance.label('performance'),
                CommitAnalysisCH.commit_summary,
                
                # Row number for pagination
                func.row_number().over(order_by=CommitCH.date.desc()).label('row_num'),
                
                # Total count
                func.count().over().label('total_commits'),
                
                # Projects aggregation (all projects for this developer)
                func.groupUniqArray(CommitCH.repository_name).over().label('all_projects'),
                
                # Per-project stats using conditional aggregation with windows
                func.groupArray(
                    func.tuple(
                        CommitCH.repository_name,
                        CommitCH.date,
                        CommitCH.commit_hash
                    )
                ).over().label('project_data'),
                
                # Department stats
                func.groupArray(
                    case(
                        (CommitAnalysisCH.department.isnot(None) & (CommitAnalysisCH.department != ''), 
                         CommitAnalysisCH.department),
                        else_=None
                    )
                ).over().label('all_departments'),
                
                # Work type stats
                func.groupArray(
                    case(
                        (CommitAnalysisCH.work_type.isnot(None) & (CommitAnalysisCH.work_type != ''), 
                         CommitAnalysisCH.work_type),
                        else_=None
                    )
                ).over().label('all_work_types'),
                
                # Work category stats
                func.groupArray(
                    case(
                        (CommitAnalysisCH.work_category.isnot(None) & (CommitAnalysisCH.work_category != ''), 
                         CommitAnalysisCH.work_category),
                        else_=None
                    )
                ).over().label('all_work_categories'),
            )
            .select_from(CommitCH)
            .outerjoin(
                CommitAnalysisCH,
                CommitCH.commit_hash == CommitAnalysisCH.commit_hash,
            )
            .where(*filters)
            .order_by(CommitCH.date.desc())
        )
        
        # Execute query
        all_results = session.execute(query).fetchall()
        
        if not all_results:
            return {
                "projects": [],
                "stats": {
                    "departments": {},
                    "work_types": {},
                    "real_vs_fake": {},
                    "total_commits": 0,
                },
                "pagination": {
                    "page": page,
                    "limit": limit,
                },
                "commit_history": [],
            }
        
        # Get stats from first row (window functions make them same for all rows)
        first_row = all_results[0]
        total_commits = first_row.total_commits
        
        # Process departments
        departments = {}
        for dept in first_row.all_departments:
            if dept:
                departments[dept] = departments.get(dept, 0) + 1
        
        # Process work types
        work_types = {}
        for wt in first_row.all_work_types:
            if wt:
                work_types[wt] = work_types.get(wt, 0) + 1
        
        # Process work categories
        real_vs_fake = {}
        for cat in first_row.all_work_categories:
            if cat:
                real_vs_fake[cat] = real_vs_fake.get(cat, 0) + 1
        
        # Process projects from project_data
        projects_map = {}
        for repo_name, commit_date, commit_hash in first_row.project_data:
            if repo_name not in projects_map:
                projects_map[repo_name] = {
                    'last_commit': commit_date,
                    'count': 0
                }
            projects_map[repo_name]['count'] += 1
            # Update last commit if this one is more recent
            if commit_date > projects_map[repo_name]['last_commit']:
                projects_map[repo_name]['last_commit'] = commit_date
        
        # Format projects
        projects = [
            {
                "repository_name": repo_name,
                "commit_count": data['count'],
                "last_commit": make_aware(data['last_commit']).isoformat() if data['last_commit'] else None,
            }
            for repo_name, data in sorted(
                projects_map.items(),
                key=lambda x: x[1]['last_commit'],
                reverse=True
            )
        ]
        
        # Filter commits for current page using row_num
        commit_history = []
        for row in all_results:
            if skip < row.row_num <= skip + limit:
                changes = _parse_changes_json(row.changes)
                
                commit_history.append({
                    "commit_hash": row.commit_hash,
                    "commit_title": row.commit_title,
                    "date": make_aware(row.date).isoformat() if row.date else None,
                    "repository_name": row.repository_name,
                    "department": row.department if row.department else None,
                    "work_type": row.work_type if row.work_type else None,
                    "work_category": row.work_category if row.work_category else None,
                    "performance": row.performance if row.performance else None,
                    "additions": changes["additions"],
                    "deletions": changes["deletions"],
                    "commit_summary": row.commit_summary if row.commit_summary else None,
                })
        
        response = {
            "projects": projects,
            "stats": {
                "departments": departments,
                "work_types": work_types,
                "real_vs_fake": real_vs_fake,
                "total_commits": total_commits,
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