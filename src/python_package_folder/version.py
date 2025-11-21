"""
Version management functionality.

This module provides utilities for setting and managing package versions
in pyproject.toml files.
"""

from __future__ import annotations

import re
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


class VersionManager:
    """
    Manages package version in pyproject.toml.

    This class can set, get, and validate package versions in pyproject.toml files.
    It supports both static version strings and dynamic versioning configurations.
    """

    def __init__(self, project_root: Path) -> None:
        """
        Initialize the version manager.

        Args:
            project_root: Root directory containing pyproject.toml
        """
        self.project_root = project_root.resolve()
        self.pyproject_path = self.project_root / "pyproject.toml"

    def get_current_version(self) -> str | None:
        """
        Get the current version from pyproject.toml.

        Returns:
            Current version string, or None if not found or using dynamic versioning
        """
        if not self.pyproject_path.exists():
            return None

        try:
            if tomllib:
                content = self.pyproject_path.read_bytes()
                data = tomllib.loads(content)
                project = data.get("project", {})
                if "version" in project:
                    return project["version"]
            else:
                # Fallback: simple regex parsing
                content = self.pyproject_path.read_text(encoding="utf-8")
                match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
        except Exception:
            pass

        return None

    def set_version(self, version: str) -> None:
        """
        Set a static version in pyproject.toml.

        This method:
        1. Validates the version format (PEP 440)
        2. Removes dynamic versioning configuration if present
        3. Sets a static version in the [project] section

        Args:
            version: Version string to set (must be PEP 440 compliant)

        Raises:
            ValueError: If version format is invalid
            FileNotFoundError: If pyproject.toml doesn't exist
        """
        if not self.pyproject_path.exists():
            raise FileNotFoundError(f"pyproject.toml not found: {self.pyproject_path}")

        # Validate version format (basic PEP 440 check)
        if not self._validate_version(version):
            raise ValueError(
                f"Invalid version format: {version}. "
                "Version must be PEP 440 compliant (e.g., '1.2.3', '1.2.3a1', '1.2.3.post1')"
            )

        content = self.pyproject_path.read_text(encoding="utf-8")

        # Remove dynamic versioning if present
        content = self._remove_dynamic_versioning(content)

        # Set static version in [project] section
        content = self._set_static_version(content, version)

        # Write back to file
        self.pyproject_path.write_text(content, encoding="utf-8")

    def _validate_version(self, version: str) -> bool:
        """
        Validate version format (basic PEP 440 check).

        Args:
            version: Version string to validate

        Returns:
            True if version appears valid, False otherwise
        """
        # Basic PEP 440 validation regex
        # Allows: 1.2.3, 1.2.3a1, 1.2.3b2, 1.2.3rc1, 1.2.3.post1, 1.2.3.dev1
        pep440_pattern = r"^(\d+!)?(\d+)(\.\d+)*([a-zA-Z]+\d+)?(\.post\d+)?(\.dev\d+)?$"
        return bool(re.match(pep440_pattern, version))

    def _remove_dynamic_versioning(self, content: str) -> str:
        """Remove dynamic versioning configuration from pyproject.toml content."""
        lines = content.split("\n")
        result = []
        skip_next = False
        in_hatch_version = False
        in_uv_dynamic = False

        for _i, line in enumerate(lines):
            # Skip lines in sections we want to remove
            if skip_next:
                skip_next = False
                continue

            # Track section boundaries
            if line.strip().startswith("[tool.hatch.version]"):
                in_hatch_version = True
                continue
            elif line.strip().startswith("[tool.uv-dynamic-versioning]"):
                in_uv_dynamic = True
                continue
            elif line.strip().startswith("[") and in_hatch_version:
                in_hatch_version = False
            elif line.strip().startswith("[") and in_uv_dynamic:
                in_uv_dynamic = False

            # Skip lines in dynamic versioning sections
            if in_hatch_version or in_uv_dynamic:
                continue

            # Remove 'version' from dynamic list if present
            if re.match(r"^\s*dynamic\s*=\s*\[", line):
                # Check if version is in the list
                if "version" in line:
                    # Remove version from the list
                    line = re.sub(r'"version"', "", line)
                    line = re.sub(r"'version'", "", line)
                    line = re.sub(r",\s*,", ",", line)  # Remove double commas
                    line = re.sub(r"\[\s*,", "[", line)  # Remove leading comma
                    line = re.sub(r",\s*\]", "]", line)  # Remove trailing comma
                    # If dynamic list is now empty, skip the line
                    if re.match(r"^\s*dynamic\s*=\s*\[\s*\]", line):
                        continue

            result.append(line)

        return "\n".join(result)

    def _set_static_version(self, content: str, version: str) -> str:
        """Set static version in [project] section."""
        lines = content.split("\n")
        result = []
        in_project = False
        version_set = False

        for line in lines:
            if line.strip().startswith("[project]"):
                in_project = True
                result.append(line)
            elif line.strip().startswith("[") and in_project:
                # End of [project] section, add version if not set
                if not version_set:
                    result.append(f'version = "{version}"')
                in_project = False
                result.append(line)
            elif in_project and re.match(r"^\s*version\s*=", line):
                # Replace existing version
                result.append(f'version = "{version}"')
                version_set = True
            else:
                result.append(line)

        # If [project] section exists but no version was set, add it
        if in_project and not version_set:
            result.append(f'version = "{version}"')

        return "\n".join(result)

    def restore_dynamic_versioning(self) -> None:
        """
        Restore dynamic versioning configuration.

        This restores the original dynamic versioning setup if it was removed.
        Note: This is a best-effort restoration and may not perfectly match
        the original configuration.
        """
        if not self.pyproject_path.exists():
            return

        content = self.pyproject_path.read_text(encoding="utf-8")

        # Check if dynamic versioning is already present
        if "[tool.hatch.version]" in content:
            return

        # Add dynamic versioning configuration
        lines = content.split("\n")
        result = []
        project_section_found = False

        for i, line in enumerate(lines):
            result.append(line)

            # Add dynamic = ["version"] after [project] if not present
            if line.strip().startswith("[project]") and not project_section_found:
                project_section_found = True
                # Check next few lines for dynamic or version
                has_dynamic = False
                has_version = False
                for j in range(i + 1, min(i + 10, len(lines))):
                    if "dynamic" in lines[j] or "version" in lines[j]:
                        if "dynamic" in lines[j]:
                            has_dynamic = True
                        if "version" in lines[j] and not lines[j].strip().startswith("#"):
                            has_version = True
                        break
                    if lines[j].strip().startswith("["):
                        break

                if not has_dynamic and not has_version:
                    result.append('dynamic = ["version"]')

        # Add hatch versioning configuration at the end
        if "[tool.hatch.version]" not in content:
            result.append("")
            result.append("[tool.hatch.version]")
            result.append('source = "uv-dynamic-versioning"')
            result.append("")
            result.append("[tool.uv-dynamic-versioning]")
            result.append('vcs = "git"')
            result.append('style = "pep440"')
            result.append("bump = true")

        self.pyproject_path.write_text("\n".join(result), encoding="utf-8")
