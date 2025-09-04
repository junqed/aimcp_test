"""CLI entry point for AIMCP."""

import asyncio
from pathlib import Path

import typer
from pydantic import ValidationError

from .config.settings import create_config, validate_config
from .utils.logging import setup_logging

app = typer.Typer(
    name="aimcp",
    help="MCP server for distributing AI rules from GitLab repositories",
    add_completion=False,
)


@app.command()
def serve(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        help="Path to configuration file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
    host: str | None = typer.Option(
        None,
        "--host",
        "-h",
        help="Server host (overrides config)",
    ),
    port: int | None = typer.Option(
        None,
        "--port",
        "-p",
        help="Server port (overrides config)",
    ),
    transport: str | None = typer.Option(
        None,
        "--transport",
        "-t",
        help="Transport type: stdio, http, sse (overrides config)",
    ),
) -> None:
    """Start the AIMCP MCP server."""
    try:
        # Build override settings
        overrides: dict[str, str | int] = {}
        if host:
            overrides["host"] = host
        if port:
            overrides["port"] = port
        if transport:
            overrides["transport"] = transport

        # Load configuration
        config_obj = create_config(config, overrides)
        validate_config(config_obj)

        # Setup logging
        setup_logging(config_obj.logging)

        # Start server
        typer.echo(f"Starting AIMCP server: {config_obj.server.name}")
        typer.echo(f"Transport: {config_obj.server.transport.value}")
        if config_obj.server.transport.value != "stdio":
            typer.echo(f"Address: {config_obj.server.host}:{config_obj.server.port}")
        typer.echo(f"Monitoring {len(config_obj.gitlab.repositories)} repositories")
        typer.echo(f"Cache backend: {config_obj.cache.backend.value}")

        from .server.factory import create_mcp_server

        async def run_server() -> None:
            mcp_server = await create_mcp_server(config_obj)

            try:
                async with mcp_server:
                    typer.echo("✓ AIMCP server started successfully")
                    typer.echo("Press Ctrl+C to stop the server")

                    # Keep server running
                    try:
                        while True:
                            await asyncio.sleep(1)
                    except KeyboardInterrupt:
                        typer.echo("\nShutting down server...")

            except Exception as e:
                typer.echo(f"✗ Server failed to start: {e}", err=True)
                raise typer.Exit(1)

        asyncio.run(run_server())

    except ValidationError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error starting server: {e}", err=True)
        raise typer.Exit(1)


