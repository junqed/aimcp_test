"""Cache protocol definition."""

from collections.abc import AsyncIterator
from typing import Any, Protocol

from .models import CacheKey, CacheStats


class CacheProtocol(Protocol):
    """Protocol for cache implementations."""

    async def get(self, key: CacheKey) -> Any | None:
        """Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/expired
        """
        ...

    async def set(
        self,
        key: CacheKey,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """Set value in cache.

        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Optional TTL override
        """
        ...

    async def delete(self, key: CacheKey) -> bool:
        """Delete value from cache.

        Args:
            key: Cache key

        Returns:
            True if key existed and was deleted
        """
        ...

    async def exists(self, key: CacheKey) -> bool:
        """Check if key exists in cache.

        Args:
            key: Cache key

        Returns:
            True if key exists and is not expired
        """
        ...

    async def clear(self) -> None:
        """Clear all cache entries."""
        ...

    def keys(self, pattern: str | None = None) -> AsyncIterator[CacheKey]:
        """Get cache keys, optionally filtered by pattern.

        Args:
            pattern: Optional glob pattern to filter keys

        Yields:
            Cache keys matching the pattern
        """
        ...

    async def size(self) -> int:
        """Get number of items in cache.

        Returns:
            Number of cached items
        """
        ...

    async def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            Cache statistics
        """
        ...

    async def cleanup_expired(self) -> int:
        """Clean up expired entries.

        Returns:
            Number of entries cleaned up
        """
        ...

    async def close(self) -> None:
        """Close cache and cleanup resources."""
        ...
