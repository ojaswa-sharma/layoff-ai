"""
SQLAlchemy declarative models for ClickHouse tables.
"""

import json
from typing import Dict, Any
from sqlalchemy import Column, Integer, DateTime, text
from sqlalchemy.orm import column_property
from dependencies.ch_db import Base
from sqlalchemy.sql import literal_column
from clickhouse_sqlalchemy import engines
from clickhouse_sqlalchemy.types import LowCardinality, String, AggregateFunction, UInt64, Int64
from datetime import datetime, timezone


class CommitCH(Base):
    __tablename__ = "commits"

    __table_args__ = (
        engines.MergeTree(
            order_by=("email" ,"repository_name", "date"),
            partition_by=text("toYYYYMM(date)")
        ),
    )

    repository_url = Column(LowCardinality(String), primary_key=True)
    commit_hash = Column(String, primary_key=True)
    installation_id = Column(Integer, primary_key=True)

    repository_name = Column(LowCardinality(String), nullable=False)
    message = Column(String, nullable=False)
    author = Column(LowCardinality(String), nullable=False)
    email = Column(LowCardinality(String), nullable=False)
    date = Column(DateTime, nullable=False)
    changes = Column(String, nullable=True)
    branch_name = Column(LowCardinality(String), nullable=True)
    additions = column_property(
            literal_column("additions", Integer)
        )

    deletions = column_property(
            literal_column("deletions", Integer)
        )


    def to_dict(self) -> Dict[str, Any]:
        changes_dict = None
        if self.changes:
            try:
                changes_dict = json.loads(self.changes)
            except Exception:
                changes_dict = {}

        return {
            "repository_name": self.repository_name,
            "repository_url": self.repository_url,
            "installation_id": self.installation_id,
            "commit_hash": self.commit_hash,
            "message": self.message,
            "author": self.author,
            "email": self.email,
            "date": self.date,
            "changes": changes_dict,
            "branch_name": self.branch_name,
        }

    @classmethod
    def from_pydantic(cls, commit, session=None):
        return cls(
            repository_name=commit.repository_name,
            repository_url=commit.repository_url,
            installation_id=commit.installation_id or 0,
            commit_hash=commit.commit_hash,
            message=commit.message,
            author=commit.author,
            email=commit.email,
            date=commit.date,
            changes=json.dumps(commit.changes) if commit.changes else "",
            branch_name=getattr(commit, 'branch_name', None),
        )


