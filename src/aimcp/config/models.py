"""Configuration models for AIMCP."""

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, HttpUrl


class TransportType(StrEnum):
    """MCP server transport types."""

    STDIO = "stdio"
    HTTP = "http"
    SSE = "sse"


class LogLevel(StrEnum):
    """Log levels."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class CacheBackend(StrEnum):
    """Cache backend types."""

    MEMORY = "memory"
    FILE = "file"


class ServerConfig(BaseModel):
    """Server configuration."""

    host: str = Field(default="127.0.0.1")
    port: int = Field(default=8000)
    transport: TransportType = Field(default=TransportType.STDIO)
    name: str = Field(default="AIMCP")


class GitLabRepository(BaseModel):
    """GitLab repository configuration."""

    url: str
    branch: str = "main"
    file_patterns: list[str] = Field(
        default=["**/*.cursorrules", "**/*.copilot-instructions.md", "**/.cursorrules", "**/.copilot"]
    )


class GitLabConfig(BaseModel):
    """GitLab API configuration."""

    instance_url: HttpUrl
    token: str
    repositories: list[GitLabRepository]
    timeout: int = 30
    max_retries: int = 3


class CacheConfig(BaseModel):
    """Cache configuration."""

    backend: CacheBackend = CacheBackend.MEMORY
    ttl_seconds: int = 3600
    max_size: int = 1000
    storage_path: Path | None = None


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: LogLevel = LogLevel.INFO
    structured: bool = True
    format: str = "%(message)s"


class RuleConfig(BaseModel):
    """Rule processing configuration."""

    validate_syntax: bool = True
    merge_strategy: str = "append"
    max_file_size: int = 1024 * 1024
    encoding: str = "utf-8"


class AIMCPConfig(BaseModel):
    """Main AIMCP configuration."""

    server: ServerConfig = Field(default_factory=ServerConfig)
    gitlab: GitLabConfig
    cache: CacheConfig = Field(default_factory=CacheConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    rules: RuleConfig = Field(default_factory=RuleConfig)

    class Config:
        """Pydantic configuration."""

        extra = "forbid"
        validate_assignment = True
