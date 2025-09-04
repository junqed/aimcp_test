"""Health check utilities for monitoring system status."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from ..cache.manager import CacheManager
from ..config.models import GitLabRepository
from ..gitlab.client import GitLabClient
from .logging import get_logger

logger = get_logger("health")


class HealthStatus(StrEnum):
    """Health check status values."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass(slots=True)
class HealthCheckResult:
    """Result of a health check."""

    component: str
    status: HealthStatus
    message: str
    details: dict[str, str | int | bool] | None = None
    checked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.checked_at is None:
            self.checked_at = datetime.now()


@dataclass(slots=True)
class SystemHealth:
    """Overall system health status."""

    status: HealthStatus
    checks: list[HealthCheckResult]
    checked_at: datetime

    @classmethod
    def from_checks(cls, checks: list[HealthCheckResult]) -> "SystemHealth":
        """Create system health from individual check results."""
        # Determine overall status
        if any(check.status == HealthStatus.UNHEALTHY for check in checks):
            overall_status = HealthStatus.UNHEALTHY
        elif any(check.status == HealthStatus.DEGRADED for check in checks):
            overall_status = HealthStatus.DEGRADED
        else:
            overall_status = HealthStatus.HEALTHY

        return cls(
            status=overall_status,
            checks=checks,
            checked_at=datetime.now(),
        )


class HealthChecker(Protocol):
    """Protocol for health check implementations."""

    async def check_health(self) -> HealthCheckResult:
        """Perform health check and return result."""
        ...


@dataclass(slots=True)
class GitLabHealthChecker:
    """Health checker for GitLab connectivity."""

    gitlab_client: GitLabClient
    repositories: list[GitLabRepository]

    async def check_health(self) -> HealthCheckResult:
        """Check GitLab connectivity and repository access."""
        try:
            # Test basic connection
            async with self.gitlab_client:
                connection_result = await self.gitlab_client.test_connection()

                if connection_result["status"] != "success":
                    return HealthCheckResult(
                        component="gitlab",
                        status=HealthStatus.UNHEALTHY,
                        message=f"GitLab connection failed: {connection_result['error']}",
                    )

                # Test repository access
                accessible_repos = 0
                total_repos = len(self.repositories)

                for repo in self.repositories:
                    try:
                        await self.gitlab_client.get_project(repo.url)
                        accessible_repos += 1
                    except Exception as e:
                        logger.warning(
                            "Repository check failed", repository=repo.url, error=str(e)
                        )

                if accessible_repos == 0:
                    status = HealthStatus.UNHEALTHY
                    message = "No repositories accessible"
                elif accessible_repos < total_repos:
                    status = HealthStatus.DEGRADED
                    message = (
                        f"Only {accessible_repos}/{total_repos} repositories accessible"
                    )
                else:
                    status = HealthStatus.HEALTHY
                    message = "All repositories accessible"

                return HealthCheckResult(
                    component="gitlab",
                    status=status,
                    message=message,
                    details={
                        "user": connection_result.get("user", "unknown"),
                        "gitlab_version": connection_result.get(
                            "gitlab_version", "unknown"
                        ),
                        "accessible_repos": accessible_repos,
                        "total_repos": total_repos,
                    },
                )

        except Exception as e:
            logger.error("GitLab health check failed", error=str(e))
            return HealthCheckResult(
                component="gitlab",
                status=HealthStatus.UNHEALTHY,
                message=f"GitLab health check failed: {str(e)}",
            )


@dataclass(slots=True)
class CacheHealthChecker:
    """Health checker for cache system."""

    cache_manager: CacheManager

    async def check_health(self) -> HealthCheckResult:
        """Check cache system health and performance."""
        try:
            async with self.cache_manager:
                stats = await self.cache_manager.get_stats()

                # Determine status based on cache performance
                if stats.item_count == 0:
                    status = HealthStatus.DEGRADED
                    message = "Cache is empty"
                elif stats.hit_rate < 0.5:
                    status = HealthStatus.DEGRADED
                    message = f"Low cache hit rate: {stats.hit_rate:.2%}"
                else:
                    status = HealthStatus.HEALTHY
                    message = f"Cache performing well (hit rate: {stats.hit_rate:.2%})"

                details: dict[str, str | int | bool] = {
                    "item_count": stats.item_count,
                    "hit_rate": f"{stats.hit_rate:.2%}",
                    "hit_count": stats.hit_count,
                    "miss_count": stats.miss_count,
                }

                if stats.memory_usage_bytes:
                    details["memory_usage_mb"] = (
                        f"{stats.memory_usage_bytes / 1024 / 1024:.2f}"
                    )

                if stats.storage_usage_bytes:
                    details["storage_usage_mb"] = (
                        f"{stats.storage_usage_bytes / 1024 / 1024:.2f}"
                    )

                return HealthCheckResult(
                    component="cache",
                    status=status,
                    message=message,
                    details=details,
                )

        except Exception as e:
            logger.error("Cache health check failed", error=str(e))
            return HealthCheckResult(
                component="cache",
                status=HealthStatus.UNHEALTHY,
                message=f"Cache health check failed: {str(e)}",
            )


@dataclass(slots=True)
class SystemHealthChecker:
    """Main system health checker coordinating all health checks."""

    checkers: list[HealthChecker]

    async def check_all(self) -> SystemHealth:
        """Run all health checks and return overall system health."""
        logger.info("Running system health checks")

        checks = []
        for checker in self.checkers:
            try:
                result = await checker.check_health()
                checks.append(result)
            except Exception as e:
                logger.error(
                    "Health checker failed",
                    checker=type(checker).__name__,
                    error=str(e),
                )
                checks.append(
                    HealthCheckResult(
                        component="unknown",
                        status=HealthStatus.UNHEALTHY,
                        message=f"Health checker failed: {str(e)}",
                    )
                )

        system_health = SystemHealth.from_checks(checks)
        logger.info(
            "Health check completed",
            status=system_health.status,
            healthy_checks=sum(1 for c in checks if c.status == HealthStatus.HEALTHY),
            total_checks=len(checks),
        )

        return system_health
