from pydantic import BaseModel
from typing import List, Optional
from enum import Enum
from datetime import datetime


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

class WorkCategory(Enum):
    real : str = "real"
    fake : str = "fake"

class WorkDepartment(Enum):
    major_features : str = "major_features"
    minor_features : str = "minor_features"
    ui_bugs : str = "ui_bugs"
    functional_bugs : str = "functional_bugs"
    tech_debt : str = "tech_debt"
    other : str = "other"

class WorkType(Enum):
    bugfix : str = "bugfix"
    feature : str = "feature"

class CommitDetails(BaseModel):
    commit_summary : str
    work_category : WorkCategory
    department : WorkDepartment
    commiters_performance : str
    work_type : WorkType
