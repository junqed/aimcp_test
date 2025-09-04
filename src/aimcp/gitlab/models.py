"""GitLab API response models."""

from datetime import datetime

from pydantic import BaseModel


class GitLabFile(BaseModel):
    """GitLab repository file information."""

    id: str
    name: str
    path: str
    type: str
    mode: str
    size: int | None = None
    last_commit_id: str | None = None


class GitLabFileContent(BaseModel):
    """GitLab file content response."""

    file_name: str
    file_path: str
    size: int
    encoding: str
    content_sha256: str | None = None
    ref: str
    blob_id: str
    commit_id: str
    last_commit_id: str
    content: str


class GitLabCommit(BaseModel):
    """GitLab commit information."""

    id: str
    short_id: str
    title: str
    message: str
    author_name: str
    author_email: str
    authored_date: datetime
    committer_name: str
    committer_email: str
    committed_date: datetime
    created_at: datetime


class GitLabProject(BaseModel):
    """GitLab project information."""

    id: int
    name: str
    path: str
    path_with_namespace: str
    description: str | None = None
    default_branch: str
    web_url: str
    ssh_url_to_repo: str
    http_url_to_repo: str
    created_at: datetime
    last_activity_at: datetime


class GitLabBranch(BaseModel):
    """GitLab branch information."""

    name: str
    merged: bool
    protected: bool
    default: bool
    developers_can_push: bool
    developers_can_merge: bool
    can_push: bool
    commit: GitLabCommit


class GitLabTree(BaseModel):
    """GitLab repository tree (directory listing)."""

    id: str
    name: str
    path: str
    type: str
    mode: str


class GitLabError(BaseModel):
    """GitLab API error response."""

    message: str
    error: str | None = None
    error_description: str | None = None
