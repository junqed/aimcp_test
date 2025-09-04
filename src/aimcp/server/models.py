"""MCP server data models."""

from dataclasses import dataclass
from datetime import datetime

from pydantic import BaseModel


@dataclass(slots=True)
class RuleResource:
    """Rule file resource for MCP clients."""

    uri: str
    name: str
    description: str
    mime_type: str = "text/plain"


@dataclass(slots=True)
class RepositoryInfo:
    """Repository information for MCP clients."""

    url: str
    branch: str
    name: str
    rule_count: int
    last_updated: datetime | None = None
    status: str = "unknown"


class CacheStatusResource(BaseModel):
    """Cache status resource for monitoring."""

    backend: str
    item_count: int
    hit_rate: float
    memory_usage_mb: float | None = None
    storage_usage_mb: float | None = None


class RuleApplicationPrompt(BaseModel):
    """Prompt template for applying rules."""

    name: str
    description: str
    arguments: dict[str, str]


class RepositoryStatus(BaseModel):
    """Repository connectivity and status."""

    repository: str
    branch: str
    accessible: bool
    rule_count: int
    last_check: datetime
    error: str | None = None


class RefreshResult(BaseModel):
    """Result of rule refresh operation."""

    success: bool
    repository: str | None = None
    updated_files: int = 0
    cached_files: int = 0
    errors: list[str] = []
