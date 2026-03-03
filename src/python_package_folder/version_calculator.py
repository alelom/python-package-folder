"""
Version calculation module for determining next version from conventional commits.

This module provides a Python-native implementation for calculating semantic versions
based on conventional commits, following the Angular Commit Message Conventions
as used by semantic-release.

Reference: https://semantic-release.gitbook.io/semantic-release/
"""

from __future__ import annotations

import logging
import re
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import requests

logger = logging.getLogger(__name__)


def query_registry_version(
    package_name: str,
    repository: str,
    repository_url: str | None = None,
) -> str | None:
    """
    Query package registry for the latest published version.

    Args:
        package_name: Package name to query
        repository: Repository type ('pypi', 'testpypi', or 'azure')
        repository_url: Repository URL (required for Azure Artifacts)

    Returns:
        Latest version string or None if not found/unsupported
    """
    if not repository or not package_name:
        return None

    try:
        if repository in ("pypi", "testpypi"):
            logger.info(f"Querying {repository} for package '{package_name}'")
            version = _query_pypi_version(package_name, repository)
            if version:
                logger.info(f"Found version {version} on {repository}")
            else:
                logger.info(f"Package '{package_name}' not found on {repository} (first release)")
            return version
        elif repository == "azure":
            if not repository_url:
                logger.warning("Azure Artifacts repository URL not provided")
                return None
            logger.info(f"Querying Azure Artifacts for package '{package_name}' at {repository_url}")
            version = _query_azure_artifacts_version(package_name, repository_url)
            if version:
                logger.info(f"Found version {version} on Azure Artifacts")
            else:
                logger.info(f"Could not retrieve version from Azure Artifacts for '{package_name}' (will fall back to git tags)")
            return version
    except Exception as e:
        logger.warning(f"Error querying {repository} for package '{package_name}': {e}", exc_info=True)
        return None

    return None


def _query_pypi_version(package_name: str, registry: str) -> str | None:
    """
    Query PyPI or TestPyPI JSON API for the latest version.

    Args:
        package_name: Package name to query
        registry: 'pypi' or 'testpypi'

    Returns:
        Latest version string or None if not found
    """
    base_url = "https://test.pypi.org" if registry == "testpypi" else "https://pypi.org"
    url = f"{base_url}/pypi/{package_name}/json"

    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 404:
            # Package doesn't exist yet (first release)
            logger.debug(f"Package '{package_name}' not found on {registry} (404)")
            return None
        if response.status_code == 200:
            json_data = response.json()
            # Get latest version from info.version or releases
            version = json_data.get("info", {}).get("version")
            if not version and "releases" in json_data:
                # Fallback: get latest from releases keys
                releases = json_data["releases"]
                if releases:
                    # Sort versions and get latest
                    versions = sorted(releases.keys(), key=_parse_version_for_sort)
                    version = versions[-1] if versions else None
            if version:
                logger.debug(f"Retrieved version {version} from {registry} for '{package_name}'")
            return version
        logger.warning(f"Unexpected status code {response.status_code} from {registry} for '{package_name}'")
        return None
    except requests.RequestException as e:
        logger.warning(f"Network error querying {registry} for '{package_name}': {e}")
        return None
    except Exception as e:
        logger.warning(f"Error parsing response from {registry} for '{package_name}': {e}", exc_info=True)
        return None


class SimpleIndexParser(HTMLParser):
    """Parser for PEP 503 simple index HTML to extract package versions."""
    
    def __init__(self, package_name: str):
        super().__init__()
        self.package_name = package_name
        self.versions: set[str] = set()
        self.in_anchor = False
        self.current_href = ""
        self.links_processed = 0
    
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            self.in_anchor = True
            # Extract href attribute
            for attr_name, attr_value in attrs:
                if attr_name == "href" and attr_value:
                    self.current_href = attr_value
                    break
    
    def handle_data(self, data: str) -> None:
        if self.in_anchor:
            # Extract version from link text or href
            # Format: package-name-version-... or package-name-version.tar.gz
            link_text = data.strip()
            if link_text:
                logger.debug(f"Processing link text: '{link_text}'")
                version = self._extract_version_from_filename(link_text)
                if version:
                    logger.debug(f"Extracted version '{version}' from link text: '{link_text}'")
                    self.versions.add(version)
            # Also check href if it contains version info
            if self.current_href:
                logger.debug(f"Processing href: '{self.current_href}'")
                version = self._extract_version_from_filename(self.current_href)
                if version:
                    logger.debug(f"Extracted version '{version}' from href: '{self.current_href}'")
                    self.versions.add(version)
    
    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self.links_processed += 1
            self.in_anchor = False
            self.current_href = ""
    
    def _extract_version_from_filename(self, filename: str) -> str | None:
        """Extract version number from package filename."""
        # Pattern: package-name-version-... or package-name-version.tar.gz
        # Examples: data-0.1.0-py3-none-any.whl, data-0.1.0.tar.gz
        # The version is between the package name and the next separator
        
        # Normalize package name (replace - with _ for matching)
        normalized_package = self.package_name.replace("-", "_").replace(".", "_")
        
        # Try to match: package-name-version- or package-name-version.
        # Version format: X.Y.Z (semantic versioning)
        pattern = rf"{re.escape(self.package_name)}-(\d+\.\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9]+)?)"
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return match.group(1)
        
        # Fallback: try with normalized package name
        pattern = rf"{re.escape(normalized_package)}-(\d+\.\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9]+)?)"
        match = re.search(pattern, filename, re.IGNORECASE)
        if match:
            return match.group(1)
        
        return None


