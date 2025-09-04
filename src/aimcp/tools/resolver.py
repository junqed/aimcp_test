"""Tool conflict resolution logic."""

from collections import defaultdict

from ..config.models import GitLabRepository
from ..utils.logging import get_logger
from .models import (
    ConflictResolutionStrategy,
    MCPTool,
    ResolvedTool,
    ToolConflict,
    ToolsSpecification,
)

logger = get_logger("tools.resolver")


class ToolConflictError(Exception):
    """Raised when tool conflicts cannot be resolved."""

    def __init__(self, conflicts: list[ToolConflict]) -> None:
        self.conflicts = conflicts
        conflict_details = []
        for conflict in conflicts:
            repos = ", ".join(conflict.repositories)
            conflict_details.append(f"'{conflict.name}' in repositories: {repos}")

        message = f"Tool name conflicts detected:\n" + "\n".join(conflict_details)
        super().__init__(message)


class ToolResolver:
    """Resolves tool name conflicts across repositories."""

    def __init__(self, strategy: ConflictResolutionStrategy) -> None:
        """Initialize resolver with conflict resolution strategy.

        Args:
            strategy: Strategy to use for resolving conflicts
        """
        self.strategy = strategy

    def resolve_tools(
        self,
        repo_specs: dict[GitLabRepository, ToolsSpecification],
    ) -> tuple[list[ResolvedTool], list[ToolConflict]]:
        """Resolve tool conflicts across repositories.

        Args:
            repo_specs: Mapping of repositories to their tool specifications

        Returns:
            Tuple of (resolved tools, conflicts detected)

        Raises:
            ToolConflictError: If strategy is ERROR and conflicts exist
        """
        # Group tools by name to detect conflicts
        tools_by_name: dict[str, list[tuple[GitLabRepository, MCPTool]]] = defaultdict(
            list
        )

        for repo, spec in repo_specs.items():
            for tool in spec.tools:
                tools_by_name[tool.name].append((repo, tool))

        # Identify conflicts and resolve
        resolved_tools: list[ResolvedTool] = []
        conflicts: list[ToolConflict] = []

        for tool_name, repo_tools_list in tools_by_name.items():
            if len(repo_tools_list) == 1:
                # No conflict - single tool
                repo, tool = repo_tools_list[0]
                spec = repo_specs[repo]  # Get the specification for this repo
                resolved_tool = self._create_resolved_tool(repo, tool, tool.name, spec)
                resolved_tools.append(resolved_tool)
            else:
                # Conflict detected
                repositories = [repo.url for repo, _ in repo_tools_list]
                conflict = ToolConflict(
                    name=tool_name,
                    repositories=repositories,
                    strategy_applied=self.strategy,
                    resolution="",
                )
                conflicts.append(conflict)

                # Apply resolution strategy
                match self.strategy:
                    case ConflictResolutionStrategy.PREFIX:
                        resolved_tools.extend(
                            self._resolve_with_prefix(repo_tools_list, conflict, repo_specs)
                        )
                    case ConflictResolutionStrategy.PRIORITY:
                        resolved_tools.extend(
                            self._resolve_with_priority(repo_tools_list, conflict, repo_specs)
                        )
                    case ConflictResolutionStrategy.MERGE:
                        resolved_tools.extend(
                            self._resolve_with_merge(repo_tools_list, conflict, repo_specs)
                        )
                    case ConflictResolutionStrategy.ERROR:
                        # Will be handled after loop
                        continue

        # Handle ERROR strategy
        if self.strategy == ConflictResolutionStrategy.ERROR and conflicts:
            raise ToolConflictError(conflicts)

        logger.info(
            "Tool resolution completed",
            strategy=self.strategy.value,
            total_tools=len(resolved_tools),
            conflicts=len(conflicts),
        )

        return resolved_tools, conflicts

    def _create_resolved_tool(
        self, repo: GitLabRepository, tool: MCPTool, resolved_name: str, spec: ToolsSpecification
    ) -> ResolvedTool:
        """Create a resolved tool with associated resources."""
        # Find related resources based on resourceRefs
        related_resources: list[MCPResource] = []
        if tool.resourceRefs:
            # Create a lookup map for resources by name
            resource_map = {resource.name: resource for resource in spec.resources}
            
            # Add referenced resources that exist
            for resource_ref in tool.resourceRefs:
                if resource_ref in resource_map:
                    related_resources.append(resource_map[resource_ref])
                else:
                    logger.warning(
                        "Resource reference not found",
                        tool_name=tool.name,
                        resource_ref=resource_ref,
                        available_resources=[r.name for r in spec.resources]
                    )
        
        return ResolvedTool(
            original_name=tool.name,
            resolved_name=resolved_name,
            repository=repo.url,
            branch=repo.branch,
            specification=tool,
            related_resources=related_resources,
        )

    def _resolve_with_prefix(
        self,
        repo_tools_list: list[tuple[GitLabRepository, MCPTool]],
        conflict: ToolConflict,
        repo_specs: dict[GitLabRepository, ToolsSpecification],
    ) -> list[ResolvedTool]:
        """Resolve conflict by prefixing with repository name."""
        resolved_tools = []

        for repo, tool in repo_tools_list:
            # Create prefix from repository URL (last part)
            repo_prefix = repo.url.split("/")[-1]
            resolved_name = f"{repo_prefix}_{tool.name}"
            spec = repo_specs[repo]

            resolved_tool = self._create_resolved_tool(repo, tool, resolved_name, spec)
            resolved_tools.append(resolved_tool)

        conflict.resolution = f"Added repository prefixes to tool names"
        logger.debug(
            "Resolved conflict with prefix strategy",
            tool_name=conflict.name,
            resolved_names=[t.resolved_name for t in resolved_tools],
        )

        return resolved_tools

    def _resolve_with_priority(
        self,
        repo_tools_list: list[tuple[GitLabRepository, MCPTool]],
        conflict: ToolConflict,
        repo_specs: dict[GitLabRepository, ToolsSpecification],
    ) -> list[ResolvedTool]:
        """Resolve conflict by using first repository (priority order)."""
        # Take the first repository (highest priority)
        repo, tool = repo_tools_list[0]
        spec = repo_specs[repo]
        resolved_tool = self._create_resolved_tool(repo, tool, tool.name, spec)

        conflict.resolution = f"Used tool from {repo.url} (first in configuration)"
        logger.debug(
            "Resolved conflict with priority strategy",
            tool_name=conflict.name,
            chosen_repo=repo.url,
            ignored_repos=[r.url for r, _ in repo_tools_list[1:]],
        )

        return [resolved_tool]

    def _resolve_with_merge(
        self,
        repo_tools_list: list[tuple[GitLabRepository, MCPTool]],
        conflict: ToolConflict,
        repo_specs: dict[GitLabRepository, ToolsSpecification],
    ) -> list[ResolvedTool]:
        """Resolve conflict by merging tool descriptions."""
        # Use first tool as base
        base_repo, base_tool = repo_tools_list[0]

        # Merge descriptions
        descriptions = [
            tool.description for _, tool in repo_tools_list if tool.description
        ]
        merged_description = (
            " | ".join(descriptions) if descriptions else base_tool.description
        )

        # Collect all resource references from merged tools
        all_resource_refs: list[str] = []
        for repo, tool in repo_tools_list:
            if tool.resourceRefs:
                all_resource_refs.extend(tool.resourceRefs)

        # Create merged tool specification
        merged_spec = MCPTool(
            name=base_tool.name,
            description=merged_description,
            inputSchema=base_tool.inputSchema,  # Use first tool's schema
            resourceRefs=all_resource_refs if all_resource_refs else None,
        )

        # Collect resources from all repositories for merge
        all_resources: list[MCPResource] = []
        for repo, tool in repo_tools_list:
            spec = repo_specs[repo]
            if tool.resourceRefs:
                resource_map = {resource.name: resource for resource in spec.resources}
                for resource_ref in tool.resourceRefs:
                    if resource_ref in resource_map:
                        all_resources.append(resource_map[resource_ref])

        # Create resolved tool
        resolved_tool = ResolvedTool(
            original_name=base_tool.name,
            resolved_name=base_tool.name,
            repository=f"merged({len(repo_tools_list)} repos)",
            branch="multiple",
            specification=merged_spec,
            related_resources=all_resources,
        )

        conflict.resolution = f"Merged descriptions from all repositories"
        logger.debug(
            "Resolved conflict with merge strategy",
            tool_name=conflict.name,
            merged_repos=[repo.url for repo, _ in repo_tools_list],
        )

        return [resolved_tool]
