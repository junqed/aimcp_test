"""Configuration loading and management."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import AIMCPConfig


class Settings(BaseSettings):
    """Settings loader with environment variable support."""

    model_config = SettingsConfigDict(
        env_prefix="AIMCP_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra="ignore"
    )

    # Server settings
    server_host: str = "127.0.0.1"
    server_port: int = 8000
    server_transport: str = "stdio"
    server_name: str = "AIMCP"

    # GitLab settings
    gitlab_instance_url: str | None = None
    gitlab_token: str | None = None

    # Cache settings
    cache_backend: str = "memory"
    cache_ttl_seconds: int = 3600
    cache_max_size: int = 1000
    cache_storage_path: str | None = None

    # Logging settings
    logging_level: str = "INFO"
    logging_structured: bool = True
    logging_format: str = "%(message)s"

    # Rule settings
    rules_validate_syntax: bool = True
    rules_merge_strategy: str = "append"
    rules_max_file_size: int = 1024 * 1024
    rules_encoding: str = "utf-8"


def load_config_from_file(config_path: Path) -> dict[str, Any]:
    """Load configuration from YAML file.

    Args:
        config_path: Path to the configuration file

    Returns:
        Configuration dictionary

    Raises:
        FileNotFoundError: If config file doesn't exist
        yaml.YAMLError: If config file is invalid YAML
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    try:
        with config_path.open("r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except yaml.YAMLError as e:
        raise yaml.YAMLError(f"Invalid YAML in config file {config_path}: {e}")


def create_config(
    config_path: Path | None = None,
    override_settings: dict[str, Any] | None = None
) -> AIMCPConfig:
    """Create configuration from file and environment variables.

    Args:
        config_path: Optional path to configuration file
        override_settings: Optional settings to override

    Returns:
        Validated AIMCP configuration

    Raises:
        ValidationError: If configuration is invalid
    """
    # Start with settings from environment
    settings = Settings()

    # Load from file if provided
    file_config = {}
    if config_path:
        file_config = load_config_from_file(config_path)

    # Apply overrides
    overrides = override_settings or {}

    # Build configuration dictionary
    config_dict = {
        "server": {
            "host": overrides.get("host", file_config.get("server", {}).get("host", settings.server_host)),
            "port": overrides.get("port", file_config.get("server", {}).get("port", settings.server_port)),
            "transport": overrides.get("transport", file_config.get("server", {}).get("transport", settings.server_transport)),
            "name": file_config.get("server", {}).get("name", settings.server_name),
        },
        "gitlab": file_config.get("gitlab", {}),
        "cache": {
            "backend": file_config.get("cache", {}).get("backend", settings.cache_backend),
            "ttl_seconds": file_config.get("cache", {}).get("ttl_seconds", settings.cache_ttl_seconds),
            "max_size": file_config.get("cache", {}).get("max_size", settings.cache_max_size),
            "storage_path": file_config.get("cache", {}).get("storage_path", settings.cache_storage_path),
        },
        "logging": {
            "level": file_config.get("logging", {}).get("level", settings.logging_level),
            "structured": file_config.get("logging", {}).get("structured", settings.logging_structured),
            "format": file_config.get("logging", {}).get("format", settings.logging_format),
        },
        "rules": {
            "validate_syntax": file_config.get("rules", {}).get("validate_syntax", settings.rules_validate_syntax),
            "merge_strategy": file_config.get("rules", {}).get("merge_strategy", settings.rules_merge_strategy),
            "max_file_size": file_config.get("rules", {}).get("max_file_size", settings.rules_max_file_size),
            "encoding": file_config.get("rules", {}).get("encoding", settings.rules_encoding),
        },
    }

    # Override GitLab settings from environment if available
    if settings.gitlab_instance_url:
        config_dict["gitlab"]["instance_url"] = settings.gitlab_instance_url
    if settings.gitlab_token:
        config_dict["gitlab"]["token"] = settings.gitlab_token

    return AIMCPConfig.model_validate(config_dict)


def validate_config(config: AIMCPConfig) -> None:
    """Validate configuration for common issues.

    Args:
        config: Configuration to validate

    Raises:
        ValueError: If configuration has issues
    """
    # Check GitLab configuration
    if not config.gitlab.token:
        raise ValueError("GitLab token is required")

    if not config.gitlab.repositories:
        raise ValueError("At least one GitLab repository must be configured")

    # Check cache configuration
    if config.cache.backend == "file" and not config.cache.storage_path:
        raise ValueError("Storage path is required for file-based cache")

    # Check server configuration
    if config.server.port < 1 or config.server.port > 65535:
        raise ValueError("Server port must be between 1 and 65535")