@app.command("validate-config")
def validate_config_command(
    config: Path = typer.Argument(
        ...,
        help="Path to configuration file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Validate configuration file."""
    try:
        config_obj = create_config(config)
        validate_config(config_obj)

        typer.echo("✓ Configuration is valid")
        typer.echo(f"  Server: {config_obj.server.host}:{config_obj.server.port} ({config_obj.server.transport})")
        typer.echo(f"  GitLab: {config_obj.gitlab.instance_url}")
        typer.echo(f"  Repositories: {len(config_obj.gitlab.repositories)}")
        typer.echo(f"  Cache: {config_obj.cache.backend} (TTL: {config_obj.cache.ttl_seconds}s)")

    except ValidationError as e:
        typer.echo("✗ Configuration validation failed:", err=True)
        for error in e.errors():
            location = " -> ".join(str(loc) for loc in error["loc"])
            typer.echo(f"  {location}: {error['msg']}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error loading configuration: {e}", err=True)
        raise typer.Exit(1)


@app.command("test-gitlab")
def test_gitlab_command(
    config: Path = typer.Argument(
        ...,
        help="Path to configuration file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Test GitLab connectivity and repository access."""
    try:
        config_obj = create_config(config)
        validate_config(config_obj)

        typer.echo("Testing GitLab connectivity...")
        typer.echo(f"Instance: {config_obj.gitlab.instance_url}")

        from .gitlab.client import GitLabClient

        async def test_connection() -> None:
            async with GitLabClient(config_obj.gitlab) as client:
                # Test basic connection
                result = await client.test_connection()
                if result["status"] == "success":
                    typer.echo(f"✓ Connected as user: {result['user']}")
                    typer.echo(f"  GitLab version: {result['gitlab_version']}")
                else:
                    typer.echo(f"✗ Connection failed: {result['error']}")
                    raise typer.Exit(1)

                # Test repository access
                typer.echo("\nTesting repository access:")
                for repo in config_obj.gitlab.repositories:
                    try:
                        project = await client.get_project(repo.url)
                        typer.echo(f"✓ {repo.url} - {project.name}")

                        # Test file fetching
                        rule_files = await client.fetch_rule_files(repo)
                        typer.echo(f"  Found {len(rule_files)} rule files")
                        for file_path in list(rule_files.keys())[:3]:  # Show first 3
                            typer.echo(f"    - {file_path}")
                        if len(rule_files) > 3:
                            typer.echo(f"    ... and {len(rule_files) - 3} more")

                    except Exception as e:
                        typer.echo(f"✗ {repo.url} - Error: {e}")
                        continue

        asyncio.run(test_connection())

    except ValidationError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error testing GitLab: {e}", err=True)
        raise typer.Exit(1)


@app.command("cache")
def cache_command() -> None:
    """Cache management commands."""
    typer.echo("Use 'cache clear' or 'cache stats' subcommands")


@app.command("cache-clear")
def cache_clear_command(
    config: Path = typer.Argument(
        ...,
        help="Path to configuration file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Clear the cache."""
    try:
        config_obj = create_config(config)
        validate_config(config_obj)

        typer.echo("Clearing cache...")

        from .cache.factory import create_cache_manager

        async def clear_cache() -> None:
            cache_manager = create_cache_manager(config_obj.cache)
            async with cache_manager:
                await cache_manager.clear_all()
                typer.echo("✓ Cache cleared successfully")

        asyncio.run(clear_cache())

    except ValidationError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error clearing cache: {e}", err=True)
        raise typer.Exit(1)


@app.command("cache-stats")
def cache_stats_command(
    config: Path = typer.Argument(
        ...,
        help="Path to configuration file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Show cache statistics."""
    try:
        config_obj = create_config(config)
        validate_config(config_obj)

        typer.echo("Cache statistics:")

        from .cache.factory import create_cache_manager

        async def show_stats() -> None:
            cache_manager = create_cache_manager(config_obj.cache)
            async with cache_manager:
                stats = await cache_manager.get_stats()

                typer.echo(f"Backend: {config_obj.cache.backend.value}")
                typer.echo(f"Items: {stats.item_count}")
                typer.echo(f"Hit rate: {stats.hit_rate:.2%} ({stats.hit_count}/{stats.hit_count + stats.miss_count})")

                if stats.memory_usage_bytes:
                    mb = stats.memory_usage_bytes / 1024 / 1024
                    typer.echo(f"Memory usage: {mb:.2f} MB")

                if stats.storage_usage_bytes:
                    mb = stats.storage_usage_bytes / 1024 / 1024
                    typer.echo(f"Storage usage: {mb:.2f} MB")

                if stats.oldest_entry:
                    typer.echo(f"Oldest entry: {stats.oldest_entry}")
                if stats.newest_entry:
                    typer.echo(f"Newest entry: {stats.newest_entry}")

                # Show per-repository stats
                typer.echo("\nPer-repository stats:")
                for repo in config_obj.gitlab.repositories:
                    repo_stats = await cache_manager.get_repository_stats(repo)
                    typer.echo(f"  {repo.url}:{repo.branch} - {repo_stats['cached_files']} files")

        asyncio.run(show_stats())

    except ValidationError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error getting cache stats: {e}", err=True)
        raise typer.Exit(1)


@app.command("health-check")
def health_check_command(
    config: Path = typer.Argument(
        ...,
        help="Path to configuration file",
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
    ),
) -> None:
    """Check system health status."""
    try:
        config_obj = create_config(config)
        validate_config(config_obj)

        typer.echo("Checking system health...")

        from .cache.factory import create_cache_manager
        from .gitlab.client import GitLabClient
        from .utils.health import (
            CacheHealthChecker,
            GitLabHealthChecker,
            SystemHealthChecker,
        )

        async def check_health() -> None:
            # Create components
            cache_manager = create_cache_manager(config_obj.cache)
            gitlab_client = GitLabClient(config_obj.gitlab)

            # Create health checkers
            gitlab_checker = GitLabHealthChecker(gitlab_client, config_obj.gitlab.repositories)
            cache_checker = CacheHealthChecker(cache_manager)

            system_checker = SystemHealthChecker([gitlab_checker, cache_checker])

            # Run health checks
            async with cache_manager:
                system_health = await system_checker.check_all()

                # Display results
                status_colors = {
                    "healthy": typer.colors.GREEN,
                    "degraded": typer.colors.YELLOW,
                    "unhealthy": typer.colors.RED,
                }

                color = status_colors.get(system_health.status, typer.colors.WHITE)
                typer.echo("\nSystem Health: ", nl=False)
                typer.secho(system_health.status.upper(), fg=color, bold=True)
                typer.echo(f"Checked at: {system_health.checked_at.strftime('%Y-%m-%d %H:%M:%S UTC')}")

                for check in system_health.checks:
                    status_symbol = {
                        "healthy": "✓",
                        "degraded": "⚠",
                        "unhealthy": "✗",
                    }.get(check.status, "?")

                    check_color = status_colors.get(check.status, typer.colors.WHITE)

                    typer.echo(f"\n{status_symbol} ", nl=False)
                    typer.secho(f"{check.component.upper()}: {check.status}", fg=check_color)
                    typer.echo(f"  Message: {check.message}")

                    if check.details:
                        typer.echo("  Details:")
                        for key, value in check.details.items():
                            typer.echo(f"    {key}: {value}")

                # Set exit code based on overall health
                if system_health.status == "unhealthy":
                    raise typer.Exit(2)  # Critical health issues
                elif system_health.status == "degraded":
                    raise typer.Exit(1)  # Warning health issues
                # Healthy = exit code 0

        asyncio.run(check_health())

    except ValidationError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1)
    except Exception as e:
        typer.echo(f"Error checking health: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def version() -> None:
    """Show version information."""
    from . import __version__
    typer.echo(f"AIMCP version {__version__}")


def main() -> None:
    """Main entry point."""
    app()


if __name__ == "__main__":
    main()