class PRMergeCH(Base):
    __tablename__ = "pr_merges"

    __table_args__ = (
        engines.ReplacingMergeTree(
            "updated_at",
            order_by=("repository_url", "pr_number", "installation_id"),
        ),
    )

    repository_url = Column(String, primary_key=True)
    pr_number = Column(Integer, primary_key=True)
    installation_id = Column(Integer, primary_key=True)

    pr_title = Column(String, nullable=False)
    status = Column(LowCardinality(String), nullable=False)  # "open", "closed", "merged"
    created_by = Column(LowCardinality(String), nullable=False)  # PR creator username
    created_by_email = Column(LowCardinality(String), nullable=False)  # PR creator email
    merge_commit_hash = Column(String, nullable=True)  # Nullable for opened PRs
    merged_by = Column(LowCardinality(String), nullable=True)  # Nullable for opened PRs
    merged_by_email = Column(LowCardinality(String), nullable=True)  # Nullable for opened PRs
    repository_name = Column(LowCardinality(String), nullable=False)
    branch = Column(LowCardinality(String), nullable=True)  # Source branch name
    additions = Column(Int64, nullable=True)  # Lines added
    deletions = Column(Int64, nullable=True)  # Lines removed
    date = Column(DateTime, nullable=False)  # Created/merged date
    updated_at = Column(DateTime, nullable=False)  # Last update timestamp
    source = Column(String, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pr_number": self.pr_number,
            "pr_title": self.pr_title,
            "status": self.status,
            "created_by": self.created_by,
            "created_by_email": self.created_by_email,
            "merge_commit_hash": self.merge_commit_hash,
            "merged_by": self.merged_by,
            "merged_by_email": self.merged_by_email,
            "repository_name": self.repository_name,
            "repository_url": self.repository_url,
            "branch": self.branch,
            "additions": self.additions,
            "deletions": self.deletions,
            "date": self.date,
            "updated_at": self.updated_at,
            "installation_id": self.installation_id,
            "source": self.source,
        }

    @classmethod
    def from_pydantic(cls, pr_merge, session=None):
        # Handle None values for String and LowCardinality(String) columns
        # ClickHouse SQLAlchemy driver may try to encode None, causing "'NoneType' object has no attribute 'encode'" error
        # Convert None to empty string for nullable String columns to avoid encoding issues
        merge_commit_hash_val = getattr(pr_merge, 'merge_commit_hash', None)
        merged_by_val = getattr(pr_merge, 'merged_by', None)
        merged_by_email_val = getattr(pr_merge, 'merged_by_email', None)
        branch_val = getattr(pr_merge, 'branch', None)
        
        # Convert None to empty string for nullable String columns to prevent encoding errors
        merge_commit_hash = merge_commit_hash_val if merge_commit_hash_val is not None else ""
        merged_by = merged_by_val if merged_by_val is not None else ""
        merged_by_email = merged_by_email_val if merged_by_email_val is not None else ""
        branch = branch_val if branch_val is not None else ""
        
        # Handle None values for Int64 columns
        # ClickHouse Int64 type doesn't accept Python None directly, convert to 0
        additions_val = getattr(pr_merge, 'additions', None)
        deletions_val = getattr(pr_merge, 'deletions', None)
        additions = additions_val if additions_val is not None else 0
        deletions = deletions_val if deletions_val is not None else 0
        
        return cls(
            pr_number=pr_merge.pr_number,
            pr_title=pr_merge.pr_title,
            status=pr_merge.status,
            created_by=pr_merge.created_by,
            created_by_email=pr_merge.created_by_email,
            merge_commit_hash=merge_commit_hash,
            merged_by=merged_by,
            merged_by_email=merged_by_email,
            repository_name=pr_merge.repository_name,
            repository_url=pr_merge.repository_url,
            branch=branch,
            additions=additions,
            deletions=deletions,
            date=pr_merge.date,
            updated_at=getattr(pr_merge, 'updated_at', pr_merge.date),
            installation_id=pr_merge.installation_id,
            source=pr_merge.source,
        )


class CommitAnalysisCH(Base):
    __tablename__ = "commit_analysis"

    __table_args__ = (
        engines.MergeTree(
            order_by=("email", "repo_name", "commit_hash"),
            partition_by=("email")
        ),
    )

    commit_hash           = Column(String,                 primary_key=True)
    email                 = Column(LowCardinality(String), primary_key=True)
    repo_name             = Column(LowCardinality(String), primary_key=True)

    commit_summary        = Column(String,   nullable=False)
    work_category         = Column(String,   nullable=False)
    department            = Column(String,   nullable=False)
    commiters_performance = Column(String,   nullable=False)
    work_type             = Column(String,   nullable=False)

    commit_title          = Column(String,   nullable=True)
    commit_date           = Column(DateTime, nullable=True)
    changes               = Column(String,   nullable=True)
    additions             = Column(Integer,  nullable=True)
    deletions             = Column(Integer,  nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commit_hash":          self.commit_hash,
            "mail":                 self.email,
            "repo_name":            self.repo_name,
            "commit_summmary":      self.commit_summary,
            "work_category":        self.work_category,
            "department":           self.department,
            "commiters_performance":self.commiters_performance,
            "work_type":            self.work_type,
            "commit_title":         self.commit_title,
            "commit_date":          self.commit_date,
            "additions":            self.additions,
            "deletions":            self.deletions,
        }

    @classmethod
    def from_dict(cls, analysis_dict: Dict[str, Any], session=None):
        return cls(
            commit_hash=           analysis_dict.get("commit_hash", ""),
            email=                 analysis_dict.get("mail") or analysis_dict.get("email", ""),
            repo_name=             analysis_dict.get("repo_name", ""),
            commit_summary=        analysis_dict.get("commit_summmary", ""),
            work_category=         analysis_dict.get("work_category", ""),
            department=            analysis_dict.get("department", ""),
            commiters_performance= analysis_dict.get("commiters_performance", ""),
            work_type=             analysis_dict.get("work_type", ""),
            commit_title=          analysis_dict.get("commit_title", ""),
            commit_date=           analysis_dict.get("commit_date"),
            changes=               analysis_dict.get("changes", ""),
            additions=             analysis_dict.get("additions", 0),
            deletions=             analysis_dict.get("deletions", 0),
        )

