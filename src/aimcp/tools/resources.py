"""Resource URI scheme handler for AIMCP."""

from urllib.parse import urlparse

from ..utils.logging import get_logger

logger = get_logger("tools.resources")


class ResourceURIError(Exception):
    """Error in resource URI handling."""


class ResourceURIHandler:
    """Handles aimcp:// resource URI scheme."""

    SCHEME = "aimcp"

    @classmethod
    def parse_uri(cls, uri: str) -> tuple[str, str, str]:
        """Parse an aimcp:// resource URI.

        Args:
            uri: Resource URI in format aimcp://repository/branch/file/path

        Returns:
            Tuple of (repository, branch, file_path)

        Raises:
            ResourceURIError: If URI format is invalid
        """
        if not uri.startswith(f"{cls.SCHEME}://"):
            raise ResourceURIError(f"Invalid URI scheme: {uri}")

        try:
            parsed = urlparse(uri)

            if parsed.scheme != cls.SCHEME:
                raise ResourceURIError(
                    f"Expected scheme '{cls.SCHEME}', got '{parsed.scheme}'"
                )

            # Extract repository from netloc (host part)
            repository = parsed.netloc
            if not repository:
                raise ResourceURIError("Missing repository in URI")

            # Extract branch and file path from path
            path_parts = parsed.path.lstrip("/").split("/", 1)
            if len(path_parts) < 2:
                raise ResourceURIError("URI must include branch and file path")

            branch, file_path = path_parts

            if not branch:
                raise ResourceURIError("Missing branch in URI")
            if not file_path:
                raise ResourceURIError("Missing file path in URI")

            return repository, branch, file_path

        except ValueError as e:
            raise ResourceURIError(f"Invalid URI format: {uri}") from e

    @classmethod
    def build_uri(cls, repository: str, branch: str, file_path: str) -> str:
        """Build an aimcp:// resource URI.

        Args:
            repository: Repository URL/name
            branch: Branch name
            file_path: File path within repository

        Returns:
            Complete resource URI
        """
        # Clean up components
        repository = repository.strip("/")
        branch = branch.strip("/")
        file_path = file_path.strip("/")

        return f"{cls.SCHEME}://{repository}/{branch}/{file_path}"

    @classmethod
    def validate_uri(cls, uri: str) -> bool:
        """Validate that a URI is a valid aimcp:// resource URI.

        Args:
            uri: URI to validate

        Returns:
            True if valid, False otherwise
        """
        try:
            cls.parse_uri(uri)
            return True
        except ResourceURIError:
            return False

    @classmethod
    def is_aimcp_uri(cls, uri: str) -> bool:
        """Check if a URI uses the aimcp:// scheme.

        Args:
            uri: URI to check

        Returns:
            True if it's an aimcp:// URI, False otherwise
        """
        return uri.startswith(f"{cls.SCHEME}://")
