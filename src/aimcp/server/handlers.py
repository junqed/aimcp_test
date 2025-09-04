"""MCP handlers for tools, resources, and prompts."""

from datetime import datetime
from typing import Any

from ..cache.manager import CacheManager
from ..config.models import AIMCPConfig
from ..gitlab.client import GitLabClient, GitLabClientError
from ..utils.logging import get_logger
from .models import (
    CacheStatusResource,
    RefreshResult,
    RepositoryInfo,
    RepositoryStatus,
    RuleApplicationPrompt,
)

logger = get_logger("mcp.handlers")


class MCPHandlers:
    """MCP handlers for AIMCP server."""

    def __init__(
        self,
        config: AIMCPConfig,
        cache_manager: CacheManager,
        gitlab_client: GitLabClient,
    ) -> None:
        """Initialize MCP handlers.

        Args:
            config: Server configuration
            cache_manager: Cache manager instance
            gitlab_client: GitLab client instance
        """
        self.config = config
        self.cache_manager = cache_manager
        self.gitlab_client = gitlab_client

    # Tools (Actions LLMs can request)

    async def refresh_rules(self, repository: str | None = None) -> RefreshResult:
        """Force refresh of rules from GitLab repositories.

        Args:
            repository: Specific repository URL to refresh, or None for all

        Returns:
            Refresh operation result
        """
        logger.info("Refreshing rules", repository=repository)

        # Determine repositories to refresh
        if repository:
            repositories = [
                repo for repo in self.config.gitlab.repositories
                if repo.url == repository
            ]
            if not repositories:
                return RefreshResult(
                    success=False,
                    repository=repository,
                    errors=[f"Repository {repository} not found in configuration"]
                )
        else:
            repositories = self.config.gitlab.repositories

        total_updated = 0
        total_cached = 0
        errors = []

        for repo in repositories:
            try:
                # Invalidate existing cache
                await self.cache_manager.invalidate_repository(repo)

                # Fetch fresh rules
                rule_files = await self.gitlab_client.fetch_rule_files(repo)

                # Cache new rules
                await self.cache_manager.cache_repository_rules(repo, rule_files)

                total_updated += len(rule_files)
                total_cached += len(rule_files)

                logger.info("Refreshed repository rules",
                           repository=repo.url,
                           count=len(rule_files))

            except Exception as e:
                error_msg = f"Failed to refresh {repo.url}: {str(e)}"
                errors.append(error_msg)
                logger.error("Failed to refresh repository",
                           repository=repo.url, error=str(e))

        return RefreshResult(
            success=len(errors) == 0,
            repository=repository,
            updated_files=total_updated,
            cached_files=total_cached,
            errors=errors,
        )

    async def invalidate_cache(self, repository: str | None = None) -> dict[str, Any]:
        """Clear cache for specific repository or all.

        Args:
            repository: Specific repository URL to invalidate, or None for all

        Returns:
            Operation result with count of invalidated entries
        """
        logger.info("Invalidating cache", repository=repository)

        if repository:
            # Find matching repository
            repo_configs = [
                repo for repo in self.config.gitlab.repositories
                if repo.url == repository
            ]

            if not repo_configs:
                return {
                    "success": False,
                    "error": f"Repository {repository} not found",
                    "invalidated": 0,
                }

            total_invalidated = 0
            for repo_config in repo_configs:
                count = await self.cache_manager.invalidate_repository(repo_config)
                total_invalidated += count

            return {
                "success": True,
                "repository": repository,
                "invalidated": total_invalidated,
            }
        else:
            # Clear all cache
            await self.cache_manager.clear_all()
            return {
                "success": True,
                "repository": None,
                "invalidated": "all",
            }

    async def get_repository_status(self, repository: str | None = None) -> list[RepositoryStatus]:
        """Check repository connectivity and rule counts.

        Args:
            repository: Specific repository URL to check, or None for all

        Returns:
            List of repository status information
        """
        logger.info("Checking repository status", repository=repository)

        # Determine repositories to check
        if repository:
            repositories = [
                repo for repo in self.config.gitlab.repositories
                if repo.url == repository
            ]
        else:
            repositories = self.config.gitlab.repositories

        results = []

        for repo in repositories:
            try:
                # Test GitLab connectivity
                await self.gitlab_client.get_project(repo.url)

                # Get cached rule count
                cached_rules = await self.cache_manager.get_repository_rules(repo)
                rule_count = len(cached_rules)

                results.append(RepositoryStatus(
                    repository=repo.url,
                    branch=repo.branch,
                    accessible=True,
                    rule_count=rule_count,
                    last_check=datetime.now(),
                ))

                logger.debug("Repository status checked",
                           repository=repo.url,
                           accessible=True,
                           rule_count=rule_count)

            except Exception as e:
                results.append(RepositoryStatus(
                    repository=repo.url,
                    branch=repo.branch,
                    accessible=False,
                    rule_count=0,
                    last_check=datetime.now(),
                    error=str(e),
                ))

                logger.error("Repository status check failed",
                           repository=repo.url,
                           error=str(e))

        return results

    async def list_repositories(self) -> list[RepositoryInfo]:
        """Show configured repositories and their status.

        Returns:
            List of repository information
        """
        logger.debug("Listing repositories")

        results = []

        for repo in self.config.gitlab.repositories:
            try:
                # Get cached rules count
                cached_rules = await self.cache_manager.get_repository_rules(repo)
                rule_count = len(cached_rules)

                # Try to get project name
                try:
                    project = await self.gitlab_client.get_project(repo.url)
                    name = project.name
                    status = "accessible"
                except Exception:
                    name = repo.url.split('/')[-1]  # Use last part of URL
                    status = "unknown"

                results.append(RepositoryInfo(
                    url=repo.url,
                    branch=repo.branch,
                    name=name,
                    rule_count=rule_count,
                    status=status,
                ))

            except Exception as e:
                logger.error("Failed to get repository info",
                           repository=repo.url,
                           error=str(e))
                continue

        return results

    # Resources (Data LLMs can read)

    async def get_repository_rules(self, repository: str, branch: str) -> dict[str, str]:
        """Get all rules for a repository/branch.

        Args:
            repository: Repository URL
            branch: Branch name

        Returns:
            Dictionary mapping file paths to rule content
        """
        logger.debug("Getting repository rules",
                    repository=repository, branch=branch)

        # Find matching repository config
        repo_config = None
        for repo in self.config.gitlab.repositories:
            if repo.url == repository and repo.branch == branch:
                repo_config = repo
                break

        if not repo_config:
            logger.warning("Repository not found in configuration",
                         repository=repository, branch=branch)
            return {}

        # Try cache first
        cached_rules = await self.cache_manager.get_repository_rules(repo_config)
        if cached_rules:
            logger.debug("Returning cached rules",
                        repository=repository,
                        count=len(cached_rules))
            return cached_rules

        # Fallback to GitLab
        try:
            fresh_rules = await self.gitlab_client.fetch_rule_files(repo_config)

            # Cache for future requests
            await self.cache_manager.cache_repository_rules(repo_config, fresh_rules)

            logger.debug("Fetched and cached fresh rules",
                        repository=repository,
                        count=len(fresh_rules))

            return fresh_rules

        except GitLabClientError as e:
            logger.error("Failed to fetch rules from GitLab",
                        repository=repository,
                        error=str(e))
            return {}

    async def get_specific_rule(self, repository: str, branch: str, file_path: str) -> str | None:
        """Get specific rule file.

        Args:
            repository: Repository URL
            branch: Branch name
            file_path: File path within repository

        Returns:
            Rule file content or None if not found
        """
        logger.debug("Getting specific rule",
                    repository=repository,
                    branch=branch,
                    file_path=file_path)

        # Get all rules for repository
        rules = await self.get_repository_rules(repository, branch)
        return rules.get(file_path)

    async def get_cache_stats(self) -> CacheStatusResource:
        """Get cache performance and usage statistics.

        Returns:
            Cache status resource
        """
        stats = await self.cache_manager.get_stats()

        return CacheStatusResource(
            backend=self.config.cache.backend.value,
            item_count=stats.item_count,
            hit_rate=stats.hit_rate,
            memory_usage_mb=(
                stats.memory_usage_bytes / 1024 / 1024
                if stats.memory_usage_bytes else None
            ),
            storage_usage_mb=(
                stats.storage_usage_bytes / 1024 / 1024
                if stats.storage_usage_bytes else None
            ),
        )

    # Prompts (Reusable templates)

    def get_apply_rules_prompt(self) -> RuleApplicationPrompt:
        """Template for applying rules to current conversation.

        Returns:
            Rule application prompt template
        """
        return RuleApplicationPrompt(
            name="apply_rules",
            description="Apply AI rules from repositories to the current conversation",
            arguments={
                "repository": "Repository URL to apply rules from (optional)",
                "context": "Current conversation context or task description",
            }
        )

    def get_explain_rules_prompt(self) -> RuleApplicationPrompt:
        """Template for explaining available rules.

        Returns:
            Rule explanation prompt template
        """
        return RuleApplicationPrompt(
            name="explain_rules",
            description="Explain the available AI rules and their purposes",
            arguments={
                "repository": "Specific repository to explain (optional)",
                "detail_level": "Level of detail: summary, detailed, or full",
            }
        )

    def get_merge_rules_prompt(self) -> RuleApplicationPrompt:
        """Template for merging rules from multiple repositories.

        Returns:
            Rule merging prompt template
        """
        return RuleApplicationPrompt(
            name="merge_rules",
            description="Merge and prioritize rules from multiple repositories",
            arguments={
                "repositories": "Comma-separated list of repository URLs",
                "strategy": "Merge strategy: append, priority, or custom",
                "context": "Context for rule prioritization",
            }
        )
