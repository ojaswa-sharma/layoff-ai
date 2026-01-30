from pydantic import BaseModel
from typing import List
from datetime import datetime


class Commit(BaseModel):
    commit_hash: str
    message: str
    author: str
    email: str
    date: datetime
    repository_name: str
    repository_url: str