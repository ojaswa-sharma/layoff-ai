"""
SQLAlchemy declarative models for ClickHouse tables.

This module defines SQLAlchemy ORM models for all ClickHouse tables:
- CommitCH (commits table)
- PRMergeCH (pr_merges table)
- CommitAnalysisCH (commit_analysis table)
- RepoSyncEventCH (repo_sync_events table)
"""
import json
from typing import Dict, Any
from sqlalchemy import Column, String, Integer, DateTime, Text
from dependencies.ch_db import Base


class CommitCH(Base):
    """
    SQLAlchemy model for commits table in ClickHouse.
    
    Maps to the commits table with columns:
    - repository_name, repository_url, installation_id, commit_hash, message,
      author, email, date, diff, changes
    """
    __tablename__ = "commits"
    
    # Composite primary key for SQLAlchemy (ClickHouse doesn't enforce PKs)
    # This combination uniquely identifies a commit
    repository_url = Column(String, nullable=False, primary_key=True)
    commit_hash = Column(String, nullable=False, primary_key=True)
    installation_id = Column(Integer, nullable=False, primary_key=True)
    
    repository_name = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    author = Column(String, nullable=False)
    email = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    # diff = Column(Text, nullable=True)
    changes = Column(String, nullable=True)  # JSON string
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        changes_dict = None
        if self.changes:
            try:
                changes_dict = json.loads(self.changes)
            except (json.JSONDecodeError, TypeError):
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
            # "diff": self.diff,
            "changes": changes_dict,
        }
    
    @classmethod
    def from_pydantic(cls, commit, session=None):
        """
        Create CommitCH instance from Pydantic Commit model.
        
        Args:
            commit: Pydantic Commit model
            session: Optional SQLAlchemy session (not used, for compatibility)
        """
        changes_json = ""
        if commit.changes:
            changes_json = json.dumps(commit.changes)
        
        return cls(
            repository_name=commit.repository_name,
            repository_url=commit.repository_url,
            installation_id=commit.installation_id or 0,
            commit_hash=commit.commit_hash,
            message=commit.message,
            author=commit.author,
            email=commit.email,
            date=commit.date,
            # diff=commit.diff or "",
            changes=changes_json,
        )


class PRMergeCH(Base):
    """
    SQLAlchemy model for pr_merges table in ClickHouse.
    
    Maps to the pr_merges table with columns:
    - pr_number, pr_title, merge_commit_hash, merged_by, merged_by_email,
      repository_name, repository_url, date, installation_id, source
    """
    __tablename__ = "pr_merges"
    
    # Composite primary key for SQLAlchemy (ClickHouse doesn't enforce PKs)
    repository_url = Column(String, nullable=False, primary_key=True)
    merge_commit_hash = Column(String, nullable=False, primary_key=True)
    installation_id = Column(Integer, nullable=False, primary_key=True)
    
    pr_number = Column(Integer, nullable=False)
    pr_title = Column(String, nullable=False)
    merged_by = Column(String, nullable=False)
    merged_by_email = Column(String, nullable=False)
    repository_name = Column(String, nullable=False)
    date = Column(DateTime, nullable=False)
    source = Column(String, nullable=False)  # "github" or "bitbucket"
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
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
        """
        Create PRMergeCH instance from Pydantic PRMerge model.
        
        Args:
            pr_merge: Pydantic PRMerge model
            session: Optional SQLAlchemy session (not used, for compatibility)
        """
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
    """
    SQLAlchemy model for commit_analysis table in ClickHouse.
    
    Maps to the commit_analysis table with columns:
    - commit_hash, email, repo_name, commit_summary, work_category,
      department, commiters_performance, work_type
    """
    __tablename__ = "commit_analysis"
    
    # Composite primary key for SQLAlchemy (ClickHouse doesn't enforce PKs)
    commit_hash = Column(String, nullable=False, primary_key=True)
    email = Column(String, nullable=False, primary_key=True)
    repo_name = Column(String, nullable=False, primary_key=True)
    commit_summary = Column(Text, nullable=False)  # Note: typo preserved from original "commit_summmary"
    work_category = Column(String, nullable=False)  # "real" or "fake"
    department = Column(String, nullable=False)  # "ui", "frontend", "backend", "devops"
    commiters_performance = Column(Text, nullable=False)
    work_type = Column(String, nullable=False)  # "major_features", "minor_features", etc.
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        return {
            "commit_hash": self.commit_hash,
            "mail": self.email,  # Use 'mail' to match MongoDB format
            "repo_name": self.repo_name,
            "commit_summmary": self.commit_summary,  # Typo preserved
            "work_category": self.work_category,
            "department": self.department,
            "commiters_performance": self.commiters_performance,
            "work_type": self.work_type,
        }
    
    @classmethod
    def from_dict(cls, analysis_dict: Dict[str, Any], session=None):
        """
        Create CommitAnalysisCH instance from analysis dictionary.
        
        Args:
            analysis_dict: Dictionary with analysis results (from ai_service)
            session: Optional SQLAlchemy session (not used, for compatibility)
        """
        return cls(
            commit_hash=analysis_dict.get("commit_hash", ""),
            email=analysis_dict.get("mail") or analysis_dict.get("email", ""),
            repo_name=analysis_dict.get("repo_name", ""),
            commit_summary=analysis_dict.get("commit_summmary", ""),  # Typo preserved
            work_category=analysis_dict.get("work_category", ""),
            department=analysis_dict.get("department", ""),
            commiters_performance=analysis_dict.get("commiters_performance", ""),
            work_type=analysis_dict.get("work_type", ""),
        )


