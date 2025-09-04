"""Tool specification models for AIMCP."""

from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel


class ConflictResolutionStrategy(StrEnum):
    """Tool name conflict resolution strategies."""

    PREFIX = "prefix"
    PRIORITY = "priority"
    ERROR = "error"
    MERGE = "merge"


class MCPToolInput(BaseModel):
    """MCP tool input schema."""

    type: str
    description: str | None = None
    required: bool = False


class MCPTool(BaseModel):
    """MCP tool specification."""

    name: str
    description: str
    inputSchema: dict[str, MCPToolInput] | None = None
    resources: list[str] = []


class ToolsSpecification(BaseModel):
    """Complete tools.json specification."""

    tools: list[MCPTool]
    version: str = "1.0"


@dataclass(slots=True)
class ResolvedTool:
    """Tool with conflict resolution applied."""

    original_name: str
    resolved_name: str
    repository: str
    branch: str
    specification: MCPTool
    resource_uris: list[str]


@dataclass(slots=True)
class ToolConflict:
    """Tool name conflict information."""

    name: str
    repositories: list[str]
    strategy_applied: ConflictResolutionStrategy
    resolution: str
