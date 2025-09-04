"""Tool specification manager."""

import json
from typing import Any

from ..cache.manager import CacheManager
from ..config.models import AIMCPConfig, GitLabRepository
from ..gitlab.client import GitLabClient, GitLabClientError
from ..utils.logging import get_logger
from .models import ConflictResolutionStrategy, ResolvedTool, ToolsSpecification
from .resolver import ToolResolver

logger = get_logger("tools.manager")


class ToolSpecificationError(Exception):
    """Error in tool specification processing."""


class ToolManager:
    """Manages tool specifications from repositories."""

    def __init__(
        self,
        config: AIMCPConfig,
        cache_manager: CacheManager,
        gitlab_client: GitLabClient,
    ) -> None:
        """Initialize tool manager.

        Args:
            config: AIMCP configuration
            cache_manager: Cache manager instance
            gitlab_client: GitLab client instance
        """
        self.config = config
        self.cache_manager = cache_manager
        self.gitlab_client = gitlab_client
        self.resolver = ToolResolver(
            ConflictResolutionStrategy.PREFIX
        )  # Default strategy

    async def load_all_tools(self) -> list[ResolvedTool]:
        """Load and resolve tools from all configured repositories.

        Returns:
            List of resolved tools ready for MCP registration
        """
        logger.info(
            "Loading tools from all repositories",
            count=len(self.config.gitlab.repositories),
        )

        # Load tool specifications from all repositories
        repo_tools: dict[GitLabRepository, ToolsSpecification] = {}

        for repo in self.config.gitlab.repositories:
            try:
                spec = await self._load_repository_tools(repo)
                if spec:
                    repo_tools[repo] = spec
                    logger.debug(
                        "Loaded tools from repository",
                        repository=repo.url,
                        tool_count=len(spec.tools),
                    )
                else:
                    logger.warning(
                        "Repository has no tools.json, skipping", repository=repo.url
                    )

            except Exception as e:
                logger.error(
                    "Failed to load tools from repository",
                    repository=repo.url,
                    error=str(e),
                )
                # Continue with other repositories
                continue

        if not repo_tools:
            logger.warning("No tool specifications loaded from any repository")
            return []

        # Resolve conflicts
        try:
            resolved_tools, conflicts = self.resolver.resolve_tools(repo_tools)

            if conflicts:
                logger.info(
                    "Tool conflicts resolved",
                    conflict_count=len(conflicts),
                    strategy=self.resolver.strategy.value,
                )

            logger.info(
                "Tool loading completed",
                total_tools=len(resolved_tools),
                repositories=len(repo_tools),
            )

            return resolved_tools

        except Exception as e:
            logger.error("Failed to resolve tool conflicts", error=str(e))
            raise ToolSpecificationError(f"Tool conflict resolution failed: {e}") from e

    async def _load_repository_tools(
        self, repository: GitLabRepository
    ) -> ToolsSpecification | None:
        """Load tool specification from a single repository.

        Args:
            repository: Repository configuration

        Returns:
            Tool specification or None if tools.json not found
        """
        cache_key = f"tools:{repository.url}:{repository.branch}"

        # Try cache first
        try:
            cached_spec = await self.cache_manager.get(cache_key)
            if cached_spec:
                logger.debug(
                    "Using cached tool specification", repository=repository.url
                )
                return ToolsSpecification(**cached_spec)
        except Exception as e:
            logger.debug(
                "Cache miss for tool specification",
                repository=repository.url,
                error=str(e),
            )

        # Fetch from GitLab
        try:
            content = await self.gitlab_client.get_file_content_decoded(
                repository.url,
                "tools.json",
                repository.branch,
            )

            # Parse JSON
            try:
                spec_data = json.loads(content)
                spec = ToolsSpecification(**spec_data)

                # Cache for future use
                await self.cache_manager.set(
                    cache_key,
                    spec.model_dump(),
                    ttl=self.config.cache.ttl_seconds,
                )

                logger.debug(
                    "Loaded and cached tool specification",
                    repository=repository.url,
                    tool_count=len(spec.tools),
                )

                return spec

            except (json.JSONDecodeError, ValueError) as e:
                logger.error(
                    "Invalid tools.json format", repository=repository.url, error=str(e)
                )
                raise ToolSpecificationError(
                    f"Invalid tools.json in {repository.url}: {e}"
                ) from e

        except GitLabClientError as e:
            if e.status_code == 404:
                # tools.json not found - this is expected for some repositories
                logger.debug(
                    "tools.json not found in repository", repository=repository.url
                )
                return None
            else:
                # Other GitLab errors
                logger.error(
                    "Failed to fetch tools.json",
                    repository=repository.url,
                    error=str(e),
                )
                raise ToolSpecificationError(
                    f"Failed to fetch tools.json from {repository.url}: {e}"
                ) from e

    async def get_resource_content(self, resource_uri: str) -> str:
        """Fetch content for a resource URI.

        Args:
            resource_uri: Resource URI in format aimcp://repo/branch/file

        Returns:
            File content

        Raises:
            ToolSpecificationError: If URI is invalid or file not accessible
        """
        # Parse URI
        if not resource_uri.startswith("aimcp://"):
            raise ToolSpecificationError(f"Invalid resource URI scheme: {resource_uri}")

        try:
            # Extract components: aimcp://repo/branch/file/path
            uri_parts = resource_uri[8:]  # Remove 'aimcp://'
            parts = uri_parts.split("/", 2)

            if len(parts) < 3:
                raise ValueError("Insufficient URI components")

            repository, branch, file_path = parts

            # Validate repository is configured
            repo_config = None
            for repo in self.config.gitlab.repositories:
                if repo.url == repository and repo.branch == branch:
                    repo_config = repo
                    break

            if not repo_config:
                raise ToolSpecificationError(
                    f"Repository {repository}:{branch} not in configuration"
                )

            # Check if file is in allowed resources
            await self._validate_resource_access(repo_config, file_path)

            # Fetch content
            cache_key = f"resource:{repository}:{branch}:{file_path}"

            # Try cache first
            try:
                cached_content = await self.cache_manager.get(cache_key)
                if cached_content:
                    logger.debug("Using cached resource content", uri=resource_uri)
                    return cached_content
            except Exception:
                pass  # Cache miss, continue to fetch

            # Fetch from GitLab
            content = await self.gitlab_client.get_file_content_decoded(
                repository, file_path, branch
            )

            # Cache content
            await self.cache_manager.set(
                cache_key,
                content,
                ttl=self.config.cache.ttl_seconds,
            )

            logger.debug(
                "Fetched and cached resource content",
                uri=resource_uri,
                size=len(content),
            )

            return content

        except (ValueError, IndexError) as e:
            raise ToolSpecificationError(
                f"Invalid resource URI format: {resource_uri}"
            ) from e
        except GitLabClientError as e:
            raise ToolSpecificationError(
                f"Failed to fetch resource {resource_uri}: {e}"
            ) from e

    async def _validate_resource_access(
        self, repository: GitLabRepository, file_path: str
    ) -> None:
        """Validate that a file is allowed to be accessed.

        Args:
            repository: Repository configuration
            file_path: File path to validate

        Raises:
            ToolSpecificationError: If file access is not allowed
        """
        # Load tool specification to check allowed resources
        spec = await self._load_repository_tools(repository)
        if not spec:
            raise ToolSpecificationError(
                f"No tool specification found for repository {repository.url}"
            )

        # Check if file is in any tool's resources
        for tool in spec.tools:
            if file_path in tool.resources:
                logger.debug(
                    "Resource access validated",
                    repository=repository.url,
                    file_path=file_path,
                    tool=tool.name,
                )
                return

        # File not found in any tool's resources
        raise ToolSpecificationError(
            f"File {file_path} not accessible - not listed in any tool's resources"
        )

    def set_conflict_strategy(self, strategy: ConflictResolutionStrategy) -> None:
        """Update conflict resolution strategy.

        Args:
            strategy: New strategy to use
        """
        self.resolver = ToolResolver(strategy)
        logger.info("Conflict resolution strategy updated", strategy=strategy.value)
