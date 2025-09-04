"""Cache storage implementations."""

import asyncio
import fnmatch
import json
import sys
import tempfile
from collections import OrderedDict
from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger
from .models import CacheEntry, CacheKey, CacheStats

logger = get_logger("cache")


class MemoryCache:
    """In-memory cache with LRU eviction."""

    def __init__(self, max_size: int = 1000, default_ttl_seconds: int = 3600) -> None:
        """Initialize memory cache.

        Args:
            max_size: Maximum number of items
            default_ttl_seconds: Default TTL for entries
        """
        self.max_size = max_size
        self.default_ttl_seconds = default_ttl_seconds
        self._cache: OrderedDict[CacheKey, CacheEntry] = OrderedDict()
        self._lock = asyncio.Lock()
        self._stats = CacheStats(item_count=0)

    async def get(self, key: CacheKey) -> Any | None:
        """Get value from cache."""
        async with self._lock:
            if key not in self._cache:
                self._stats.miss_count += 1
                return None

            entry = self._cache[key]

            # Check expiration
            if entry.is_expired:
                del self._cache[key]
                self._stats.item_count -= 1
                self._stats.miss_count += 1
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            entry.access()
            self._stats.hit_count += 1

            return entry.value

    async def set(
        self,
        key: CacheKey,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """Set value in cache."""
        async with self._lock:
            ttl = ttl_seconds or self.default_ttl_seconds

            # Calculate size estimate
            size_bytes = self._estimate_size(value)

            entry = CacheEntry(
                value=value,
                created_at=datetime.now(),
                ttl_seconds=ttl,
                size_bytes=size_bytes,
            )

            # Remove if already exists
            if key in self._cache:
                del self._cache[key]
                self._stats.item_count -= 1

            # Add new entry
            self._cache[key] = entry
            self._cache.move_to_end(key)
            self._stats.item_count += 1

            # Evict if over size limit
            while len(self._cache) > self.max_size:
                oldest_key = next(iter(self._cache))
                del self._cache[oldest_key]
                self._stats.item_count -= 1

                logger.debug("Evicted cache entry", key=oldest_key)

    async def delete(self, key: CacheKey) -> bool:
        """Delete value from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
                self._stats.item_count -= 1
                return True
            return False

    async def exists(self, key: CacheKey) -> bool:
        """Check if key exists."""
        async with self._lock:
            if key not in self._cache:
                return False

            entry = self._cache[key]
            if entry.is_expired:
                del self._cache[key]
                self._stats.item_count -= 1
                return False

            return True

    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            self._cache.clear()
            self._stats.item_count = 0
            logger.info("Cleared memory cache")

    async def keys(self, pattern: str | None = None) -> AsyncIterator[CacheKey]:
        """Get cache keys."""
        async with self._lock:
            keys_list = list(self._cache.keys())

        for key in keys_list:
            # Check if still valid
            if await self.exists(key):
                if pattern is None or fnmatch.fnmatch(key, pattern):
                    yield key

    async def size(self) -> int:
        """Get cache size."""
        return len(self._cache)

    async def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        async with self._lock:
            memory_usage = sum(
                entry.size_bytes or 0
                for entry in self._cache.values()
                if entry.size_bytes is not None
            )

            timestamps = [entry.created_at for entry in self._cache.values()]

            return CacheStats(
                item_count=len(self._cache),
                hit_count=self._stats.hit_count,
                miss_count=self._stats.miss_count,
                memory_usage_bytes=memory_usage or None,
                oldest_entry=min(timestamps) if timestamps else None,
                newest_entry=max(timestamps) if timestamps else None,
            )

    async def cleanup_expired(self) -> int:
        """Clean up expired entries."""
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() if entry.is_expired
            ]

            for key in expired_keys:
                del self._cache[key]
                self._stats.item_count -= 1

            if expired_keys:
                logger.info("Cleaned up expired entries", count=len(expired_keys))

            return len(expired_keys)

    async def close(self) -> None:
        """Close cache."""
        await self.clear()

    def _estimate_size(self, value: Any) -> int:
        """Estimate memory size of value."""
        try:
            if isinstance(value, str):
                return len(value.encode("utf-8"))
            elif isinstance(value, int | float):
                return sys.getsizeof(value)
            elif isinstance(value, list | tuple | dict):
                return sys.getsizeof(value)
            else:
                return sys.getsizeof(str(value))
        except Exception:
            return 0


class FileCache:
    """File-based persistent cache."""

    def __init__(
        self,
        storage_path: Path,
        max_size: int = 1000,
        default_ttl_seconds: int = 3600,
    ) -> None:
        """Initialize file cache.

        Args:
            storage_path: Directory for cache files
            max_size: Maximum number of items
            default_ttl_seconds: Default TTL for entries
        """
        self.storage_path = Path(storage_path)
        self.max_size = max_size
        self.default_ttl_seconds = default_ttl_seconds
        self._lock = asyncio.Lock()
        self._stats = CacheStats(item_count=0)

        # Create storage directory
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # Index file for metadata
        self.index_path = self.storage_path / "index.json"
        self._load_index()

    def _load_index(self) -> None:
        """Load cache index from disk."""
        if self.index_path.exists():
            try:
                with self.index_path.open("r") as f:
                    index_data = json.load(f)
                    self._stats = CacheStats(**index_data.get("stats", {}))
            except Exception as e:
                logger.warning("Failed to load cache index", error=str(e))
                self._stats = CacheStats(item_count=0)

    def _save_index(self) -> None:
        """Save cache index to disk."""
        try:
            index_data = {
                "stats": self._stats.model_dump(),
                "updated_at": datetime.now().isoformat(),
            }

            # Atomic write
            with tempfile.NamedTemporaryFile(
                mode="w", dir=self.storage_path, delete=False
            ) as f:
                json.dump(index_data, f, indent=2)
                temp_path = Path(f.name)

            temp_path.replace(self.index_path)

        except Exception as e:
            logger.error("Failed to save cache index", error=str(e))

    def _get_file_path(self, key: CacheKey) -> Path:
        """Get file path for cache key."""
        # Use hash to avoid filesystem issues with special characters
        key_hash = str(hash(key))
        return self.storage_path / f"{key_hash}.json"

    async def get(self, key: CacheKey) -> Any | None:
        """Get value from cache."""
        file_path = self._get_file_path(key)

        if not file_path.exists():
            self._stats.miss_count += 1
            return None

        try:
            with file_path.open("r") as f:
                data = json.load(f)

            # Parse entry
            entry = CacheEntry(
                value=data["value"],
                created_at=datetime.fromisoformat(data["created_at"]),
                ttl_seconds=data.get("ttl_seconds"),
                access_count=data.get("access_count", 0),
                last_accessed=datetime.fromisoformat(data["last_accessed"])
                if data.get("last_accessed")
                else None,
                size_bytes=data.get("size_bytes"),
            )

            # Check expiration
            if entry.is_expired:
                file_path.unlink(missing_ok=True)
                self._stats.miss_count += 1
                return None

            # Update access info
            entry.access()

            # Save updated entry
            await self._save_entry(key, entry)

            self._stats.hit_count += 1
            return entry.value

        except Exception as e:
            logger.error("Failed to read cache file", key=key, error=str(e))
            self._stats.miss_count += 1
            return None

    async def set(
        self,
        key: CacheKey,
        value: Any,
        ttl_seconds: int | None = None,
    ) -> None:
        """Set value in cache."""
        async with self._lock:
            ttl = ttl_seconds or self.default_ttl_seconds

            entry = CacheEntry(
                value=value,
                created_at=datetime.now(),
                ttl_seconds=ttl,
                size_bytes=len(str(value).encode("utf-8"))
                if isinstance(value, str)
                else None,
            )

            await self._save_entry(key, entry)

            # Update stats
            if not await self.exists(key):
                self._stats.item_count += 1

            # Evict old entries if over limit
            await self._evict_if_needed()

            self._save_index()

    async def _save_entry(self, key: CacheKey, entry: CacheEntry) -> None:
        """Save entry to file."""
        file_path = self._get_file_path(key)

        data = {
            "key": key,
            "value": entry.value,
            "created_at": entry.created_at.isoformat(),
            "ttl_seconds": entry.ttl_seconds,
            "access_count": entry.access_count,
            "last_accessed": entry.last_accessed.isoformat()
            if entry.last_accessed
            else None,
            "size_bytes": entry.size_bytes,
        }

        # Atomic write
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=self.storage_path,
            delete=False,
            suffix=".tmp",
        ) as f:
            json.dump(data, f, indent=2)
            temp_path = Path(f.name)

        temp_path.replace(file_path)

    async def _evict_if_needed(self) -> None:
        """Evict old entries if over size limit."""
        cache_files = list(self.storage_path.glob("*.json"))
        if self.index_path in cache_files:
            cache_files.remove(self.index_path)

        if len(cache_files) <= self.max_size:
            return

        # Sort by modification time (oldest first)
        cache_files.sort(key=lambda p: p.stat().st_mtime)

        # Remove oldest files
        to_remove = len(cache_files) - self.max_size
        for file_path in cache_files[:to_remove]:
            file_path.unlink(missing_ok=True)
            self._stats.item_count -= 1

        logger.debug("Evicted cache files", count=to_remove)

    async def delete(self, key: CacheKey) -> bool:
        """Delete value from cache."""
        file_path = self._get_file_path(key)
        if file_path.exists():
            file_path.unlink()
            self._stats.item_count -= 1
            self._save_index()
            return True
        return False

    async def exists(self, key: CacheKey) -> bool:
        """Check if key exists."""
        file_path = self._get_file_path(key)
        if not file_path.exists():
            return False

        # Check if expired by trying to get it
        value = await self.get(key)
        return value is not None

    async def clear(self) -> None:
        """Clear all entries."""
        async with self._lock:
            for file_path in self.storage_path.glob("*.json"):
                if file_path != self.index_path:
                    file_path.unlink(missing_ok=True)

            self._stats.item_count = 0
            self._save_index()

            logger.info("Cleared file cache", path=self.storage_path)

    async def keys(self, pattern: str | None = None) -> AsyncIterator[CacheKey]:
        """Get cache keys."""
        for file_path in self.storage_path.glob("*.json"):
            if file_path == self.index_path:
                continue

            try:
                with file_path.open("r") as f:
                    data = json.load(f)
                    key = data.get("key")

                    if key and await self.exists(key):
                        if pattern is None or fnmatch.fnmatch(key, pattern):
                            yield key

            except Exception as e:
                logger.warning(
                    "Failed to read cache file", file=file_path, error=str(e)
                )
                continue

    async def size(self) -> int:
        """Get cache size."""
        cache_files = list(self.storage_path.glob("*.json"))
        if self.index_path in cache_files:
            cache_files.remove(self.index_path)
        return len(cache_files)

    async def get_stats(self) -> CacheStats:
        """Get cache statistics."""
        # Calculate storage usage
        storage_usage = sum(
            f.stat().st_size
            for f in self.storage_path.glob("*.json")
            if f != self.index_path
        )

        # Get file timestamps
        timestamps = []
        for file_path in self.storage_path.glob("*.json"):
            if file_path == self.index_path:
                continue
            timestamps.append(datetime.fromtimestamp(file_path.stat().st_mtime))

        current_stats = await self.size()

        return CacheStats(
            item_count=current_stats,
            hit_count=self._stats.hit_count,
            miss_count=self._stats.miss_count,
            storage_usage_bytes=storage_usage,
            oldest_entry=min(timestamps) if timestamps else None,
            newest_entry=max(timestamps) if timestamps else None,
        )

    async def cleanup_expired(self) -> int:
        """Clean up expired entries."""
        expired_count = 0

        for file_path in self.storage_path.glob("*.json"):
            if file_path == self.index_path:
                continue

            try:
                with file_path.open("r") as f:
                    data = json.load(f)

                entry = CacheEntry(
                    value=data["value"],
                    created_at=datetime.fromisoformat(data["created_at"]),
                    ttl_seconds=data.get("ttl_seconds"),
                )

                if entry.is_expired:
                    file_path.unlink()
                    expired_count += 1
                    self._stats.item_count -= 1

            except Exception as e:
                logger.warning(
                    "Failed to check cache file expiration",
                    file=file_path,
                    error=str(e),
                )
                continue

        if expired_count > 0:
            self._save_index()
            logger.info("Cleaned up expired cache files", count=expired_count)

        return expired_count

    async def close(self) -> None:
        """Close cache."""
        self._save_index()
