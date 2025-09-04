"""FastMCP server implementation."""

import asyncio
from dataclasses import dataclass

from fastmcp import FastMCP

from ..cache.manager import CacheManager
from ..config.models import AIMCPConfig
from ..gitlab.client import GitLabClient
from ..utils.logging import get_logger

logger = get_logger("mcp.server")


@dataclass(slots=True)
class MCPServer:
    """MCP server with FastMCP."""

    config: AIMCPConfig
    cache_manager: CacheManager
    gitlab_client: GitLabClient
    _server: FastMCP | None = None
    _server_task: asyncio.Task[None] | None = None

    def __post_init__(self) -> None:
        """Initialize FastMCP server."""
        self._server = FastMCP(self.config.server.name)
        logger.info("MCP server initialized", name=self.config.server.name)

    async def start(self) -> None:
        """Start the MCP server."""
        if not self._server:
            raise RuntimeError("Server not initialized")

        # Start cache manager
        await self.cache_manager.start()

        # Warm cache on startup
        await self._warm_cache()

        # Configure server transport
        match self.config.server.transport:
            case "stdio":
                logger.info("Starting MCP server with STDIO transport")
                self._server_task = asyncio.create_task(
                    self._server.run()
                )
            case "http":
                logger.info("Starting MCP server with HTTP transport",
                          host=self.config.server.host,
                          port=self.config.server.port)
                self._server_task = asyncio.create_task(
                    self._server.run(
                        transport="http",
                        host=self.config.server.host,
                        port=self.config.server.port,
                    )
                )
            case "sse":
                logger.info("Starting MCP server with SSE transport",
                          host=self.config.server.host,
                          port=self.config.server.port)
                self._server_task = asyncio.create_task(
                    self._server.run(
                        transport="sse",
                        host=self.config.server.host,
                        port=self.config.server.port,
                    )
                )
            case _:
                raise ValueError(f"Unsupported transport: {self.config.server.transport}")

        logger.info("MCP server started")

    async def stop(self) -> None:
        """Stop the MCP server."""
        logger.info("Stopping MCP server")

        # Cancel server task
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

        # Stop cache manager
        await self.cache_manager.stop()

        # Close GitLab client
        await self.gitlab_client.close()

        logger.info("MCP server stopped")

    async def __aenter__(self) -> "MCPServer":
        """Async context manager entry."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Async context manager exit."""
        await self.stop()

    async def _warm_cache(self) -> None:
        """Warm cache with repository rules."""
        try:
            await self.cache_manager.warm_cache(
                self.config.gitlab.repositories,
                self.gitlab_client.fetch_rule_files,
            )
            logger.info("Cache warmed successfully")
        except Exception as e:
            logger.error("Failed to warm cache", error=str(e))
            # Continue startup even if cache warming fails

    @property
    def server(self) -> FastMCP:
        """Get the FastMCP server instance."""
        if not self._server:
            raise RuntimeError("Server not initialized")
        return self._server
