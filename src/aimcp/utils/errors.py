"""Enhanced error handling utilities and custom exceptions."""

import asyncio
import functools
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from typing import Any, TypeVar

from .logging import get_logger

logger = get_logger("errors")

T = TypeVar("T")


class AIMCPError(Exception):
    """Base exception for all AIMCP errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class ConfigurationError(AIMCPError):
    """Configuration-related errors."""


class GitLabError(AIMCPError):
    """GitLab-related errors."""


class CacheError(AIMCPError):
    """Cache-related errors."""


class MCPError(AIMCPError):
    """MCP server-related errors."""


class NetworkError(AIMCPError):
    """Network connectivity errors."""


def retry_async(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for retrying async operations with exponential backoff.

    Args:
        max_attempts: Maximum number of retry attempts
        delay: Initial delay between retries in seconds
        backoff_factor: Multiplier for delay on each retry
        exceptions: Exception types to retry on

    Returns:
        Decorated function with retry logic
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = delay

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    if attempt == max_attempts - 1:
                        logger.error(
                            "Retry exhausted for function",
                            function=func.__name__,
                            attempt=attempt + 1,
                            max_attempts=max_attempts,
                            error=str(e)
                        )
                        raise

                    logger.warning(
                        "Function failed, retrying",
                        function=func.__name__,
                        attempt=attempt + 1,
                        max_attempts=max_attempts,
                        delay=current_delay,
                        error=str(e)
                    )

                    await asyncio.sleep(current_delay)
                    current_delay *= backoff_factor

            return None  # Should never reach here

        return wrapper
    return decorator


@asynccontextmanager
async def error_context(
    operation: str,
    *,
    reraise: bool = True,
) -> AsyncGenerator[None]:
    """Context manager for standardized error handling and logging.

    Args:
        operation: Description of the operation being performed
        reraise: Whether to re-raise exceptions after logging

    Yields:
        None

    Raises:
        Exception: Re-raises the original exception if reraise=True
    """
    try:
        logger.debug("Starting operation", operation=operation)
        yield
        logger.debug("Operation completed successfully", operation=operation)
    except Exception as e:
        logger.error(
            "Operation failed",
            operation=operation,
            error_type=type(e).__name__,
            error=str(e)
        )

        if reraise:
            raise


@asynccontextmanager
async def resource_cleanup(*resources: Any) -> AsyncGenerator[None]:
    """Context manager for ensuring proper cleanup of async resources.

    Args:
        *resources: Resources that need cleanup (must have aclose() method)

    Yields:
        None
    """
    try:
        yield
    finally:
        cleanup_errors = []

        for resource in resources:
            try:
                if hasattr(resource, "aclose"):
                    await resource.aclose()
                elif hasattr(resource, "__aexit__"):
                    await resource.__aexit__(None, None, None)
                elif hasattr(resource, "close"):
                    resource.close()
                else:
                    logger.warning(
                        "Resource does not have cleanup method",
                        resource_type=type(resource).__name__
                    )
            except Exception as e:
                cleanup_errors.append(f"{type(resource).__name__}: {str(e)}")
                logger.error(
                    "Failed to cleanup resource",
                    resource_type=type(resource).__name__,
                    error=str(e)
                )

        if cleanup_errors:
            logger.warning(
                "Some resources failed to cleanup properly",
                errors=cleanup_errors
            )


def handle_async_errors(
    *,
    default_return: Any = None,
    log_level: str = "error",
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator for handling async function errors gracefully.

    Args:
        default_return: Value to return if exception occurs
        log_level: Log level for error messages

    Returns:
        Decorated function with error handling
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                getattr(logger, log_level)(
                    "Async function error handled",
                    function=func.__name__,
                    error_type=type(e).__name__,
                    error=str(e)
                )
                return default_return

        return wrapper
    return decorator


def safe_async(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator that prevents async functions from raising exceptions.

    Args:
        func: Async function to make safe

    Returns:
        Decorated function that logs errors but doesn't raise them
    """
    return handle_async_errors(default_return=None, log_level="error")(func)


class ErrorCollector:
    """Collect and manage multiple errors during complex operations."""

    def __init__(self, operation: str) -> None:
        self.operation = operation
        self.errors: list[tuple[str, Exception]] = []

    def add_error(self, context: str, error: Exception) -> None:
        """Add an error to the collection."""
        self.errors.append((context, error))
        logger.warning(
            "Error collected",
            operation=self.operation,
            context=context,
            error=str(error)
        )

    def has_errors(self) -> bool:
        """Check if any errors have been collected."""
        return len(self.errors) > 0

    def get_summary(self) -> str:
        """Get a summary of all collected errors."""
        if not self.errors:
            return f"Operation '{self.operation}' completed successfully"

        error_lines = [f"Operation '{self.operation}' had {len(self.errors)} errors:"]
        for context, error in self.errors:
            error_lines.append(f"  - {context}: {str(error)}")

        return "\n".join(error_lines)

    def raise_if_errors(self) -> None:
        """Raise an AIMCPError if any errors were collected."""
        if self.errors:
            raise AIMCPError(
                message=f"Operation '{self.operation}' failed with {len(self.errors)} errors",
                details={
                    "operation": self.operation,
                    "error_count": len(self.errors),
                    "errors": [
                        {"context": context, "error": str(error)}
                        for context, error in self.errors
                    ]
                }
            )
