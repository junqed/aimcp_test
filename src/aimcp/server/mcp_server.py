"""FastMCP server implementation."""

import asyncio
from dataclasses import dataclass
from functools import partial
from typing import Any, Awaitable, Callable

from fastmcp import FastMCP

from ..cache.manager import CacheManager
from ..config.models import AIMCPConfig
from ..gitlab.client import GitLabClient
from ..tools.manager import ToolManager
from ..tools.models import ConflictResolutionStrategy
from ..utils.logging import get_logger

logger = get_logger("mcp.server")


@dataclass(slots=True)
class MCPServer:
    """MCP server with FastMCP."""

    config: AIMCPConfig
    cache_manager: CacheManager
    gitlab_client: GitLabClient
    tool_manager: ToolManager
    _server: FastMCP | None = None

    def __post_init__(self) -> None:
        """Initialize FastMCP server."""
        self._server = FastMCP(self.config.server.name)

        # Set tool manager conflict resolution strategy
        try:
            strategy = ConflictResolutionStrategy(
                self.config.tools.conflict_resolution_strategy
            )
            self.tool_manager.set_conflict_strategy(strategy)
        except ValueError:
            logger.warning(
                "Invalid conflict resolution strategy, using default",
                strategy=self.config.tools.conflict_resolution_strategy,
                default="prefix",
            )

        logger.info("MCP server initialized", name=self.config.server.name)

    async def get_server_runner(self) -> Callable[[], Awaitable[None]]:
        """Get server runner coroutine for the configured transport.
        
        Returns:
            Async callable that runs the server with configured transport
        """
        if not self._server:
            raise RuntimeError("Server not initialized")

        # Start cache manager
        await self.cache_manager.start()

        # Load and register tools
        await self._load_and_register_tools()

        # Return appropriate runner based on transport
        match self.config.server.transport:
            case "stdio":
                logger.info("Server ready for STDIO transport")
                return self._run_stdio
            case "http":
                logger.info(
                    "Server ready for HTTP transport",
                    host=self.config.server.host,
                    port=self.config.server.port,
                )
                return partial(self._run_http, self.config.server.host, self.config.server.port)
            case "sse":
                logger.info(
                    "Server ready for SSE transport",
                    host=self.config.server.host,
                    port=self.config.server.port,
                )
                return partial(self._run_sse, self.config.server.host, self.config.server.port)
            case _:
                raise ValueError(
                    f"Unsupported transport: {self.config.server.transport}"
                )

    async def cleanup(self) -> None:
        """Clean up server resources."""
        logger.info("Cleaning up MCP server resources")

        # Stop cache manager
        await self.cache_manager.stop()

        # Close GitLab client
        await self.gitlab_client.close()

        logger.info("MCP server cleanup completed")

    async def __aenter__(self) -> Callable[[], Awaitable[None]]:
        """Async context manager entry - returns server runner."""
        return await self.get_server_runner()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Async context manager exit."""
        await self.cleanup()

    async def _load_and_register_tools(self) -> None:
        """Load tool specifications and register MCP tools."""
        try:
            # Load resolved tools from all repositories
            resolved_tools = await self.tool_manager.load_all_tools()

            if not resolved_tools:
                logger.warning("No tools loaded from any repository")
                return

            # Register each tool with FastMCP
            for tool in resolved_tools:
                await self._register_mcp_tool(tool)

            logger.info(
                "Tools loaded and registered successfully", count=len(resolved_tools)
            )

        except Exception as e:
            logger.error("Failed to load and register tools", error=str(e))
            # Continue startup even if tool loading fails

    async def _register_mcp_tool(self, tool: Any) -> None:
        """Register a single resolved tool with FastMCP.

        Args:
            tool: ResolvedTool instance to register
        """
        from ..tools.models import ResolvedTool

        if not isinstance(tool, ResolvedTool):
            logger.error("Invalid tool type for registration", tool_type=type(tool))
            return

        # Create tool handler that fetches resources on demand
        async def tool_handler(**kwargs) -> dict[str, str]:  # type: ignore
            """Handle tool execution by providing resource content."""
            result = {"tool": tool.resolved_name, "repository": tool.repository}

            # Add related resource contents
            for resource in tool.related_resources:
                try:
                    # Generate URI from resource
                    uri = f"aimcp://{tool.repository}/{tool.branch}/{resource.uri}"
                    content = await self.tool_manager.get_resource_content(uri)
                    result[resource.name] = content
                except Exception as e:
                    logger.error(
                        "Failed to fetch resource content", 
                        resource=resource.name, 
                        error=str(e)
                    )
                    result[resource.name] = f"Error: {e}"

            return result

        # Register with FastMCP using the tool decorator
        if not self._server:
            raise RuntimeError("Server not initialized")
        
        self._server.tool(
            tool_handler,
            name=tool.resolved_name,
            description=tool.specification.description,
        )

        logger.debug(
            "Registered MCP tool",
            name=tool.resolved_name,
            repository=tool.repository,
            resources=len(tool.related_resources),
        )

    async def _run_stdio(self) -> None:
        """Run server with STDIO transport."""
        if not self._server:
            raise RuntimeError("Server not initialized")
        await self._server.run_stdio_async()

    async def _run_http(self, host: str, port: int) -> None:
        """Run server with HTTP transport."""
        if not self._server:
            raise RuntimeError("Server not initialized")
        await self._server.run_http_async(host=host, port=port)

    async def _run_sse(self, host: str, port: int) -> None:
        """Run server with SSE transport."""
        if not self._server:
            raise RuntimeError("Server not initialized")
        await self._server.run_sse_async(host=host, port=port)

    @property
    def server(self) -> FastMCP:
        """Get the FastMCP server instance."""
        if not self._server:
            raise RuntimeError("Server not initialized")
        return self._server
