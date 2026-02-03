from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from datetime import datetime


class SyncStatus(str, Enum):
    """Repository synchronization status"""
    BACKFILLING = "BACKFILLING"
    LIVE = "LIVE"
    FAILED = "FAILED"


class Repository(BaseModel):
    """Repository metadata and sync status tracking"""
    repository_name: str
    repository_full_name: str
    repository_url: str
    installation_id: int
    sync_status: SyncStatus = SyncStatus.BACKFILLING
    backfill_started_at: Optional[datetime] = None
    backfill_completed_at: Optional[datetime] = None
    last_commit_processed: Optional[str] = None  # commit SHA
    total_commits_backfilled: int = 0
    error_message: Optional[str] = None


class Commit(BaseModel):
    commit_hash: str
    message: str
    author: str
    email: str
    date: datetime
    repository_name: str
    repository_url: str
    diff: Optional[str] = None
    installation_id : Optional[int] = None
    changes : Optional[dict]

class WorkCategory(Enum):
    real : str = "real"
    fake : str = "fake"

class WorkDepartment(Enum):
    ui : str = "ui"
    frontend : str = "frontend"
    backend : str = "backend"
    devops : str = "devops"

class WorkType(Enum):
    major_features : str = "major_features"
    minor_features : str = "minor_features"
    ui_bugs : str = "ui_bugs"
    functional_bugs : str = "functional_bugs"
    tech_debt : str = "tech_debt"
    other : str = "other"

class CommitDetails(BaseModel):
    commit_summary: str = Field(
        ...,
        description=(
            "A concise but detailed 2–3 sentence paragraph describing what was changed, "
            "why it was done, and the concrete technical impact. "
            "Must be factual, specific, and avoid exaggeration or filler."
        ),
    )

    work_category: WorkCategory = Field(
        ...,
        description="All development and bug fixing is real work, but changes to the code that dont do anything, like editing a readme, or removing commented code is fake/unproductive."
    )

    department: WorkDepartment
    

    commiters_performance: str = Field(
        ...,
        description=(
            "A professional 2–3 sentence performance evaluation assessing technical value, "
            "execution quality, clarity of intent, and whether the work matches its implied importance. "
            "Must be critical and objective, not complimentary or vague."
        ),
    )

    work_type: WorkType
