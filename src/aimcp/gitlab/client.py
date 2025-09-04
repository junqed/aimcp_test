"""Async GitLab API client."""

import asyncio
import base64
import fnmatch
from urllib.parse import quote

import httpx
from httpx import AsyncClient, Response

from ..config.models import GitLabConfig, GitLabRepository
from ..utils.logging import get_logger
from .models import (
    GitLabBranch,
    GitLabError,
    GitLabFile,
    GitLabFileContent,
    GitLabProject,
    GitLabTree,
)

logger = get_logger("gitlab")


class GitLabClientError(Exception):
    """GitLab client error."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class GitLabClient:
    """Async GitLab API client."""

    def __init__(self, config: GitLabConfig) -> None:
        """Initialize GitLab client.

        Args:
            config: GitLab configuration
        """
        self.config = config
        self.base_url = str(config.instance_url).rstrip("/")
        self.api_url = f"{self.base_url}/api/v4"

        # HTTP client configuration
        self.client = AsyncClient(
            timeout=config.timeout,
            headers={
                "Private-Token": config.token,
                "User-Agent": "AIMCP/0.1.0",
            },
        )

    async def __aenter__(self) -> "GitLabClient":
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:  # type: ignore
        """Async context manager exit."""
        await self.close()

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def _make_request(
        self,
        method: str,
        endpoint: str,
        **kwargs  # type: ignore
    ) -> Response:
        """Make HTTP request to GitLab API.

        Args:
            method: HTTP method
            endpoint: API endpoint (without /api/v4 prefix)
            **kwargs: Additional request parameters

        Returns:
            HTTP response

        Raises:
            GitLabClientError: If request fails
        """
        url = f"{self.api_url}/{endpoint.lstrip('/')}"

        for attempt in range(self.config.max_retries + 1):
            try:
                logger.debug("Making GitLab API request",
                           method=method, url=url, attempt=attempt)

                response = await self.client.request(method, url, **kwargs)

                if response.status_code == 429:  # Rate limit
                    if attempt < self.config.max_retries:
                        wait_time = 2 ** attempt
                        logger.warning("Rate limited, retrying",
                                     wait_time=wait_time, attempt=attempt)
                        await asyncio.sleep(wait_time)
                        continue

                if response.status_code >= 400:
                    try:
                        error_data = response.json()
                        error = GitLabError(**error_data)
                        message = error.message
                    except Exception:
                        message = f"HTTP {response.status_code}: {response.text}"

                    raise GitLabClientError(message, response.status_code)

                logger.debug("GitLab API request successful",
                           status_code=response.status_code)
                return response

            except httpx.RequestError as e:
                if attempt < self.config.max_retries:
                    wait_time = 2 ** attempt
                    logger.warning("Request failed, retrying",
                                 error=str(e), wait_time=wait_time, attempt=attempt)
                    await asyncio.sleep(wait_time)
                    continue
                raise GitLabClientError(f"Request failed: {e}")

        raise GitLabClientError("Max retries exceeded")

    async def get_project(self, project_path: str) -> GitLabProject:
        """Get project information.

        Args:
            project_path: Project path (e.g., "group/project")

        Returns:
            Project information
        """
        encoded_path = quote(project_path, safe="")
        response = await self._make_request("GET", f"/projects/{encoded_path}")
        return GitLabProject(**response.json())

    async def get_branches(self, project_path: str) -> list[GitLabBranch]:
        """Get project branches.

        Args:
            project_path: Project path

        Returns:
            List of branches
        """
        encoded_path = quote(project_path, safe="")
        response = await self._make_request("GET", f"/projects/{encoded_path}/repository/branches")
        return [GitLabBranch(**branch) for branch in response.json()]

    async def get_tree(
        self,
        project_path: str,
        ref: str = "main",
        path: str = "",
        recursive: bool = False,
    ) -> list[GitLabTree]:
        """Get repository tree (directory listing).

        Args:
            project_path: Project path
            ref: Git reference (branch, tag, commit)
            path: Path within repository
            recursive: Whether to get recursive listing

        Returns:
            List of tree entries
        """
        encoded_path = quote(project_path, safe="")
        params = {"ref": ref}
        if path:
            params["path"] = path
        if recursive:
            params["recursive"] = "true"

        response = await self._make_request(
            "GET",
            f"/projects/{encoded_path}/repository/tree",
            params=params,
        )
        return [GitLabTree(**entry) for entry in response.json()]

    async def get_file(
        self,
        project_path: str,
        file_path: str,
        ref: str = "main",
    ) -> GitLabFileContent:
        """Get file content.

        Args:
            project_path: Project path
            file_path: File path within repository
            ref: Git reference

        Returns:
            File content
        """
        encoded_path = quote(project_path, safe="")
        encoded_file_path = quote(file_path, safe="")
        params = {"ref": ref}

        response = await self._make_request(
            "GET",
            f"/projects/{encoded_path}/repository/files/{encoded_file_path}",
            params=params,
        )
        return GitLabFileContent(**response.json())

    async def get_file_content_decoded(
        self,
        project_path: str,
        file_path: str,
        ref: str = "main",
    ) -> str:
        """Get file content decoded as string.

        Args:
            project_path: Project path
            file_path: File path within repository
            ref: Git reference

        Returns:
            Decoded file content
        """
        file_info = await self.get_file(project_path, file_path, ref)

        if file_info.encoding == "base64":
            content_bytes = base64.b64decode(file_info.content)
            return content_bytes.decode("utf-8")
        else:
            # Assume text content
            return file_info.content

    async def find_files_by_pattern(
        self,
        project_path: str,
        patterns: list[str],
        ref: str = "main",
        path: str = "",
    ) -> list[GitLabFile]:
        """Find files matching glob patterns.

        Args:
            project_path: Project path
            patterns: List of glob patterns to match
            ref: Git reference
            path: Root path to search from

        Returns:
            List of matching files
        """
        # Get recursive tree listing
        tree_entries = await self.get_tree(project_path, ref, path, recursive=True)

        matching_files = []
        for entry in tree_entries:
            if entry.type != "blob":  # Only files, not directories
                continue

            # Check if file matches any pattern
            for pattern in patterns:
                if fnmatch.fnmatch(entry.path, pattern):
                    file_info = GitLabFile(
                        id=entry.id,
                        name=entry.name,
                        path=entry.path,
                        type=entry.type,
                        mode=entry.mode,
                    )
                    matching_files.append(file_info)
                    break

        logger.info("Found matching files",
                   project=project_path,
                   patterns=patterns,
                   count=len(matching_files))

        return matching_files

    async def fetch_rule_files(
        self, repository: GitLabRepository
    ) -> dict[str, str]:
        """Fetch all rule files from a repository.

        Args:
            repository: Repository configuration

        Returns:
            Dictionary mapping file paths to content
        """
        logger.info("Fetching rule files",
                   repository=repository.url,
                   branch=repository.branch,
                   patterns=repository.file_patterns)

        try:
            # Find matching files
            files = await self.find_files_by_pattern(
                repository.url,
                repository.file_patterns,
                repository.branch,
            )

            # Fetch content for each file
            rule_files = {}
            for file_info in files:
                try:
                    content = await self.get_file_content_decoded(
                        repository.url,
                        file_info.path,
                        repository.branch,
                    )
                    rule_files[file_info.path] = content

                    logger.debug("Fetched rule file",
                               file=file_info.path,
                               size=len(content))

                except Exception as e:
                    logger.error("Failed to fetch rule file",
                               file=file_info.path,
                               error=str(e))
                    continue

            logger.info("Successfully fetched rule files",
                       repository=repository.url,
                       count=len(rule_files))

            return rule_files

        except Exception as e:
            logger.error("Failed to fetch rule files",
                        repository=repository.url,
                        error=str(e))
            raise

    async def test_connection(self) -> dict[str, str]:
        """Test GitLab API connection.

        Returns:
            Connection test results
        """
        try:
            # Test API connectivity with user info
            response = await self._make_request("GET", "/user")
            user_data = response.json()

            return {
                "status": "success",
                "user": user_data.get("username", "unknown"),
                "gitlab_version": response.headers.get("x-gitlab-version", "unknown"),
            }

        except Exception as e:
            return {
                "status": "failed",
                "error": str(e),
            }
