from pydantic import Field
from zep_cloud.external_clients.ontology import (
    EntityModel,
    EntityText,
    EntityBoolean,
    EdgeModel,
)

# =========================
# ENTITY DEFINITIONS
# =========================

class Repository(EntityModel):
    """
    Represents a code repository.
    """
    repo_name: EntityText = Field(
        description="The name of the repository"
    )


class Bug(EntityModel):
    """
    Represents a bug in a repository.
    """
    bug_type: EntityText = Field(
        description="Type of bug: frontend, backend, devops"
    )
    bug_severity: EntityText = Field(
        description="Severity of the bug: LOW, HIGH, CRITICAL"
    )
    bug_summary: EntityText = Field(
        description="Detailed summary of the bug"
    )
    is_resolved: EntityBoolean = Field(
        description="Whether the bug has been fixed"
    )


class Feature(EntityModel):
    """
    Represents a feature in a repository.
    """
    feature_name: EntityText = Field(
        description="Short name of the feature"
    )
    feature_description: EntityText = Field(
        description="Detailed description of the feature"
    )
    is_implemented: EntityBoolean = Field(
        description="Whether the feature has been implemented"
    )


class Commit(EntityModel):
    """
    Represents a commit.
    """
    commit_title: EntityText = Field(
        description="The title of the commit"
    )
    commit_hash: EntityText = Field(
        description="The hash of the commit"
    )
    relevant_work: EntityBoolean = Field(
        description="True if actual work, false if fake/irrelevant"
    )
    commit_description: EntityText = Field(
        description="Detailed description of the commit"
    )

class Developer(EntityModel):
    """
    Represents the developer
    """
    email : EntityModel = Field(description="The email of the developer")
    name : EntityModel = Field(description="The name of the developer")
    

class Changes(EntityModel):
    """
    Represents the changes in a commit
    """
    change_text : EntityText = Field(description="Summary of changes done in a commit")

class Positives(EntityModel):
    """
    Represents the actual good work done by the developer
    """
    positve_work_summary : EntityText = Field(description="The good work done by the developer")

class Negatives(EntityModel):
    """
    Represents the issues or bad coding practices followed by the developer
    """
    negative_work_summary : EntityText = Field(description="The issues or bad coding practices done by the developer")


# =========================
# EDGE DEFINITIONS (DATA LIVES HERE)
# =========================

class RepositoryContainsBug(EdgeModel):
    """
    Repo → Bug relationship metadata.
    """
    discovery_context: EntityText = Field(
        description="How the bug was discovered (logs, user report, monitoring, etc.)"
    )


class RepositoryContainsFeature(EdgeModel):
    """
    Repo → Feature relationship metadata.
    """
    priority: EntityText = Field(
        description="Feature priority: LOW, MEDIUM, HIGH"
    )


class BugAddressedByCommit(EdgeModel):
    """
    Bug → Commit relationship metadata.
    """
    fix_type: EntityText = Field(
        description="Type of fix: hotfix, patch, refactor"
    )
    fully_resolves: EntityBoolean = Field(
        description="Whether this commit fully resolves the bug"
    )


class FeatureRealizedByCommit(EdgeModel):
    """
    Feature → Commit relationship metadata.
    """
    implementation_stage: EntityText = Field(
        description="Stage: initial, partial, complete"
    )
