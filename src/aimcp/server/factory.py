"""Server factory for creating MCP server instances."""


from ..cache.factory import create_cache_manager
from ..config.models import AIMCPConfig
from ..gitlab.client import GitLabClient
from ..utils.health import CacheHealthChecker, GitLabHealthChecker, SystemHealthChecker
from ..utils.logging import get_logger
from .handlers import MCPHandlers
from .mcp_server import MCPServer

logger = get_logger("mcp.factory")


async def create_mcp_server(config: AIMCPConfig) -> MCPServer:
    """Create MCP server with all dependencies.

    Args:
        config: Application configuration

    Returns:
        Configured MCP server instance
    """
    logger.info("Creating MCP server", name=config.server.name)

    # Create cache manager
    cache_manager = create_cache_manager(config.cache)

    # Create GitLab client
    gitlab_client = GitLabClient(config.gitlab)

    # Create MCP server
    mcp_server = MCPServer(
        config=config,
        cache_manager=cache_manager,
        gitlab_client=gitlab_client,
    )

    # Register handlers
    await _register_handlers(mcp_server, config, cache_manager, gitlab_client)

    logger.info("MCP server created successfully")
    return mcp_server


async def _register_handlers(
    mcp_server: MCPServer,
    config: AIMCPConfig,
    cache_manager,
    gitlab_client: GitLabClient,
) -> None:
    """Register MCP handlers with the server.

    Args:
        mcp_server: MCP server instance
        config: Application configuration
        cache_manager: Cache manager instance
        gitlab_client: GitLab client instance
    """
    logger.debug("Registering MCP handlers")

    server = mcp_server.server
    handlers = MCPHandlers(config, cache_manager, gitlab_client)

    # Register tools
    @server.tool()
    async def refresh_rules(repository: str | None = None) -> dict:
        """Force refresh of rules from GitLab repositories."""
        result = await handlers.refresh_rules(repository)
        return result.model_dump()

    @server.tool()
    async def invalidate_cache(repository: str | None = None) -> dict:
        """Clear cache for specific repository or all."""
        return await handlers.invalidate_cache(repository)

    @server.tool()
    async def get_repository_status(repository: str | None = None) -> list[dict]:
        """Check repository connectivity and rule counts."""
        statuses = await handlers.get_repository_status(repository)
        return [status.model_dump() for status in statuses]

    @server.tool()
    async def list_repositories() -> list[dict]:
        """Show configured repositories and their status."""
        repositories = await handlers.list_repositories()
        return [
            {
                "url": repo.url,
                "branch": repo.branch,
                "name": repo.name,
                "rule_count": repo.rule_count,
                "status": repo.status,
                "last_updated": repo.last_updated.isoformat() if repo.last_updated else None,
            }
            for repo in repositories
        ]

    # Register resources
    @server.resource("all-rules/{repository}/{branch}")
    async def get_all_rules(repository: str, branch: str) -> str:
        """Get all rules for a repository/branch."""
        rules = await handlers.get_repository_rules(repository, branch)

        if not rules:
            return f"No rules found for {repository}:{branch}"

        # Format rules for display
        rule_content = []
        for file_path, content in rules.items():
            rule_content.append(f"=== {file_path} ===")
            rule_content.append(content)
            rule_content.append("")

        return "\n".join(rule_content)

    # @server.resource("single-rule/{repository}/{branch}/{file_path:path}")
    # async def get_single_rule(repository: str, branch: str, file_path: str) -> str:
    #     """Get specific rule file."""
    #     content = await handlers.get_specific_rule(repository, branch, file_path)
    #
    #     if content is None:
    #         return f"Rule file not found: {file_path}"
    #
    #     return content

    # @server.resource("api/repositories")
    # async def list_repositories_resource() -> str:
    #     """List all configured repositories."""
    #     repositories = await handlers.list_repositories()
    #
    #     if not repositories:
    #         return "No repositories configured"
    #
    #     lines = ["Configured Repositories:", ""]
    #     for repo in repositories:
    #         lines.append(f"- {repo.name} ({repo.url}:{repo.branch})")
    #         lines.append(f"  Rules: {repo.rule_count}, Status: {repo.status}")
    #         if repo.last_updated:
    #             lines.append(f"  Last Updated: {repo.last_updated}")
    #         lines.append("")
    #
    #     return "\n".join(lines)

    # @server.resource("cache_stats")
    # async def cache_stats_resource() -> str:
    #     """Cache performance and usage statistics."""
    #     stats = await handlers.get_cache_stats()
    #
    #     lines = [
    #         f"Cache Statistics ({stats.backend} backend):",
    #         "",
    #         f"Items: {stats.item_count}",
    #         f"Hit Rate: {stats.hit_rate:.2%}",
    #     ]
    #
    #     if stats.memory_usage_mb is not None:
    #         lines.append(f"Memory Usage: {stats.memory_usage_mb:.2f} MB")
    #
    #     if stats.storage_usage_mb is not None:
    #         lines.append(f"Storage Usage: {stats.storage_usage_mb:.2f} MB")
    #
    #     return "\n".join(lines)

    # @server.resource("health")
    # async def health_check_resource() -> str:
    #     """System health check with component status."""
    #     # Create health checkers
    #     gitlab_checker = GitLabHealthChecker(gitlab_client, config.gitlab.repositories)
    #     cache_checker = CacheHealthChecker(cache_manager)
    #
    #     system_checker = SystemHealthChecker([gitlab_checker, cache_checker])
    #
    #     # Run health checks
    #     system_health = await system_checker.check_all()
    #
    #     # Format health check results
    #     lines = [
    #         f"System Health: {system_health.status.value.upper()}",
    #         f"Checked at: {system_health.checked_at.strftime('%Y-%m-%d %H:%M:%S UTC')}",
    #         "",
    #     ]
    #
    #     for check in system_health.checks:
    #         status_emoji = {
    #             "healthy": "✅",
    #             "degraded": "⚠️",
    #             "unhealthy": "❌",
    #         }.get(check.status, "❓")
    #
    #         lines.append(f"{status_emoji} {check.component.upper()}: {check.status}")
    #         lines.append(f"   Message: {check.message}")
    #
    #         if check.details:
    #             lines.append("   Details:")
    #             for key, value in check.details.items():
    #                 lines.append(f"   - {key}: {value}")
    #
    #         lines.append("")
    #
    #     return "\n".join(lines)

    # Register prompts
    @server.prompt()
    async def apply_rules(repository: str = "", context: str = "") -> str:
        """Apply AI rules from repositories to the current conversation."""
        handlers.get_apply_rules_prompt()

        # Get rules to apply
        if repository:
            # Apply rules from specific repository
            repo_parts = repository.split(":")
            if len(repo_parts) == 2:
                repo_url, branch = repo_parts
                rules = await handlers.get_repository_rules(repo_url, branch)
            else:
                # Assume main branch
                rules = await handlers.get_repository_rules(repository, "main")
        else:
            # Apply rules from all repositories
            all_rules = {}
            for repo in config.gitlab.repositories:
                repo_rules = await handlers.get_repository_rules(repo.url, repo.branch)
                all_rules.update(repo_rules)
            rules = all_rules

        if not rules:
            return "No rules found to apply."

        prompt_parts = [
            "Apply the following AI rules to the current conversation:",
            "",
        ]

        if context:
            prompt_parts.extend([
                f"Context: {context}",
                "",
            ])

        for file_path, content in rules.items():
            prompt_parts.extend([
                f"--- Rule from {file_path} ---",
                content,
                "",
            ])

        return "\n".join(prompt_parts)

    @server.prompt()
    async def explain_rules(repository: str = "", detail_level: str = "summary") -> str:
        """Explain the available AI rules and their purposes."""
        repositories = await handlers.list_repositories()

        if not repositories:
            return "No AI rules repositories are configured."

        if repository:
            # Filter to specific repository
            repositories = [r for r in repositories if r.url == repository]
            if not repositories:
                return f"Repository '{repository}' not found."

        lines = ["Available AI Rules:", ""]

        for repo in repositories:
            lines.append(f"📁 {repo.name} ({repo.url}:{repo.branch})")
            lines.append(f"   Rules: {repo.rule_count}, Status: {repo.status}")

            match detail_level:
                case "detailed" | "full":
                    # Get actual rules content
                    rules = await handlers.get_repository_rules(repo.url, repo.branch)
                    if rules:
                        lines.append("   Files:")
                        for file_path in rules.keys():
                            lines.append(f"   - {file_path}")

                            if detail_level == "full":
                                content = rules[file_path]
                                # Show first few lines
                                preview_lines = content.split('\n')[:3]
                                for line in preview_lines:
                                    lines.append(f"     {line}")
                                if len(content.split('\n')) > 3:
                                    lines.append("     ...")
                    lines.append("")
                case _:
                    lines.append("")

        return "\n".join(lines)

    @server.prompt()
    async def merge_rules(repositories: str = "", strategy: str = "append", context: str = "") -> str:
        """Merge and prioritize rules from multiple repositories."""
        if not repositories:
            repo_list = config.gitlab.repositories
        else:
            # Parse repository list
            repo_urls = [r.strip() for r in repositories.split(",")]
            repo_list = [
                repo for repo in config.gitlab.repositories
                if repo.url in repo_urls
            ]

        if not repo_list:
            return "No valid repositories specified for merging."

        all_rules = {}

        match strategy:
            case "append":
                # Simple concatenation
                for repo in repo_list:
                    rules = await handlers.get_repository_rules(repo.url, repo.branch)
                    for file_path, content in rules.items():
                        key = f"{repo.url}:{repo.branch}:{file_path}"
                        all_rules[key] = content

            case "priority":
                # First repository takes precedence
                for repo in reversed(repo_list):  # Reverse so first has priority
                    rules = await handlers.get_repository_rules(repo.url, repo.branch)
                    all_rules.update(rules)

            case _:
                # Custom strategy - just append for now
                for repo in repo_list:
                    rules = await handlers.get_repository_rules(repo.url, repo.branch)
                    for file_path, content in rules.items():
                        key = f"{repo.url}:{file_path}"
                        all_rules[key] = content

        if not all_rules:
            return "No rules found in specified repositories."

        lines = [
            f"Merged Rules (strategy: {strategy}):",
            "",
        ]

        if context:
            lines.extend([
                f"Context: {context}",
                "",
            ])

        for rule_key, content in all_rules.items():
            lines.extend([
                f"--- {rule_key} ---",
                content,
                "",
            ])

        return "\n".join(lines)

    logger.debug("MCP handlers registered successfully")
