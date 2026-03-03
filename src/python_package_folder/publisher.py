"""
Package publishing functionality.

This module provides functionality to publish built packages to various
repositories including PyPI, PyPI Test, and Azure Artifacts.
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from enum import Enum
from pathlib import Path

try:
    import keyring
except ImportError:
    keyring = None


def _is_non_interactive() -> bool:
    """Check if running in a non-interactive environment (CI/CD)."""
    # Check for common CI environment variables
    ci_vars = ["GITHUB_ACTIONS", "CI", "CONTINUOUS_INTEGRATION", "TF_BUILD"]
    if any(os.getenv(var) for var in ci_vars):
        return True
    # Check if stdin is not a TTY (non-interactive)
    if not sys.stdin.isatty():
        return True
    return False


class Repository(Enum):
    """
    Supported package repositories.

    Attributes:
        PYPI: Official Python Package Index (https://pypi.org)
        PYPI_TEST: Test PyPI for testing package uploads (https://test.pypi.org)
        AZURE: Azure Artifacts feed (requires custom repository_url)
    """

    PYPI = "pypi"
    PYPI_TEST = "testpypi"
    AZURE = "azure"


class Publisher:
    """
    Handles publishing Python packages to various repositories.

    This class manages the publishing process, including credential handling
    and repository configuration. It uses twine under the hood for actual publishing.

    Credentials are not stored - they must be provided via command-line arguments
    or will be prompted each time. This ensures credentials are not persisted.

    Attributes:
        repository: Target repository for publishing
        dist_dir: Directory containing built distribution files
        repository_url: Custom repository URL (for Azure or custom PyPI servers)
        username: Username for authentication (optional, will be prompted if not provided)
        password: Password/token for authentication (optional, will be prompted if not provided)
    """

    def __init__(
        self,
        repository: Repository | str,
        dist_dir: Path | None = None,
        repository_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        package_name: str | None = None,
        version: str | None = None,
    ) -> None:
        """
        Initialize the publisher.

        Args:
            repository: Target repository (Repository enum or string)
            dist_dir: Directory containing distribution files (default: dist/)
            repository_url: Custom repository URL (required for Azure)
            username: Username for authentication (will prompt if not provided)
            password: Password/token for authentication (will prompt if not provided)
            package_name: Package name to filter distribution files (optional)
            version: Package version to filter distribution files (optional)
        """
        if isinstance(repository, str):
            try:
                self.repository = Repository(repository.lower())
            except ValueError as err:
                valid_repos = ", ".join(r.value for r in Repository)
                raise ValueError(
                    f"Invalid repository: {repository}. Must be one of: {valid_repos}"
                ) from err
        else:
            self.repository = repository

        self.dist_dir = dist_dir or Path("dist")
        self.repository_url = repository_url
        self.username = username
        self.password = password
        self.package_name = package_name
        self.version = version

    def _get_repository_url(self) -> str:
        """Get the repository URL based on the selected repository."""
        if self.repository_url:
            return self.repository_url

        if self.repository == Repository.PYPI:
            return "https://upload.pypi.org/legacy/"
        elif self.repository == Repository.PYPI_TEST:
            return "https://test.pypi.org/legacy/"
        elif self.repository == Repository.AZURE:
            if not self.repository_url:
                raise ValueError("repository_url is required for Azure Artifacts")
            return self.repository_url

        raise ValueError(f"Unknown repository: {self.repository}")

    def _get_credentials(self) -> tuple[str, str]:
        """
        Get credentials for publishing.

        Prompts for username and password/token if not already provided.
        In non-interactive environments (CI/CD), checks environment variables
        or raises an error if credentials are missing.

        Returns:
            Tuple of (username, password/token)
        """
        username = self.username
        password = self.password

        is_non_interactive_env = _is_non_interactive()

        # Get username
        if not username:
            if is_non_interactive_env:
                # Check environment variables
                username = os.getenv("TWINE_USERNAME") or os.getenv("PYPI_USERNAME")
                if not username:
                    raise ValueError(
                        f"Username is required for publishing to {self.repository.value} in CI/CD. "
                        "Please provide --username argument or set TWINE_USERNAME/PYPI_USERNAME environment variable."
                    )
            else:
                username = input(f"Enter username for {self.repository.value}: ").strip()
                if not username:
                    raise ValueError("Username is required")

        # Get password
        if not password:
            if is_non_interactive_env:
                # Check environment variables (common names used by twine and CI/CD)
                password = (
                    os.getenv("TWINE_PASSWORD")
                    or os.getenv("PYPI_PASSWORD")
                    or os.getenv("AZURE_ARTIFACTS_TOKEN")  # For Azure
                )
                if not password:
                    raise ValueError(
                        f"Password/token is required for publishing to {self.repository.value} in CI/CD. "
                        "Please provide --password argument or set one of: "
                        "TWINE_PASSWORD, PYPI_PASSWORD, or AZURE_ARTIFACTS_TOKEN environment variable."
                    )
            else:
                if self.repository == Repository.AZURE:
                    prompt = f"Enter Azure Artifacts token for {username}: "
                else:
                    prompt = f"Enter PyPI token for {username} (or __token__ for API token): "
                try:
                    password = getpass.getpass(prompt)
                except (EOFError, OSError):
                    # Handle non-interactive environments gracefully
                    raise ValueError(
                        f"Password/token is required for publishing to {self.repository.value}. "
                        "Cannot prompt for password in non-interactive environment. "
                        "Please provide --password argument or set TWINE_PASSWORD/PYPI_PASSWORD environment variable."
                    )
                if not password:
                    raise ValueError("Password/token is required")

        # Auto-detect if password is an API token and adjust username
        if password.startswith("pypi-") or password.startswith("pypi_Ag"):
            # This is an API token, username should be __token__
            if username != "__token__":
                print(
                    f"Note: Detected API token. Using '__token__' as username instead of '{username}'",
                    file=sys.stderr,
                )
                username = "__token__"

        # Do not store in keyring - credentials are not persisted

        return username, password

    def _check_twine_installed(self) -> bool:
        """Check if twine is installed."""
        try:
            subprocess.run(["twine", "--version"], capture_output=True, check=True)
            return True
        except (subprocess.CalledProcessError, FileNotFoundError):
            return False

    def publish(self, skip_existing: bool = False) -> None:
        """
        Publish the package to the selected repository.

        Args:
            skip_existing: If True, skip files that already exist on the repository

        Raises:
            ValueError: If twine is not installed or credentials are invalid
            subprocess.CalledProcessError: If publishing fails
        """
        if not self._check_twine_installed():
            raise ValueError("twine is required for publishing. Install it with: pip install twine")

        if not self.dist_dir.exists():
            raise ValueError(f"Distribution directory not found: {self.dist_dir}")

        all_dist_files = list(self.dist_dir.glob("*.whl")) + list(self.dist_dir.glob("*.tar.gz"))

        # Filter files by package name and version if provided
        if self.package_name and self.version:
            # Normalize package name - try both hyphen and underscore variants
            # Wheel names typically use hyphens, but source dists might use underscores
            name_hyphen = self.package_name.replace("_", "-").lower()
            name_underscore = self.package_name.replace("-", "_").lower()
            name_original = self.package_name.lower()

            # Try all name variants
            name_variants = {name_hyphen, name_underscore, name_original}
            version_str = self.version

            dist_files = []
            for f in all_dist_files:
                # Get the base filename without extension
                # For wheels: name-version-tag.whl -> name-version-tag
                # For source: name-version.tar.gz -> name-version
                stem = f.stem
                if f.suffix == ".gz" and stem.endswith(".tar"):
                    # Handle .tar.gz files
                    stem = stem[:-4]  # Remove .tar

                # Check if filename matches any name variant with exact version
                matches = False
                for name_variant in name_variants:
                    # Pattern: {name}-{version} or {name}-{version}-{tag}
                    # Use exact match: must start with name-version and next char (if any) must be - or end of string
                    expected_prefix = f"{name_variant}-{version_str}"
                    if stem.startswith(expected_prefix):
                        # Ensure exact version match (not a longer version like 1.0.10 matching 1.0.1)
                        # Check that after the version, we have either:
                        # - End of string (for source dists: name-version)
                        # - A hyphen followed by more characters (for wheels: name-version-tag)
                        remaining = stem[len(expected_prefix) :]
                        if not remaining or remaining.startswith("-"):
                            matches = True
                            break

                if matches:
                    dist_files.append(f)

            # Debug output to help diagnose filtering issues
            if dist_files:
                print(f"Filtering: package='{self.package_name}', version='{self.version}'")
                print(f"Matched {len(dist_files)} files:")
                for f in dist_files:
                    print(f"  - {f.name}")
        else:
            # If no package name or version provided, warn and upload all files
            if not self.package_name or not self.version:
                print(
                    f"Warning: No package name or version specified for filtering. "
                    f"Uploading all {len(all_dist_files)} files in dist/ directory.",
                    file=sys.stderr,
                )
            dist_files = all_dist_files

        if not dist_files:
            if self.package_name and self.version:
                raise ValueError(
                    f"No distribution files found matching package '{self.package_name}' "
                    f"version '{self.version}' in {self.dist_dir}"
                )
            else:
                raise ValueError(f"No distribution files found in {self.dist_dir}")

        username, password = self._get_credentials()
        repo_url = self._get_repository_url()

        # Build twine command
        cmd = ["twine", "upload"]
        if skip_existing:
            cmd.append("--skip-existing")
        # Always use verbose for Azure Artifacts to get better error details
        if self.repository == Repository.AZURE:
            cmd.append("--verbose")
        cmd.extend(["--repository-url", repo_url])
        cmd.extend(["--username", username])
        cmd.extend(["--password", password])
        cmd.extend([str(f) for f in dist_files])

        print(f"\nPublishing to {self.repository.value} at {repo_url}")
        print(f"Files to upload: {len(dist_files)}")

        try:
            result = subprocess.run(
                cmd,
                check=True,
                text=True,
                capture_output=True,
            )
            # Print twine output if available
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            print(f"\n✓ Successfully published to {self.repository.value}")
        except subprocess.CalledProcessError as e:
            print(f"\n✗ Failed to publish to {self.repository.value}", file=sys.stderr)
            
            # Extract and display twine's actual error message
            error_details = []
            if e.stdout:
                error_details.append(f"stdout: {e.stdout}")
            if e.stderr:
                error_details.append(f"stderr: {e.stderr}")
            if e.returncode is not None:
                error_details.append(f"exit code: {e.returncode}")
            
            if error_details:
                print("Twine error details:", file=sys.stderr)
                for detail in error_details:
                    print(f"  {detail}", file=sys.stderr)
            else:
                # Fallback to generic error if no output captured
                print(f"Command failed: {' '.join(cmd)}", file=sys.stderr)
                print(f"Return code: {e.returncode}", file=sys.stderr)
            
            # Provide helpful hints based on common errors
            if e.returncode == 1:
                if e.stderr and ("already exists" in e.stderr.lower() or "409" in e.stderr or "conflict" in e.stderr.lower()):
                    print(
                        "\nHint: This version may already exist on the repository. "
                        "Use --skip-existing to skip files that already exist, "
                        "or publish a new version.",
                        file=sys.stderr,
                    )
                elif e.stderr and ("401" in e.stderr or "unauthorized" in e.stderr.lower()):
                    print(
                        "\nHint: Authentication failed. Check your credentials.",
                        file=sys.stderr,
                    )
                elif e.stderr and ("403" in e.stderr or "forbidden" in e.stderr.lower()):
                    print(
                        "\nHint: Access forbidden. Check your permissions for this repository.",
                        file=sys.stderr,
                    )
            
            raise

    def publish_interactive(self, skip_existing: bool = False) -> None:
        """
        Publish with interactive credential prompts.

        This is a convenience method that ensures credentials are prompted
        even if they were provided during initialization.

        Args:
            skip_existing: If True, skip files that already exist on the repository
        """
        # Clear cached credentials to force prompt
        self.username = None
        self.password = None
        self.publish(skip_existing=skip_existing)

    def clear_stored_credentials(self) -> None:
        """
        Clear any stored credentials from keyring for this repository.

        This method can be used to remove previously stored credentials.
        Note: The current implementation does not store credentials, but this
        method is provided for compatibility and to clear any old stored credentials.
        """
        if keyring:
            try:
                service_name = f"python-package-folder-{self.repository.value}"
                # Try to get and delete stored username
                stored_username = keyring.get_password(service_name, "username")
                if stored_username:
                    try:
                        keyring.delete_password(service_name, stored_username)
                    except Exception:
                        pass
                    try:
                        keyring.delete_password(service_name, "username")
                    except Exception:
                        pass
            except Exception:
                pass


def get_repository_help() -> str:
    """
    Get help text for repository configuration.

    Returns:
        Helpful text about repository options and configuration
    """
    return """
Repository Options:
  - pypi: Official Python Package Index (https://pypi.org)
  - testpypi: Test PyPI for testing package uploads (https://test.pypi.org)
  - azure: Azure Artifacts feed (requires repository_url)

For PyPI/TestPyPI:
  - Username: Your PyPI username or '__token__' for API tokens
  - Password: Your PyPI password or API token

For Azure Artifacts:
  - Username: Your Azure username or feed name
  - Password: Personal Access Token (PAT) with packaging permissions
  - Repository URL: Your Azure Artifacts feed URL
    Example: https://pkgs.dev.azure.com/ORG/PROJECT/_packaging/FEED/pypi/upload
"""
