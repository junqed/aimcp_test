"""Tool specification models for AIMCP."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ConflictResolutionStrategy(StrEnum):
    """Tool name conflict resolution strategies."""

    PREFIX = "prefix"
    PRIORITY = "priority"
    ERROR = "error"
    MERGE = "merge"


class MCPResourceAnnotations(BaseModel):
    """MCP resource annotations."""

    audience: list[str] | None = None
    priority: float | None = Field(None, ge=0.0, le=1.0)
    lastModified: datetime | None = None


class MCPResource(BaseModel):
    """MCP resource specification according to MCP spec."""

    uri: str
    name: str
    title: str | None = None
    description: str | None = None
    mimeType: str | None = None
    size: int | None = None
    annotations: MCPResourceAnnotations | None = None


class MCPToolAnnotations(BaseModel):
    """MCP tool annotations."""

    # Tool behavior annotations as defined in spec
    # Extensible for future annotations
    pass


class MCPTool(BaseModel):
    """MCP tool specification according to MCP spec."""

    name: str
    title: str | None = None
    description: str
    inputSchema: dict[str, Any] | None = None  # JSON Schema as dict
    outputSchema: dict[str, Any] | None = None  # JSON Schema as dict
    annotations: MCPToolAnnotations | None = None


class ToolsSpecification(BaseModel):
    """Complete tools.json specification."""

    tools: list[MCPTool] = []
    resources: list[MCPResource] = []  # Separate from tools per MCP spec
    version: str = "1.0"


@dataclass(slots=True)
class ResolvedTool:
    """Tool with conflict resolution applied."""

    original_name: str
    resolved_name: str
    repository: str
    branch: str
    specification: MCPTool
    related_resources: list[MCPResource] = None  # Resources associated with this tool

    def __post_init__(self) -> None:
        """Initialize related_resources if None."""
        if self.related_resources is None:
            self.related_resources = []


@dataclass(slots=True)
class ToolConflict:
    """Tool name conflict information."""

    name: str
    repositories: list[str]
    strategy_applied: ConflictResolutionStrategy
    resolution: str
