"""Configuration models for AIMCP."""

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate server port range."""
        if not 1 <= v <= 65535:
            raise ValueError("Server port must be between 1 and 65535")
        return v


class GitLabRepository(BaseModel):
    """GitLab repository configuration."""

    url: str
    branch: str = "main"


class GitLabConfig(BaseModel):
    """GitLab API configuration."""

    instance_url: HttpUrl
    token: str
    repositories: list[GitLabRepository]
    timeout: int = 30
    max_retries: int = 3

    @field_validator("token")
    @classmethod
    def validate_token(cls, v: str) -> str:
        """Validate GitLab token is not empty."""
        if not v.strip():
            raise ValueError("GitLab token is required and cannot be empty")
        return v.strip()

    @field_validator("repositories")
    @classmethod
    def validate_repositories(cls, v: list[GitLabRepository]) -> list[GitLabRepository]:
        """Validate at least one repository is configured."""
        if not v:
            raise ValueError("At least one GitLab repository must be configured")
        return v


class CacheConfig(BaseModel):
    """Cache configuration."""

    backend: CacheBackend = CacheBackend.MEMORY
    ttl_seconds: int = 3600
    max_size: int = 1000
    storage_path: Path | None = None

    @model_validator(mode="after")
    def validate_file_backend(self) -> "CacheConfig":
        """Validate file backend configuration."""
        if self.backend == CacheBackend.FILE and not self.storage_path:
            raise ValueError("Storage path is required for file-based cache")
        return self


class LoggingConfig(BaseModel):
    """Logging configuration."""

    level: LogLevel = LogLevel.INFO
    structured: bool = True
    format: str | None = None


class ToolConfig(BaseModel):
    """Tool processing configuration."""

    conflict_resolution_strategy: str = "prefix"
    max_file_size: int = 1024 * 1024
    encoding: str = "utf-8"

    @field_validator("conflict_resolution_strategy")
    @classmethod
    def validate_conflict_strategy(cls, v: str) -> str:
        """Validate conflict resolution strategy."""
        allowed = {"prefix", "priority", "error", "merge"}
        if v not in allowed:
            raise ValueError(f"Conflict resolution strategy must be one of: {allowed}")
        return v


class AIMCPConfig(BaseSettings):
    """Main AIMCP configuration with file and environment support."""

    model_config = SettingsConfigDict(
        env_prefix="AIMCP_",
        env_nested_delimiter="__",
        case_sensitive=False,
        yaml_file="config.yaml",
        yaml_file_encoding="utf-8",
        validate_assignment=True,
    )

    server: ServerConfig = Field(default_factory=ServerConfig)
    gitlab: GitLabConfig
    cache: CacheConfig = Field(default_factory=CacheConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    tools: ToolConfig = Field(default_factory=ToolConfig)

    @classmethod
    def from_yaml_file(
        cls, file_path: Path, overrides: dict[str, Any] | None = None
    ) -> "AIMCPConfig":
        """Create configuration from YAML file with optional overrides.
        
        Args:
            file_path: Path to YAML configuration file
            overrides: Optional dictionary of override values
            
        Returns:
            Validated configuration instance
            
        Raises:
            FileNotFoundError: If config file doesn't exist
            yaml.YAMLError: If config file is invalid YAML
            ValidationError: If configuration is invalid
        """
        if not file_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {file_path}")

        try:
            with file_path.open("r", encoding="utf-8") as f:
                file_data = yaml.safe_load(f) or {}
        except yaml.YAMLError as e:
            raise yaml.YAMLError(f"Invalid YAML in config file {file_path}: {e}")

        # Apply overrides if provided
        if overrides:
            # Apply server overrides
            if any(k in overrides for k in ["host", "port", "transport"]):
                server_data = file_data.setdefault("server", {})
                for key in ["host", "port", "transport"]:
                    if key in overrides:
                        server_data[key] = overrides[key]

        return cls.model_validate(file_data)

    @classmethod
    def create(
        cls, 
        config_path: Path | None = None, 
        overrides: dict[str, Any] | None = None
    ) -> "AIMCPConfig":
        """Create configuration from file and environment with overrides.
        
        Args:
            config_path: Optional path to configuration file
            overrides: Optional settings to override
            
        Returns:
            Validated AIMCP configuration
        """
        if config_path:
            return cls.from_yaml_file(config_path, overrides)
        else:
            # Load from environment variables only
            config_data = overrides or {}
            return cls.model_validate(config_data)