def _query_azure_artifacts_version(
    package_name: str,
    repository_url: str,
) -> str | None:
    """
    Query Azure Artifacts for the latest version.

    Azure Artifacts uses a simple index format (HTML) following PEP 503.
    Parses the HTML to extract version numbers from package filenames.

    Args:
        package_name: Package name to query
        repository_url: Azure Artifacts repository URL

    Returns:
        Latest version string or None if not found/unsupported
    """
    # Convert upload URL to simple index URL
    # Upload: https://pkgs.dev.azure.com/ORG/PROJECT/_packaging/FEED/pypi/upload
    # Simple: https://pkgs.dev.azure.com/ORG/PROJECT/_packaging/FEED/pypi/simple/{package}/
    try:
        if repository_url.endswith("/upload"):
            simple_index_url = repository_url.replace("/upload", f"/simple/{package_name}/")
        else:
            simple_index_url = repository_url.rstrip("/") + f"/simple/{package_name}/"
        logger.info(f"Constructed Azure Artifacts simple index URL: {simple_index_url}")
    except Exception as e:
        logger.warning(f"Error constructing Azure Artifacts URL for '{package_name}': {e}")
        return None

    try:
        logger.info(f"Fetching Azure Artifacts simple index for '{package_name}'...")
        response = requests.get(simple_index_url, timeout=10)
        logger.info(f"Azure Artifacts response: status={response.status_code}, content_length={len(response.text)} bytes")
        
        if response.status_code == 401:
            logger.warning(
                f"Authentication required for Azure Artifacts (401). "
                f"Package '{package_name}' may require authentication to query. "
                f"URL: {simple_index_url}"
            )
            return None
        elif response.status_code == 403:
            logger.warning(
                f"Access forbidden for Azure Artifacts (403). "
                f"Package '{package_name}' may not be accessible or requires different permissions. "
                f"URL: {simple_index_url}"
            )
            return None
        elif response.status_code == 404:
            logger.info(
                f"Package '{package_name}' not found on Azure Artifacts (404) - this appears to be the first release. "
                f"URL: {simple_index_url}"
            )
            return None
        elif response.status_code != 200:
            logger.warning(
                f"Unexpected status code {response.status_code} from Azure Artifacts for '{package_name}'. "
                f"URL: {simple_index_url}, Response preview: {response.text[:200]}"
            )
            return None
        
        # Parse HTML to extract versions
        logger.info(f"Parsing HTML response to extract versions for '{package_name}'...")
        parser = SimpleIndexParser(package_name)
        try:
            parser.feed(response.text)
            logger.info(
                f"HTML parsing completed: processed {parser.links_processed} link(s), "
                f"found {len(parser.versions)} unique version(s)"
            )
        except Exception as e:
            logger.warning(
                f"Error parsing Azure Artifacts HTML for '{package_name}': {e}. "
                f"Response length: {len(response.text)} bytes, "
                f"Response preview: {response.text[:500]}"
            )
            return None
        
        if not parser.versions:
            if parser.links_processed == 0:
                logger.info(
                    f"No links found in Azure Artifacts HTML for '{package_name}'. "
                    f"This may indicate: (1) HTML structure differs from PEP 503 format, "
                    f"(2) package doesn't exist, or (3) authentication required. "
                    f"Response preview: {response.text[:500]}"
                )
            else:
                logger.info(
                    f"Found {parser.links_processed} link(s) but no versions extracted for '{package_name}'. "
                    f"This may indicate: (1) package name mismatch (expected '{package_name}'), "
                    f"(2) filename format differs from expected pattern, or (3) first release. "
                    f"Response preview: {response.text[:500]}"
                )
            return None
        
        # Find the latest version
        versions = list(parser.versions)
        logger.info(f"Found {len(versions)} version(s) in Azure Artifacts HTML: {versions}")
        
        # Sort versions to find the latest
        try:
            sorted_versions = sorted(versions, key=_parse_version_for_sort, reverse=True)
            latest_version = sorted_versions[0]
            logger.info(f"Latest version on Azure Artifacts for '{package_name}': {latest_version}")
            return latest_version
        except Exception as e:
            logger.warning(
                f"Error sorting versions for '{package_name}': {e}. "
                f"Versions found: {versions}. Using first version as fallback."
            )
            # Fallback: return the first version found
            return versions[0]
            
    except requests.RequestException as e:
        logger.warning(
            f"Network error querying Azure Artifacts for '{package_name}': {e}. "
            f"URL: {simple_index_url}"
        )
        return None
    except Exception as e:
        logger.warning(
            f"Unexpected error querying Azure Artifacts for '{package_name}': {e}. "
            f"URL: {simple_index_url}",
            exc_info=True
        )
        return None