class RepoSyncEventCH(Base):
    __tablename__ = "repo_sync_events"

    __table_args__ = (
        engines.MergeTree(
            order_by=("repository_full_name", "installation_id"),
        ),
    )

    repository_full_name = Column(String, primary_key=True)
    installation_id = Column(Integer, primary_key=True)

    repository_name = Column(String, nullable=False)
    sync_status = Column(String, nullable=False)
    last_commit_processed = Column(String, nullable=True)
    total_commits = Column(Integer, nullable=False, default=0)
    error_message = Column(String, nullable=True)
    event_time = Column(DateTime, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repository_name": self.repository_name,
            "repository_full_name": self.repository_full_name,
            "installation_id": self.installation_id,
            "sync_status": self.sync_status,
            "last_commit_processed": self.last_commit_processed,
            "total_commits": self.total_commits,
            "error_message": self.error_message,
            "event_time": self.event_time,
        }

    @classmethod
    def from_pydantic(cls, repo, session=None):
        return cls(
            repository_name=repo.repository_name,
            repository_full_name=repo.repository_full_name,
            installation_id=repo.installation_id,
            sync_status=repo.sync_status.value if hasattr(repo.sync_status, "value") else str(repo.sync_status),
            last_commit_processed=repo.last_commit_processed,
            total_commits=repo.total_commits,
            error_message=repo.error_message,
            event_time=repo.event_time,
        )



class UserRepoAggregate(Base):
    __tablename__ = "user_repo_agg"

    __table_args__ = (
        engines.AggregatingMergeTree(
            order_by=("email", "repo_name"),
        ),
    )

    email = Column(LowCardinality(String), primary_key=True)
    repo_name = Column(LowCardinality(String), primary_key=True)
    author = Column(
        AggregateFunction("any", String)
    )

    commit_count = Column(
        AggregateFunction("count", Integer)
    )

    total_additions = Column(
        AggregateFunction("sum", Integer)
    )

    total_deletions = Column(
        AggregateFunction("sum", Integer)
    )

    last_commit_date = Column(
        AggregateFunction("max", DateTime)
    )


class UserStatsAggregate(Base):
    __tablename__ = "user_stats_agg"

    __table_args__ = (
        engines.AggregatingMergeTree(
            order_by=("email", "dimension_type", "dimension_value")
        ),
    )

    email = Column(LowCardinality(String), primary_key=True)
    dimension_type = Column(String)
    dimension_value = Column(String)
    cnt_state = Column(AggregateFunction("count"))


class RepositoryTechStackCH(Base):
    __tablename__ = "repository_tech_stack"

    __table_args__ = (
        engines.ReplacingMergeTree(
            "last_updated",
            order_by=("repository_full_name", "installation_id"),
        ),
    )

    repository_full_name = Column(String, primary_key=True)
    installation_id = Column(UInt64, primary_key=True)

    repository_name = Column(String, nullable=False)

    languages = Column(String, default={})
    topics = Column(String, default=[])

    last_updated = Column(DateTime, nullable=False)
    source = Column(String, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "repository_full_name": self.repository_full_name,
            "installation_id": self.installation_id,
            "repository_name": self.repository_name,
            "languages": self.languages or {},
            "topics": self.topics or [],
            "last_updated": self.last_updated,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]):
        return cls(
            repository_full_name=data.get("repository_full_name") or "",
            installation_id=data.get("installation_id") or 0,
            repository_name=data.get("repository_name") or "",
            languages=data.get("languages") or {},
            topics=data.get("topics") or [],
            last_updated=data.get("last_updated") or datetime.now(timezone.utc),
            source=data.get("source") or "github",
        )


