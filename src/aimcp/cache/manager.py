"""Cache manager with high-level operations."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from ..config.models import GitLabRepository
from ..utils.logging import get_logger
from .models import CacheKey, CacheStats, RepositoryCacheKey
from .protocol import CacheProtocol

logger = get_logger("cache.manager")


@dataclass(slots=True)
class CacheManager:
    """High-level cache manager."""

    cache: CacheProtocol
    _cleanup_task: asyncio.Task[None] | None = None

    def __post_init__(self) -> None:
        """Post-initialization setup."""
        logger.info("Cache manager initialized")

    async def start(self) -> None:
        """Start cache manager and background tasks."""
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Cache manager started")

    async def stop(self) -> None:
        """Stop cache manager and cleanup."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        await self.cache.close()
        logger.info("Cache manager stopped")

    async def __aenter__(self) -> "CacheManager":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Async context manager exit."""
        await self.stop()

    async def _cleanup_loop(self) -> None:
        """Background cleanup loop."""
        while True:
            try:
                await asyncio.sleep(300)  # Cleanup every 5 minutes

                cleaned_count = await self.cache.cleanup_expired()
                if cleaned_count > 0:
                    logger.info("Background cleanup completed", count=cleaned_count)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in cleanup loop", error=str(e))
                await asyncio.sleep(60)  # Wait before retrying

    def _make_repository_key(
        self,
        repository: GitLabRepository,
        file_path: str,
    ) -> CacheKey:
        """Create cache key for repository file.

        Args:
            repository: Repository configuration
            file_path: File path within repository

        Returns:
            Cache key
        """
        key = RepositoryCacheKey(
            repository_url=repository.url,
            branch=repository.branch,
            file_path=file_path,
        )
        return key.to_key()

    async def get_rule_file(
        self,
        repository: GitLabRepository,
        file_path: str,
    ) -> str | None:
        """Get cached rule file content.

        Args:
            repository: Repository configuration
            file_path: File path within repository

        Returns:
            File content or None if not cached
        """
        key = self._make_repository_key(repository, file_path)
        content = await self.cache.get(key)

        if content:
            logger.debug(
                "Cache hit for rule file", repository=repository.url, file=file_path
            )
        else:
            logger.debug(
                "Cache miss for rule file", repository=repository.url, file=file_path
            )

        return content

    async def set_rule_file(
        self,
        repository: GitLabRepository,
        file_path: str,
        content: str,
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache rule file content.

        Args:
            repository: Repository configuration
            file_path: File path within repository
            content: File content to cache
            ttl_seconds: TTL override (optional)
        """
        key = self._make_repository_key(repository, file_path)
        await self.cache.set(key, content, ttl_seconds)

        logger.debug(
            "Cached rule file",
            repository=repository.url,
            file=file_path,
            size=len(content),
        )

    async def cache_repository_rules(
        self,
        repository: GitLabRepository,
        rule_files: dict[str, str],
        ttl_seconds: int | None = None,
    ) -> None:
        """Cache all rule files from a repository.

        Args:
            repository: Repository configuration
            rule_files: Dictionary mapping file paths to content
            ttl_seconds: TTL override (optional)
        """
        for file_path, content in rule_files.items():
            await self.set_rule_file(repository, file_path, content, ttl_seconds)

        logger.info(
            "Cached repository rules",
            repository=repository.url,
            branch=repository.branch,
            count=len(rule_files),
        )

    async def get_repository_rules(
        self,
        repository: GitLabRepository,
    ) -> dict[str, str]:
        """Get all cached rule files for a repository.

        Args:
            repository: Repository configuration

        Returns:
            Dictionary mapping file paths to content
        """
        # Find all keys for this repository
        pattern = f"{repository.url}:{repository.branch}:*"
        rule_files = {}

        async for key in self.cache.keys(pattern):
            try:
                repo_key = RepositoryCacheKey.from_key(key)
                content = await self.cache.get(key)

                if content:
                    rule_files[repo_key.file_path] = content

            except Exception as e:
                logger.warning("Failed to get cached rule file", key=key, error=str(e))
                continue

        logger.debug(
            "Retrieved repository rules from cache",
            repository=repository.url,
            branch=repository.branch,
            count=len(rule_files),
        )

        return rule_files

    async def invalidate_repository(self, repository: GitLabRepository) -> int:
        """Invalidate all cached files for a repository.

        Args:
            repository: Repository configuration

        Returns:
            Number of invalidated entries
        """
        pattern = f"{repository.url}:{repository.branch}:*"
        invalidated = 0

        async for key in self.cache.keys(pattern):
            if await self.cache.delete(key):
                invalidated += 1

        logger.info(
            "Invalidated repository cache",
            repository=repository.url,
            branch=repository.branch,
            count=invalidated,
        )

        return invalidated

    async def invalidate_file(
        self,
        repository: GitLabRepository,
        file_path: str,
    ) -> bool:
        """Invalidate specific cached file.

        Args:
            repository: Repository configuration
            file_path: File path within repository

        Returns:
            True if file was cached and invalidated
        """
        key = self._make_repository_key(repository, file_path)
        result = await self.cache.delete(key)

        if result:
            logger.debug(
                "Invalidated cached file", repository=repository.url, file=file_path
            )

        return result

    async def clear_all(self) -> None:
        """Clear all cached data."""
        await self.cache.clear()
        logger.info("Cleared all cached data")

    async def get_stats(self) -> CacheStats:
        """Get cache statistics.

        Returns:
            Cache statistics
        """
        return await self.cache.get_stats()

    async def get_repository_stats(
        self, repository: GitLabRepository
    ) -> dict[str, int | str]:
        """Get statistics for a specific repository.

        Args:
            repository: Repository configuration

        Returns:
            Repository-specific statistics
        """
        pattern = f"{repository.url}:{repository.branch}:*"
        file_count = 0

        async for _ in self.cache.keys(pattern):
            file_count += 1

        return {
            "cached_files": file_count,
            "repository": repository.url,
            "branch": repository.branch,
        }

    async def cleanup_expired(self) -> int:
        """Manually trigger cleanup of expired entries.

        Returns:
            Number of cleaned up entries
        """
        count = await self.cache.cleanup_expired()
        logger.info("Manual cleanup completed", count=count)
        return count

    async def warm_cache(
        self,
        repositories: list[GitLabRepository],
        fetch_function: Callable[[GitLabRepository], Awaitable[dict[str, str]]],
    ) -> None:
        """Warm cache with rule files from repositories.

        Args:
            repositories: List of repositories to warm
            fetch_function: Function to fetch rule files
        """
        logger.info("Starting cache warm-up", repositories=len(repositories))

        for repository in repositories:
            try:
                # Check if we already have cached data
                cached_rules = await self.get_repository_rules(repository)
                if cached_rules:
                    logger.debug(
                        "Repository already cached, skipping warm-up",
                        repository=repository.url,
                    )
                    continue

                # Fetch fresh data
                rule_files = await fetch_function(repository)
                await self.cache_repository_rules(repository, rule_files)

                logger.debug(
                    "Warmed cache for repository",
                    repository=repository.url,
                    count=len(rule_files),
                )

            except Exception as e:
                logger.error(
                    "Failed to warm cache for repository",
                    repository=repository.url,
                    error=str(e),
                )
                continue

        logger.info("Cache warm-up completed")

    # Generic cache methods for non-rule content
    async def get(self, key: str) -> Any | None:
        """Get value from cache using string key.

        Args:
            key: String cache key

        Returns:
            Cached value or None if not found
        """
        return await self.cache.get(key)

    async def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        """Set value in cache using string key.

        Args:
            key: String cache key
            value: Value to cache
            ttl: Optional TTL override
        """
        await self.cache.set(key, value, ttl)