class RepoSyncEventCH(Base):
    """
    SQLAlchemy model for repo_sync_events table in ClickHouse.
    
    Maps to the repo_sync_events table with columns:
    - repository_name, repository_full_name, repository_url, installation_id,
      sync_status, backfill_started_at, backfill_completed_at,
      last_commit_processed, total_commits_backfilled, error_message
    """
    __tablename__ = "repo_sync_events"
    
    # Composite primary key for SQLAlchemy (ClickHouse doesn't enforce PKs)
    repository_url = Column(String, nullable=False, primary_key=True)
    installation_id = Column(Integer, nullable=False, primary_key=True)
    
    repository_name = Column(String, nullable=False)
    repository_full_name = Column(String, nullable=False)
    sync_status = Column(String, nullable=False)  # "BACKFILLING", "LIVE", "FAILED"
    # backfill_started_at = Column(DateTime, nullable=True)
    # backfill_completed_at = Column(DateTime, nullable=True)
    last_commit_processed = Column(String, nullable=True)
    total_commits = Column(Integer, nullable=False, default=0)
    error_message = Column(Text, nullable=True)
    event_time = Column(DateTime, nullable=True)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert model instance to dictionary."""
        return {
            "repository_name": self.repository_name,
            "repository_full_name": self.repository_full_name,
            "repository_url": self.repository_url,
            "installation_id": self.installation_id,
            "sync_status": self.sync_status,
            # "backfill_started_at": self.backfill_started_at,
            # "backfill_completed_at": self.backfill_completed_at,
            "last_commit_processed": self.last_commit_processed,
            "total_commits": self.total_commits,
            "error_message": self.error_message,
            "event_time": self.event_time,
        }
    
    @classmethod
    def from_pydantic(cls, repo, session=None):
        """
        Create RepoSyncEventCH instance from Pydantic Repository model.
        
        Args:
            repo: Pydantic Repository model
            session: Optional SQLAlchemy session (not used, for compatibility)
        """
        return cls(
            repository_name=repo.repository_name,
            repository_full_name=repo.repository_full_name,
            repository_url=repo.repository_url,
            installation_id=repo.installation_id,
            sync_status=repo.sync_status.value if hasattr(repo.sync_status, 'value') else str(repo.sync_status),
            # backfill_started_at=repo.backfill_started_at,
            # backfill_completed_at=repo.backfill_completed_at,
            last_commit_processed=repo.last_commit_processed,
            total_commits=repo.total_commits,
            error_message=repo.error_message,
            event_time=repo.event_time,
        )

