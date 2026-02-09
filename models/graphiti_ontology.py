from pydantic import Field, BaseModel

# =========================
# ENTITY DEFINITIONS
# =========================

class Repository(BaseModel):
    """
    Represents a code repository.
    """
    repo_name: str = Field(
        description="The name of the repository"
    )


class Bug(BaseModel):
    """
    Represents a bug in a repository.
    """
    bug_type: str = Field(
        description="Type of bug: frontend, backend, devops"
    )
    bug_severity: str = Field(
        description="Severity of the bug: LOW, HIGH, CRITICAL"
    )
    bug_summary: str = Field(
        description="Detailed summary of the bug"
    )
    is_resolved: bool = Field(
        description="Whether the bug has been fixed"
    )


class Feature(BaseModel):
    """
    Represents a feature in a repository.
    """
    feature_name: str = Field(
        description="Short name of the feature"
    )
    feature_description: str = Field(
        description="Detailed description of the feature"
    )
    is_implemented: bool = Field(
        description="Whether the feature has been implemented"
    )


class Commit(BaseModel):
    """
    Represents a commit.
    """
    commit_title: str = Field(
        description="The title of the commit"
    )
    commit_hash: str = Field(
        description="The hash of the commit"
    )
    relevant_work: bool = Field(
        description="True if actual work, false if fake/irrelevant"
    )
    commit_description: str = Field(
        description="Detailed description of the commit"
    )

class Developer(BaseModel):
    """
    Represents the developer
    """
    email : BaseModel = Field(description="The email of the developer")
    name : BaseModel = Field(description="The name of the developer")
    

class Changes(BaseModel):
    """
    Represents the changes in a commit
    """
    change_text : str = Field(description="Summary of changes done in a commit")

class Positives(BaseModel):
    """
    Represents the actual good work done by the developer
    """
    positve_work_summary : str = Field(description="The good work done by the developer")

class Negatives(BaseModel):
    """
    Represents the issues or bad coding practices followed by the developer
    """
    negative_work_summary : str = Field(description="The issues or bad coding practices done by the developer")


# =========================
# EDGE DEFINITIONS (DATA LIVES HERE)
# =========================

class RepositoryContainsBug(BaseModel):
    """
    Repo → Bug relationship metadata.
    """
    discovery_context: str = Field(
        description="How the bug was discovered (logs, user report, monitoring, etc.)"
    )


class RepositoryContainsFeature(BaseModel):
    """
    Repo → Feature relationship metadata.
    """
    priority: str = Field(
        description="Feature priority: LOW, MEDIUM, HIGH"
    )


class BugAddressedByCommit(BaseModel):
    """
    Bug → Commit relationship metadata.
    """
    fix_type: str = Field(
        description="Type of fix: hotfix, patch, refactor"
    )
    fully_resolves: bool = Field(
        description="Whether this commit fully resolves the bug"
    )


class FeatureRealizedByCommit(BaseModel):
    """
    Feature → Commit relationship metadata.
    """
    implementation_stage: str = Field(
        description="Stage: initial, partial, complete"
    )
