"""Server factory for creating MCP server instances."""

from typing import Awaitable, Callable

from ..cache.factory import create_cache_manager
from ..config.models import AIMCPConfig
from ..gitlab.client import GitLabClient
from ..tools.manager import ToolManager
from ..utils.logging import get_logger
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

    # Create tool manager
    tool_manager = ToolManager(config, cache_manager, gitlab_client)

    # Create MCP server
    mcp_server = MCPServer(
        config=config,
        cache_manager=cache_manager,
        gitlab_client=gitlab_client,
        tool_manager=tool_manager,
    )

    logger.info("MCP server created successfully")
    return mcp_server


async def create_server_runner(config: AIMCPConfig) -> Callable[[], Awaitable[None]]:
    """Create MCP server and return runner coroutine.
    
    Args:
        config: Application configuration
        
    Returns:
        Server runner coroutine that can be passed to asyncio.run()
    """
    server = await create_mcp_server(config)
    return await server.get_server_runner()
