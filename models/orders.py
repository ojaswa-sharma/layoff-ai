from enum import Enum

class OrderBy(Enum):
    author : str = "author"
    email : str = "email"
    total_additions : str = "total_additions"
    total_removed : str = "total_removed"
    total_commits : str = "total_commits"
    last_commit : str = "last_commit"

class OrderDir(Enum):
    asc : str = "ASC"
    desc : str = "DESC"