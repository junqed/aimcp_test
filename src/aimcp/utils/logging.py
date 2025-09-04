"""Logging configuration and utilities."""

import logging
import sys

import structlog
from structlog.typing import FilteringBoundLogger

from ..config.models import LoggingConfig


def setup_logging(config: LoggingConfig) -> FilteringBoundLogger:
    """Set up structured logging.

    Args:
        config: Logging configuration

    Returns:
        Configured logger
    """
    # Configure standard library logging
    logging.basicConfig(
        level=getattr(logging, config.level.upper()),
        format=config.format,
        stream=sys.stdout,
    )

    if config.structured:
        # Configure structlog
        structlog.configure(
            processors=[
                structlog.stdlib.filter_by_level,
                structlog.stdlib.add_logger_name,
                structlog.stdlib.add_log_level,
                structlog.stdlib.PositionalArgumentsFormatter(),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            logger_factory=structlog.stdlib.LoggerFactory(),
            context_class=dict,
            cache_logger_on_first_use=True,
        )

        return structlog.get_logger("aimcp")
    else:
        # Use standard logging
        logger = logging.getLogger("aimcp")
        return logger  # type: ignore


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """Get a logger instance.

    Args:
        name: Optional logger name

    Returns:
        Logger instance
    """
    if name:
        return structlog.get_logger(f"aimcp.{name}")
    return structlog.get_logger("aimcp")
