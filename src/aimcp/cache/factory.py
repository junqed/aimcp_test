"""Cache factory for creating cache backends."""

from pathlib import Path

from ..config.models import CacheBackend, CacheConfig
from .manager import CacheManager
from .protocol import CacheProtocol
from .storage import FileCache, MemoryCache


def create_cache_backend(config: CacheConfig) -> CacheProtocol:
    """Create cache backend from configuration.

    Args:
        config: Cache configuration

    Returns:
        Cache backend instance

    Raises:
        ValueError: If backend is unknown or configuration is invalid
    """
    match config.backend:
        case CacheBackend.MEMORY:
            return MemoryCache(
                max_size=config.max_size,
                default_ttl_seconds=config.ttl_seconds,
            )
        case CacheBackend.FILE:
            if not config.storage_path:
                raise ValueError("storage_path is required for file cache backend")

            return FileCache(
                storage_path=Path(config.storage_path),
                max_size=config.max_size,
                default_ttl_seconds=config.ttl_seconds,
            )
        case _:
            raise ValueError(f"Unknown cache backend: {config.backend}")


def create_cache_manager(config: CacheConfig) -> CacheManager:
    """Create cache manager with configured backend.

    Args:
        config: Cache configuration

    Returns:
        Cache manager instance
    """
    backend = create_cache_backend(config)
    return CacheManager(cache=backend)