class BranchRawCH(Base):
    __tablename__ = "branches_raw"

    __table_args__ = (
        engines.MergeTree(
            order_by=("repository_full_name", "branch_name", "email"),
            partition_by=text("toYYYYMM(fetched_at)")
        ),
    )

    repository_full_name = Column(LowCardinality(String), primary_key=True)
    branch_name = Column(LowCardinality(String), primary_key=True)
    email = Column(LowCardinality(String), primary_key=True)

    commit_date = Column(DateTime, nullable=False)
    installation_id = Column(UInt64, nullable=False)

    fetched_at = Column(DateTime, default=datetime.utcnow)


class UserBranchAggregateCH(Base):
    __tablename__ = "user_branch_agg"

    __table_args__ = (
        engines.AggregatingMergeTree(
            order_by=("email", "repository_full_name", "branch_name"),
        ),
    )

    email = Column(LowCardinality(String), primary_key=True)
    repository_full_name = Column(LowCardinality(String), primary_key=True)
    branch_name = Column(LowCardinality(String), primary_key=True)

    commit_count = Column(AggregateFunction("count", Integer))
    last_commit_date = Column(AggregateFunction("max", DateTime))
    total_additions = Column(AggregateFunction("sum", Integer))
    total_deletions = Column(AggregateFunction("sum", Integer))

    last_pr_status = Column(AggregateFunction("anyLast", String))
    last_seen = Column(DateTime)


class WorkItemCH(Base):
    __tablename__ = "work_items"

    __table_args__ = (
        engines.ReplacingMergeTree(
            "last_updated_at",
            order_by=("workspace_id", "work_item_id"),
        ),
    )

    workspace_id = Column(String, primary_key=True)
    work_item_id = Column(String, primary_key=True)

    title = Column(String, nullable=False)
    description = Column(String, nullable=True)
    status = Column(LowCardinality(String), nullable=False)
    assignee_email = Column(LowCardinality(String), nullable=True)
    assignee_name = Column(LowCardinality(String), nullable=True)
    assigner_email = Column(LowCardinality(String), nullable=True)
    assigner_name = Column(LowCardinality(String), nullable=True)
    created_at = Column(DateTime, nullable=False)
    last_updated_at = Column(DateTime, nullable=False)
    project_id = Column(String, nullable=True)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "work_item_id": self.work_item_id,
            "workspace_id": self.workspace_id,
            "title": self.title,
            "description": self.description,
            "status": self.status,
            "assignee_email": self.assignee_email,
            "assignee_name": self.assignee_name,
            "assigner_email": self.assigner_email,
            "assigner_name": self.assigner_name,
            "created_at": self.created_at,
            "last_updated_at": self.last_updated_at,
            "project_id": self.project_id,
        }

    @classmethod
    def from_pydantic(cls, work_item, session=None):
        # Handle None values for String and LowCardinality(String) columns
        # ClickHouse SQLAlchemy driver may try to encode None, causing "'NoneType' object has no attribute 'encode'" error
        # Convert None to empty string for nullable String columns to avoid encoding issues
        description_val = getattr(work_item, 'description', None)
        assignee_email_val = getattr(work_item, 'assignee_email', None)
        assignee_name_val = getattr(work_item, 'assignee_name', None)
        assigner_email_val = getattr(work_item, 'assigner_email', None)
        assigner_name_val = getattr(work_item, 'assigner_name', None)
        project_id_val = getattr(work_item, 'project_id', None)
        
        # Convert None to empty string for nullable String columns to prevent encoding errors
        description = description_val if description_val is not None else ""
        assignee_email = assignee_email_val if assignee_email_val is not None else ""
        assignee_name = assignee_name_val if assignee_name_val is not None else ""
        assigner_email = assigner_email_val if assigner_email_val is not None else ""
        assigner_name = assigner_name_val if assigner_name_val is not None else ""
        project_id = project_id_val if project_id_val is not None else ""
        
        return cls(
            work_item_id=work_item.work_item_id,
            workspace_id=work_item.workspace_id,
            title=work_item.title,
            description=description,
            status=work_item.status,
            assignee_email=assignee_email,
            assignee_name=assignee_name,
            assigner_email=assigner_email,
            assigner_name=assigner_name,
            created_at=work_item.created_at,
            last_updated_at=work_item.last_updated_at,
            project_id=project_id,
        )