def _parse_version_for_sort(version_str: str) -> tuple[int, ...]:
    """
    Parse version string for sorting.

    Args:
        version_str: Version string (e.g., "1.2.3")

    Returns:
        Tuple of integers for sorting
    """
    try:
        parts = version_str.split(".")
        return tuple(int(p) for p in parts if p.isdigit())
    except Exception:
        return (0,)


def get_latest_git_tag(
    project_root: Path,
    package_name: str | None = None,
    is_subfolder: bool = False,
) -> str | None:
    """
    Get the latest git tag version.

    Args:
        project_root: Root directory of the project
        package_name: Package name for subfolder builds
        is_subfolder: Whether this is a subfolder build

    Returns:
        Latest version string or None if no tags found
    """
    try:
        if is_subfolder and package_name:
            # For subfolder: look for tags matching {package-name}-v{version}
            tag_pattern = f"{package_name}-v*"
        else:
            # For main package: look for tags matching v{version}
            tag_pattern = "v*"

        result = subprocess.run(
            ["git", "tag", "--list", tag_pattern],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0 or not result.stdout.strip():
            return None

        tags = [tag.strip() for tag in result.stdout.strip().split("\n") if tag.strip()]

        if not tags:
            return None

        # Extract versions from tags and find latest
        versions = []
        for tag in tags:
            if is_subfolder and package_name:
                # Extract version from {package-name}-v{version}
                prefix = f"{package_name}-v"
                if tag.startswith(prefix):
                    version_str = tag[len(prefix) :]
                else:
                    continue
            else:
                # Extract version from v{version}
                if tag.startswith("v"):
                    version_str = tag[1:]
                else:
                    continue

            # Validate version format (basic check)
            if _is_valid_version(version_str):
                versions.append((version_str, tag))

        if not versions:
            return None

        # Sort versions and return latest
        versions.sort(key=lambda x: _parse_version_for_sort(x[0]))
        return versions[-1][0]

    except Exception:
        return None


def _is_valid_version(version_str: str) -> bool:
    """
    Check if version string is valid (basic validation).

    Args:
        version_str: Version string to validate

    Returns:
        True if valid, False otherwise
    """
    # Basic validation: should match pattern like "1.2.3" or "1.2.3-alpha.1"
    pattern = r"^\d+\.\d+\.\d+(-[a-zA-Z0-9.-]+)?$"
    return bool(re.match(pattern, version_str))


def get_commits_since(
    project_root: Path,
    baseline_version: str,
    subfolder_path: Path | None = None,
    package_name: str | None = None,
) -> list[str]:
    """
    Get commit messages since the baseline version.

    Args:
        project_root: Root directory of the project
        baseline_version: Baseline version to compare against
        subfolder_path: Optional path to subfolder for filtering commits
        package_name: Optional package name for subfolder builds (needed for tag matching)

    Returns:
        List of commit messages (full messages, not just subjects)
    """
    try:
        # Determine tag format based on whether we have subfolder info
        if subfolder_path and package_name:
            # For subfolder: {package-name}-v{version}
            tag_pattern = f"{package_name}-v{baseline_version}"
        else:
            # For main package: v{version}
            tag_pattern = f"v{baseline_version}"

        # Try to find the tag
        result = subprocess.run(
            ["git", "tag", "--list", tag_pattern],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        tag = None
        if result.returncode == 0 and result.stdout.strip():
            tags = [t.strip() for t in result.stdout.strip().split("\n") if t.strip()]
            if tags:
                tag = tags[0]  # Use first matching tag

        if not tag:
            # If tag not found, we can't determine commits since that version
            # Return empty list - the caller should handle this case
            return []
        
        base_ref = tag

        # Build git log command
        cmd = ["git", "log", "--format=%B", f"{base_ref}..HEAD"]

        # If subfolder_path provided, filter commits by path
        if subfolder_path:
            # Convert to relative path from project root
            if subfolder_path.is_absolute():
                rel_path = subfolder_path.relative_to(project_root)
            else:
                rel_path = subfolder_path
            cmd.append("--")
            cmd.append(str(rel_path))

        result = subprocess.run(
            cmd,
            cwd=project_root,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            return []

        # Split commits (they're separated by double newlines in --format=%B)
        commits = []
        current_commit = []
        for line in result.stdout.split("\n"):
            if line.strip() == "" and current_commit:
                # Empty line after commit content - save this commit
                commit_msg = "\n".join(current_commit).strip()
                if commit_msg:
                    commits.append(commit_msg)
                current_commit = []
            else:
                current_commit.append(line)

        # Don't forget the last commit if there's no trailing newline
        if current_commit:
            commit_msg = "\n".join(current_commit).strip()
            if commit_msg:
                commits.append(commit_msg)

        return commits

    except Exception:
        return []


def parse_commit_for_bump(commit_message: str) -> str | None:
    """
    Parse conventional commit message to determine version bump type.

    Follows Angular Commit Message Conventions as used by semantic-release.
    Reference: https://semantic-release.gitbook.io/semantic-release/

    Args:
        commit_message: Full commit message

    Returns:
        'major', 'minor', 'patch', or None if no version bump needed
    """
    if not commit_message:
        return None

    # Normalize line endings and split into lines
    lines = commit_message.replace("\r\n", "\n").split("\n")
    if not lines:
        return None

    # First line is the subject
    subject = lines[0].strip()

    # Check for breaking change indicators
    # 1. Check for '!' after type/scope: feat!:, feat(scope)!:, etc.
    breaking_pattern = r"^(\w+)(\([^)]+\))?!:\s"
    if re.match(breaking_pattern, subject):
        return "major"

    # 2. Check for BREAKING CHANGE in body/footer (case-insensitive)
    body = "\n".join(lines[1:]) if len(lines) > 1 else ""
    body_lower = body.lower()
    if "breaking change:" in body_lower or "breaking change" in body_lower:
        return "major"

    # Parse conventional commit format: type(scope): description
    # Types that trigger version bumps:
    # - feat: minor
    # - fix: patch
    # - perf: patch
    commit_pattern = r"^(\w+)(\([^)]+\))?:\s"
    match = re.match(commit_pattern, subject)
    if not match:
        return None

    commit_type = match.group(1).lower()

    # Version bump rules
    if commit_type == "feat":
        return "minor"
    elif commit_type in ("fix", "perf"):
        return "patch"
    else:
        # Ignored types: docs, style, refactor, test, build, ci, chore, revert
        return None


def calculate_next_version(
    baseline_version: str,
    commits: list[str],
) -> str | None:
    """
    Calculate next version from baseline and commits.

    Args:
        baseline_version: Current baseline version (e.g., "1.2.3")
        commits: List of commit messages since baseline

    Returns:
        Next version string or None if no changes require a version bump
    """
    if not commits:
        return None

    # Parse each commit to determine bump type
    bump_types = []
    for commit in commits:
        bump = parse_commit_for_bump(commit)
        if bump:
            bump_types.append(bump)

    if not bump_types:
        return None

    # Determine highest bump (major > minor > patch)
    if "major" in bump_types:
        bump_type = "major"
    elif "minor" in bump_types:
        bump_type = "minor"
    else:
        bump_type = "patch"

    # Increment version
    try:
        parts = baseline_version.split(".")
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
        patch = int(parts[2]) if len(parts) > 2 else 0

        if bump_type == "major":
            return f"{major + 1}.0.0"
        elif bump_type == "minor":
            return f"{major}.{minor + 1}.0"
        else:  # patch
            return f"{major}.{minor}.{patch + 1}"
    except (ValueError, IndexError):
        return None


def resolve_version(
    project_root: Path,
    package_name: str | None = None,
    subfolder_path: Path | None = None,
    repository: str | None = None,
    repository_url: str | None = None,
) -> tuple[str | None, str | None]:
    """
    Resolve the next version using conventional commits.

    This is the main entry point that replaces resolve_version_via_semantic_release.

    Args:
        project_root: Root directory of the project
        package_name: Optional package name (for registry queries and subfolder tags)
        subfolder_path: Optional path to subfolder (relative to project_root)
        repository: Optional target repository ('pypi', 'testpypi', or 'azure')
        repository_url: Optional repository URL (required for Azure Artifacts)

    Returns:
        Tuple of (version string if a release is determined, error message if any)
        Returns (None, None) if no release or no error, (None, error_msg) on error
    """
    is_subfolder = subfolder_path is not None and package_name is not None

    # Step 1: Try to get baseline version from registry
    baseline_version = None
    if repository and package_name:
        logger.info(f"Attempting to query {repository} for baseline version of '{package_name}'")
        baseline_version = query_registry_version(package_name, repository, repository_url)

    # Step 2: Fallback to git tags if registry query failed
    if not baseline_version:
        logger.info(f"Registry query did not return a version, falling back to git tags")
        if is_subfolder:
            logger.debug(f"Looking for subfolder git tags matching '{package_name}-v*'")
        else:
            logger.debug("Looking for main package git tags matching 'v*'")
        baseline_version = get_latest_git_tag(project_root, package_name, is_subfolder)
        if baseline_version:
            logger.info(f"Found baseline version {baseline_version} from git tags")
        else:
            logger.info("No git tags found")

    # Step 3: If still no baseline, this is likely the first release
    # Default to 0.0.0 as the starting version (standard semantic-release behavior)
    if not baseline_version:
        logger.info("No baseline version found (no registry version or git tags). Treating as first release (baseline: 0.0.0)")
        baseline_version = "0.0.0"
        # For first release, get all commits (no baseline to compare against)
        # Use HEAD as the reference point to get all commits
        try:
            cmd = ["git", "log", "--format=%B", "HEAD"]
            if subfolder_path:
                # Convert to relative path from project root
                if subfolder_path.is_absolute():
                    rel_path = subfolder_path.relative_to(project_root)
                else:
                    rel_path = subfolder_path
                cmd.append("--")
                cmd.append(str(rel_path))
            
            result = subprocess.run(
                cmd,
                cwd=project_root,
                capture_output=True,
                text=True,
                check=False,
            )
            
            commits = []
            if result.returncode == 0:
                # Split commits (they're separated by double newlines in --format=%B)
                current_commit = []
                for line in result.stdout.split("\n"):
                    if line.strip() == "" and current_commit:
                        commit_msg = "\n".join(current_commit).strip()
                        if commit_msg:
                            commits.append(commit_msg)
                        current_commit = []
                    else:
                        current_commit.append(line)
                
                # Don't forget the last commit if there's no trailing newline
                if current_commit:
                    commit_msg = "\n".join(current_commit).strip()
                    if commit_msg:
                        commits.append(commit_msg)
                logger.debug(f"Retrieved {len(commits)} commits for first release")
        except Exception as e:
            logger.warning(f"Error retrieving commits for first release: {e}", exc_info=True)
            commits = []
    else:
        # Step 4: Get commits since baseline
        logger.info(f"Retrieving commits since version {baseline_version}")
        if subfolder_path:
            logger.debug(f"Filtering commits for subfolder path: {subfolder_path}")
        commits = get_commits_since(project_root, baseline_version, subfolder_path, package_name)
        logger.debug(f"Found {len(commits)} commits since {baseline_version}")

    # Step 5: Calculate next version
    logger.info(f"Calculating next version from baseline {baseline_version} and {len(commits)} commits")
    next_version = calculate_next_version(baseline_version, commits)

    if next_version:
        logger.info(f"Calculated next version: {next_version}")
        return next_version, None
    else:
        # No relevant commits for version bump
        # For first release (0.0.0), default to 0.1.0 if there are any commits
        if baseline_version == "0.0.0" and commits:
            # Even if commits don't match conventional format, start at 0.1.0 for first release
            logger.info("No conventional commits found, but commits exist. Defaulting to 0.1.0 for first release")
            return "0.1.0", None
        logger.info("No version bump needed (no relevant conventional commits found)")
        return None, None
