"""
SQLAlchemy declarative models for ClickHouse tables.
"""

import json
from typing import Dict, Any
from sqlalchemy import Column, Integer, DateTime, text, Computed
from sqlalchemy.orm import column_property
from dependencies.ch_db import Base
# from clickhouse_connect.cc_sqlalchemy import engines
# from clickhouse_connect.cc_sqlalchemy.ddl.tableengine import MergeTree
from sqlalchemy.sql import literal_column
# from clickhouse_connect.cc_sqlalchemy.datatypes.sqltypes import LowCardinality, String
from clickhouse_sqlalchemy import engines
from clickhouse_sqlalchemy.types import LowCardinality, String, AggregateFunction, UInt64, Int64


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
        )


class PRMergeCH(Base):
    __tablename__ = "pr_merges"

    __table_args__ = (
        engines.MergeTree(
            order_by=("repository_url", "merge_commit_hash", "installation_id"),
        ),
    )

    repository_url = Column(String, primary_key=True)
    merge_commit_hash = Column(String, primary_key=True)
    installation_id = Column(Integer, primary_key=True)

    pr_number = Column(Integer, nullable=False)
    pr_title = Column(String, nullable=False)
    merged_by = Column(LowCardinality(String), nullable=False)
    merged_by_email = Column(LowCardinality(String), nullable=False)
    repository_name = Column(LowCardinality(String), nullable=False)
    date = Column(DateTime, nullable=False)
    source = Column(String, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pr_number": self.pr_number,
            "pr_title": self.pr_title,
            "merge_commit_hash": self.merge_commit_hash,
            "merged_by": self.merged_by,
            "merged_by_email": self.merged_by_email,
            "repository_name": self.repository_name,
            "repository_url": self.repository_url,
            "date": self.date,
            "installation_id": self.installation_id,
            "source": self.source,
        }

    @classmethod
    def from_pydantic(cls, pr_merge, session=None):
        return cls(
            pr_number=pr_merge.pr_number,
            pr_title=pr_merge.pr_title,
            merge_commit_hash=pr_merge.merge_commit_hash,
            merged_by=pr_merge.merged_by,
            merged_by_email=pr_merge.merged_by_email,
            repository_name=pr_merge.repository_name,
            repository_url=pr_merge.repository_url,
            date=pr_merge.date,
            installation_id=pr_merge.installation_id,
            source=pr_merge.source,
        )


class CommitAnalysisCH(Base):
    __tablename__ = "commit_analysis"

    __table_args__ = (
        engines.MergeTree(
            order_by=("email", "repo_name"),
        ),
    )

    commit_hash = Column(String, primary_key=True)
    email = Column(LowCardinality(String), primary_key=True)
    repo_name = Column(LowCardinality(String), primary_key=True)

    commit_summary = Column(String, nullable=False)
    work_category = Column(String, nullable=False)
    department = Column(String, nullable=False)
    commiters_performance = Column(String, nullable=False)
    work_type = Column(String, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "commit_hash": self.commit_hash,
            "mail": self.email,
            "repo_name": self.repo_name,
            "commit_summmary": self.commit_summary,
            "work_category": self.work_category,
            "department": self.department,
            "commiters_performance": self.commiters_performance,
            "work_type": self.work_type,
        }

    @classmethod
    def from_dict(cls, analysis_dict: Dict[str, Any], session=None):
        return cls(
            commit_hash=analysis_dict.get("commit_hash", ""),
            email=analysis_dict.get("mail") or analysis_dict.get("email", ""),
            repo_name=analysis_dict.get("repo_name", ""),
            commit_summary=analysis_dict.get("commit_summmary", ""),
            work_category=analysis_dict.get("work_category", ""),
            department=analysis_dict.get("department", ""),
            commiters_performance=analysis_dict.get("commiters_performance", ""),
            work_type=analysis_dict.get("work_type", ""),
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


class RepositoryTechStackCH(Base):
    __tablename__ = "repository_tech_stack"

    __table_args__ = (
        engines.MergeTree(
            order_by=("repository_full_name", "installation_id"),
        ),
    )

    repository_full_name = Column(String, primary_key=True)
    installation_id = Column(Integer, primary_key=True)

    repository_name = Column(String, nullable=False)
    languages = Column(String, nullable=True)  # JSON string: {"Python": 12345, "JavaScript": 6789}
    topics = Column(String, nullable=True)  # JSON array string: ["python", "fastapi"]
    last_updated = Column(DateTime, nullable=False)
    source = Column(String, nullable=False)  # "github" or "bitbucket"

    def to_dict(self) -> Dict[str, Any]:
        languages_dict = None
        if self.languages:
            try:
                languages_dict = json.loads(self.languages)
            except Exception:
                languages_dict = {}
        
        topics_list = None
        if self.topics:
            try:
                topics_list = json.loads(self.topics)
            except Exception:
                topics_list = []

        return {
            "repository_full_name": self.repository_full_name,
            "installation_id": self.installation_id,
            "repository_name": self.repository_name,
            "languages": languages_dict,
            "topics": topics_list,
            "last_updated": self.last_updated,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, tech_stack_dict: Dict[str, Any], session=None):
        languages_json = json.dumps(tech_stack_dict.get("languages", {})) if tech_stack_dict.get("languages") else None
        topics_json = json.dumps(tech_stack_dict.get("topics", [])) if tech_stack_dict.get("topics") else None
        
        return cls(
            repository_full_name=tech_stack_dict.get("repository_full_name", ""),
            installation_id=tech_stack_dict.get("installation_id", 0),
            repository_name=tech_stack_dict.get("repository_name", ""),
            languages=languages_json,
            topics=topics_json,
            last_updated=tech_stack_dict.get("last_updated"),
            source=tech_stack_dict.get("source", "github"),
        )