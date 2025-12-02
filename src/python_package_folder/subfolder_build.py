"""
Subfolder build configuration management.

This module handles creating temporary build configurations for subfolders
that need to be built as separate packages with their own names and versions.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Self

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


class SubfolderBuildConfig:
    """
    Manages temporary build configuration for subfolder builds.

    When building a subfolder as a separate package, this class:
    - Uses the subfolder's pyproject.toml if it exists (adjusts package paths and ensures
      [build-system] uses hatchling)
    - Otherwise creates a temporary pyproject.toml with the appropriate package name and version
    - Always ensures [build-system] section uses hatchling (replaces any existing build-system
      configuration from parent or subfolder)
    - Handles README files similarly (uses subfolder README if present)
    - **Never modifies the root pyproject.toml**: The original file is temporarily moved to
      pyproject.toml.original and restored after the build, ensuring the original is never modified
    """

    def __init__(
        self,
        project_root: Path,
        src_dir: Path,
        package_name: str | None = None,
        version: str | None = None,
        dependency_group: str | None = None,
    ) -> None:
        """
        Initialize subfolder build configuration.

        Args:
            project_root: Root directory containing the main pyproject.toml
            src_dir: Source directory being built (subfolder)
            package_name: Name for the subfolder package (default: derived from src_dir name).
                Only used if subfolder doesn't have its own pyproject.toml.
            version: Version for the subfolder package (required if building subfolder).
                Only used if subfolder doesn't have its own pyproject.toml.
            dependency_group: Name of dependency group to copy from parent pyproject.toml.
                Only used if subfolder doesn't have its own pyproject.toml.
        """
        self.project_root = project_root.resolve()
        self.src_dir = src_dir.resolve()
        self.package_name = package_name or self._derive_package_name()
        self.version = version
        self.dependency_group = dependency_group
        self.temp_pyproject: Path | None = None
        self.original_pyproject_backup: Path | None = None
        self.original_pyproject_path: Path | None = None
        self._temp_init_created = False
        self.temp_readme: Path | None = None
        self.original_readme_backup: Path | None = None
        self._used_subfolder_pyproject = False

    def _derive_package_name(self) -> str:
        """Derive package name from source directory name."""
        # Use the directory name, replacing invalid characters
        name = self.src_dir.name
        # Replace invalid characters with hyphens
        name = name.replace("_", "-").replace(" ", "-").lower()
        # Remove any leading/trailing hyphens
        name = name.strip("-")
        return name

    def _get_package_structure(self) -> tuple[str, list[str]]:
        """
        Determine the package structure for hatchling.

        Returns:
            Tuple of (packages_path, package_dirs) where:
            - packages_path: The path to the directory containing packages
            - package_dirs: List of package directories to include
        """
        # Check if src_dir itself is a package (has __init__.py)
        has_init = (self.src_dir / "__init__.py").exists()

        # Check for Python files directly in src_dir
        py_files = list(self.src_dir.glob("*.py"))
        has_py_files = bool(py_files)

        # Calculate relative path
        try:
            rel_path = self.src_dir.relative_to(self.project_root)
            packages_path = str(rel_path).replace("\\", "/")
        except ValueError:
            packages_path = None

        # If src_dir has Python files but no __init__.py, we need to make it a package
        # or include it as a module directory
        if has_py_files and not has_init:
            # For flat structures, we include the directory itself
            # Hatchling will treat Python files in the directory as modules
            return packages_path, [packages_path] if packages_path else []

        # If it's a package or has subpackages, return the path
        return packages_path, [packages_path] if packages_path else []

    def _adjust_subfolder_pyproject_packages_path(self, content: str) -> str:
        """
        Adjust packages path in subfolder pyproject.toml to be relative to project root.

        When a subfolder's pyproject.toml is copied to project root, the packages path
        needs to be adjusted to point to the subfolder relative to the project root.

        Args:
            content: Content of the subfolder's pyproject.toml

        Returns:
            Adjusted content with correct packages path
        """
        # Get the correct packages path relative to project root
        _, package_dirs = self._get_package_structure()
        if not package_dirs:
            # No adjustment needed if we can't determine the path
            return content

        correct_packages_path = package_dirs[0]
        lines = content.split("\n")
        result = []
        in_hatch_build = False
        in_hatch_build_section = False
        packages_set = False
        paths_exclude_set = False

        for line in lines:
            # Detect hatch build section
            if line.strip().startswith("[tool.hatch.build.targets.wheel]"):
                in_hatch_build = True
                result.append(line)
                continue
            elif line.strip().startswith("[tool.hatch.build]"):
                in_hatch_build_section = True
                result.append(line)
                continue
            elif line.strip().startswith("[") and in_hatch_build:
                # End of hatch build section, add packages if not set
                if not packages_set and correct_packages_path:
                    packages_str = f'"{correct_packages_path}"'
                    result.append(f"packages = [{packages_str}]")
                in_hatch_build = False
                result.append(line)
            elif line.strip().startswith("[") and in_hatch_build_section:
                # End of hatch build section
                in_hatch_build_section = False
                result.append(line)
            elif in_hatch_build_section:
                # Track if paths-exclude already exists
                if re.match(r"^\s*paths-exclude\s*=", line):
                    paths_exclude_set = True
                result.append(line)
            elif in_hatch_build:
                # Modify packages path if found
                if re.match(r"^\s*packages\s*=", line):
                    packages_str = f'"{correct_packages_path}"'
                    result.append(f"packages = [{packages_str}]")
                    packages_set = True
                    continue
                # Keep other lines in hatch build section
                result.append(line)
            else:
                result.append(line)

        # Add packages if we're still in hatch build section and haven't set it
        if in_hatch_build and not packages_set and correct_packages_path:
            packages_str = f'"{correct_packages_path}"'
            result.append(f"packages = [{packages_str}]")

        # Ensure build-system section exists (required for hatchling)
        # Check if build-system section exists in the result
        has_build_system = any(line.strip().startswith("[build-system]") for line in result)
        if not has_build_system:
            # Insert build-system at the very beginning of the file
            build_system_lines = [
                "[build-system]",
                'requires = ["hatchling"]',
                'build-backend = "hatchling.build"',
                "",
            ]
            result = build_system_lines + result

        # Ensure hatch build section exists if packages path is needed
        if not packages_set and correct_packages_path:
            # Check if we need to add the section
            if "[tool.hatch.build.targets.wheel]" not in content:
                result.append("")
                result.append("[tool.hatch.build.targets.wheel]")
                packages_str = f'"{correct_packages_path}"'
                result.append(f"packages = [{packages_str}]")

        # Add file exclusion patterns to prevent including non-package files
        # Only add if paths-exclude wasn't already set (we merged it above)
        if not paths_exclude_set:
            result.append("")
            result.append("[tool.hatch.build]")
            result.append("paths-exclude = [")
            result.append('    ".cursor/**",')
            result.append('    ".github/**",')
            result.append('    ".vscode/**",')
            result.append('    ".idea/**",')
            result.append('    "data/**",')
            result.append('    "docs/**",')
            result.append('    "references/**",')
            result.append('    "reports/**",')
            result.append('    "scripts/**",')
            result.append('    "tests/**",')
            result.append('    "test/**",')
            result.append('    "dist/**",')
            result.append('    "build/**",')
            result.append('    "*.egg-info/**",')
            result.append('    "__pycache__/**",')
            result.append('    ".pytest_cache/**",')
            result.append('    ".mypy_cache/**",')
            result.append('    ".venv/**",')
            result.append('    "venv/**",')
            result.append('    ".git/**",')
            result.append('    ".gitignore",')
            result.append('    ".gitattributes",')
            result.append('    "Dockerfile",')
            result.append('    ".dockerignore",')
            result.append('    ".pylintrc",')
            result.append('    "pyrightconfig.json",')
            result.append('    "git-filter-repo",')
            result.append('    "pyproject.toml.original",')
            result.append('    "README.md.backup",')
            result.append("]")

        return "\n".join(result)

    def create_temp_pyproject(self) -> Path | None:
        """
        Create a temporary pyproject.toml for the subfolder build.

        If a pyproject.toml exists in the subfolder, it will be used (copied to project root
        with adjusted package paths and ensuring [build-system] uses hatchling). Otherwise,
        creates a pyproject.toml in the project root based on the parent pyproject.toml with
        the appropriate package name and version.

        The [build-system] section is always set to use hatchling, even if the parent or
        subfolder pyproject.toml uses a different build backend (e.g., setuptools).

        **Important**: The root pyproject.toml is never modified. Instead, it is temporarily
        moved to pyproject.toml.original and restored after the build completes. This ensures
        the original file remains unchanged.

        Returns:
            Path to the pyproject.toml file (either from subfolder or created temporary),
            or None if no parent pyproject.toml exists (in which case subfolder config is skipped)
        """
        if not self.version:
            raise ValueError("Version is required for subfolder builds")

        # Ensure src_dir is a package (has __init__.py) for hatchling
        init_file = self.src_dir / "__init__.py"
        if not init_file.exists():
            # Create a temporary __init__.py to make it a package
            init_file.write_text("# Temporary __init__.py for build\n", encoding="utf-8")
            self._temp_init_created = True
        else:
            self._temp_init_created = False

        # Check if pyproject.toml exists in subfolder
        subfolder_pyproject = self.src_dir / "pyproject.toml"
        if subfolder_pyproject.exists():
            # Use the subfolder's pyproject.toml
            print(f"Using existing pyproject.toml from subfolder: {subfolder_pyproject}")
            self._used_subfolder_pyproject = True

            # Store reference to original project root pyproject.toml
            original_pyproject = self.project_root / "pyproject.toml"
            self.original_pyproject_path = original_pyproject

            # Create temporary pyproject.toml file
            temp_pyproject_path = self.project_root / "pyproject.toml.temp"

            # Read and adjust the subfolder pyproject.toml
            subfolder_content = subfolder_pyproject.read_text(encoding="utf-8")
            # Adjust packages path to be relative to project root
            adjusted_content = self._adjust_subfolder_pyproject_packages_path(subfolder_content)

            # Write adjusted content to temporary file
            temp_pyproject_path.write_text(adjusted_content, encoding="utf-8")
            self.temp_pyproject = temp_pyproject_path

            # Print the temporary pyproject.toml content for debugging
            print("\n" + "=" * 80)
            print("Temporary pyproject.toml content (from subfolder pyproject.toml):")
            print("=" * 80)
            print(adjusted_content)
            print("=" * 80 + "\n")

            # If original pyproject.toml exists, temporarily move it
            if original_pyproject.exists():
                backup_path = self.project_root / "pyproject.toml.original"
                # Remove backup if it already exists (from previous failed test or run)
                if backup_path.exists():
                    backup_path.unlink()
                original_pyproject.rename(backup_path)
                self.original_pyproject_backup = backup_path

            # Move temp file to pyproject.toml for the build
            temp_pyproject_path.rename(original_pyproject)
            self.temp_pyproject = original_pyproject

            # Handle README file
            self._handle_readme()

            return original_pyproject

        # No pyproject.toml in subfolder, create one from parent
        self._used_subfolder_pyproject = False
        print("No pyproject.toml found in subfolder, creating temporary one from parent")

        # Read the original pyproject.toml
        original_pyproject = self.project_root / "pyproject.toml"
        if not original_pyproject.exists():
            # If no parent pyproject.toml exists, we can't create a temporary one
            # This is acceptable for tests or cases where only dependency copying is needed
            print(
                f"Warning: No pyproject.toml found in project root ({original_pyproject}). "
                "Skipping subfolder build configuration. Only dependency copying will be performed.",
                file=sys.stderr,
            )
            # Still handle README file
            self._handle_readme()
            # Return None to indicate no pyproject.toml was created
            return None

        original_content = original_pyproject.read_text(encoding="utf-8")

        # Store reference to original
        self.original_pyproject_path = original_pyproject

        # Temporarily move original to backup location
        backup_path = self.project_root / "pyproject.toml.original"
        # Remove backup if it already exists (from previous failed test or run)
        if backup_path.exists():
            backup_path.unlink()
        original_pyproject.rename(backup_path)
        self.original_pyproject_backup = backup_path

        # Parse and modify the pyproject.toml
        if tomllib:
            try:
                data = tomllib.loads(original_content.encode())
            except Exception:
                # Fallback to string manipulation if parsing fails
                data = None
        else:
            data = None

        # Extract dependency group from parent if specified
        parent_dependency_group = None
        if data and self.dependency_group and "dependency-groups" in data:
            if self.dependency_group in data["dependency-groups"]:
                parent_dependency_group = {
                    self.dependency_group: data["dependency-groups"][self.dependency_group]
                }
            else:
                print(
                    f"Warning: Dependency group '{self.dependency_group}' not found in parent pyproject.toml",
                    file=sys.stderr,
                )

        if data:
            # Modify using parsed data
            if "project" in data:
                data["project"]["name"] = self.package_name
                if "version" in data["project"]:
                    data["project"]["version"] = self.version
                elif "dynamic" in data["project"]:
                    # Remove version from dynamic and set it
                    if "version" in data["project"]["dynamic"]:
                        data["project"]["dynamic"].remove("version")
                    data["project"]["version"] = self.version

            # Add dependency group if specified
            if parent_dependency_group:
                if "dependency-groups" not in data:
                    data["dependency-groups"] = {}
                # Add the specified dependency group from parent
                data["dependency-groups"].update(parent_dependency_group)

            # For now, use string manipulation (tomli-w not in stdlib)
            modified_content = self._modify_pyproject_string(
                original_content, parent_dependency_group
            )
        else:
            # Use string manipulation
            modified_content = self._modify_pyproject_string(
                original_content, parent_dependency_group
            )

        # Write the modified content to a temporary file
        temp_pyproject_path = self.project_root / "pyproject.toml.temp"
        temp_pyproject_path.write_text(modified_content, encoding="utf-8")

        # Print the temporary pyproject.toml content for debugging
        print("\n" + "=" * 80)
        print("Temporary pyproject.toml content (created from parent):")
        print("=" * 80)
        print(modified_content)
        print("=" * 80 + "\n")

        # Move temp file to pyproject.toml for the build
        temp_pyproject_path.rename(original_pyproject)
        self.temp_pyproject = original_pyproject

        # Handle README file
        self._handle_readme()

        return original_pyproject

    def _modify_pyproject_string(
        self, content: str, dependency_group: dict[str, list[str]] | None = None
    ) -> str:
        """Modify pyproject.toml content using string manipulation."""
        lines = content.split("\n")
        result = []
        in_project = False
        name_set = False
        version_set = False
        in_dynamic = False
        skip_hatch_version = False
        skip_uv_dynamic = False
        in_hatch_build = False
        packages_set = False
        build_system_set = False

        # Get package structure
        packages_path, package_dirs = self._get_package_structure()
        if not package_dirs:
            package_dirs = []

        for _i, line in enumerate(lines):
            # Skip build-system section - we'll add our own for subfolder builds
            if line.strip().startswith("[build-system]"):
                build_system_set = True
                continue  # Skip the [build-system] line
            elif build_system_set and line.strip().startswith("["):
                # End of build-system section
                build_system_set = False
                result.append(line)
                continue
            elif build_system_set:
                # Skip build-system content - we'll add our own
                continue

            # Skip hatch versioning and uv-dynamic-versioning sections
            if line.strip().startswith("[tool.hatch.version]"):
                skip_hatch_version = True
                continue
            elif line.strip().startswith("[tool.uv-dynamic-versioning]"):
                skip_uv_dynamic = True
                continue
            elif skip_hatch_version and line.strip().startswith("["):
                skip_hatch_version = False
            elif skip_uv_dynamic and line.strip().startswith("["):
                skip_uv_dynamic = False

            if skip_hatch_version or skip_uv_dynamic:
                continue

            # Handle hatch build targets
            if line.strip().startswith("[tool.hatch.build.targets.wheel]"):
                in_hatch_build = True
                result.append(line)
                continue
            elif line.strip().startswith("[") and in_hatch_build:
                # End of hatch build section, add packages if not set
                if not packages_set and package_dirs:
                    packages_str = ", ".join(f'"{p}"' for p in package_dirs)
                    result.append(f"packages = [{packages_str}]")
                in_hatch_build = False
                result.append(line)
            elif in_hatch_build:
                # Modify packages path
                if re.match(r"^\s*packages\s*=", line):
                    if package_dirs:
                        packages_str = ", ".join(f'"{p}"' for p in package_dirs)
                        result.append(f"packages = [{packages_str}]")
                    else:
                        result.append(line)
                    packages_set = True
                    continue
                # Keep other lines in hatch build section
                result.append(line)

            elif line.strip().startswith("[project]"):
                in_project = True
                result.append(line)
            elif line.strip().startswith("[") and in_project:
                # End of [project] section
                if not name_set:
                    result.append(f'name = "{self.package_name}"')
                if not version_set:
                    result.append(f'version = "{self.version}"')
                in_project = False
                result.append(line)
            elif in_project:
                # Modify name
                if re.match(r"^\s*name\s*=", line):
                    result.append(f'name = "{self.package_name}"')
                    name_set = True
                    continue
                # Modify version
                elif re.match(r"^\s*version\s*=", line):
                    result.append(f'version = "{self.version}"')
                    version_set = True
                    continue
                # Remove version from dynamic
                elif re.match(r"^\s*dynamic\s*=\s*\[", line):
                    in_dynamic = True
                    # Remove "version" from the list
                    line = re.sub(r'"version"', "", line)
                    line = re.sub(r"'version'", "", line)
                    line = re.sub(r",\s*,", ",", line)
                    line = re.sub(r"\[\s*,", "[", line)
                    line = re.sub(r",\s*\]", "]", line)
                    if re.match(r"^\s*dynamic\s*=\s*\[\s*\]", line):
                        continue  # Skip empty dynamic list
                elif in_dynamic and "]" in line:
                    in_dynamic = False
                    # Remove version from the closing bracket line if present
                    line = re.sub(r'"version"', "", line)
                    line = re.sub(r"'version'", "", line)

                result.append(line)
            else:
                result.append(line)

        # Add name and version if not set (still in project section)
        if in_project:
            if not name_set:
                result.append(f'name = "{self.package_name}"')
            if not version_set:
                result.append(f'version = "{self.version}"')

        # Add packages configuration if not set
        if in_hatch_build and not packages_set and package_dirs:
            packages_str = ", ".join(f'"{p}"' for p in package_dirs)
            result.append(f"packages = [{packages_str}]")

        # Ensure build-system section exists (required for hatchling)
        # Check if build-system section exists in the result
        has_build_system = any(line.strip().startswith("[build-system]") for line in result)
        if not has_build_system:
            # Insert build-system at the very beginning of the file
            build_system_lines = [
                "[build-system]",
                'requires = ["hatchling"]',
                'build-backend = "hatchling.build"',
                "",
            ]
            result = build_system_lines + result

        # Ensure packages is always set for subfolder builds
        if not packages_set and package_dirs:
            # Add the section if it doesn't exist
            if "[tool.hatch.build.targets.wheel]" not in "\n".join(result):
                result.append("")
                result.append("[tool.hatch.build.targets.wheel]")
            packages_str = ", ".join(f'"{p}"' for p in package_dirs)
            result.append(f"packages = [{packages_str}]")

        # Add file exclusion patterns to prevent including non-package files
        # This ensures only the subfolder code is included, not project root files
        result.append("")
        result.append("[tool.hatch.build]")
        result.append("paths-exclude = [")
        result.append('    ".cursor/**",')
        result.append('    ".github/**",')
        result.append('    ".vscode/**",')
        result.append('    ".idea/**",')
        result.append('    "data/**",')
        result.append('    "docs/**",')
        result.append('    "references/**",')
        result.append('    "reports/**",')
        result.append('    "scripts/**",')
        result.append('    "tests/**",')
        result.append('    "test/**",')
        result.append('    "dist/**",')
        result.append('    "build/**",')
        result.append('    "*.egg-info/**",')
        result.append('    "__pycache__/**",')
        result.append('    ".pytest_cache/**",')
        result.append('    ".mypy_cache/**",')
        result.append('    ".venv/**",')
        result.append('    "venv/**",')
        result.append('    ".git/**",')
        result.append('    ".gitignore",')
        result.append('    ".gitattributes",')
        result.append('    "Dockerfile",')
        result.append('    ".dockerignore",')
        result.append('    ".pylintrc",')
        result.append('    "pyrightconfig.json",')
        result.append('    "git-filter-repo",')
        result.append('    "pyproject.toml.original",')
        result.append('    "README.md.backup",')
        result.append("]")

        # Add dependency group if specified
        if dependency_group:
            # Find where to insert dependency-groups section
            # Usually after [project] section or at the end
            insert_index = len(result)
            for i, line in enumerate(result):
                if line.strip().startswith("[dependency-groups]"):
                    # Update existing dependency-groups section
                    insert_index = i
                    break
                elif line.strip().startswith("[") and i > 0:
                    # Insert before the last section (usually before [tool.*] sections)
                    if not line.strip().startswith("[tool."):
                        insert_index = i
                        break

            # Format dependency group
            if insert_index < len(result) and result[insert_index].strip().startswith(
                "[dependency-groups]"
            ):
                # Replace existing section
                dep_lines = ["[dependency-groups]"]
                for group_name, deps in dependency_group.items():
                    dep_lines.append(f"{group_name} = [")
                    for dep in deps:
                        dep_lines.append(f'    "{dep}",')
                    dep_lines.append("]")
                    dep_lines.append("")

                # Find end of existing dependency-groups section
                end_index = insert_index + 1
                while end_index < len(result) and not result[end_index].strip().startswith("["):
                    end_index += 1

                result[insert_index:end_index] = dep_lines
            else:
                # Insert new section
                dep_lines = ["", "[dependency-groups]"]
                for group_name, deps in dependency_group.items():
                    dep_lines.append(f"{group_name} = [")
                    for dep in deps:
                        dep_lines.append(f'    "{dep}",')
                    dep_lines.append("]")
                result[insert_index:insert_index] = dep_lines

        return "\n".join(result)

    def add_third_party_dependencies(self, dependencies: list[str]) -> None:
        """
        Add third-party dependencies to the temporary pyproject.toml.

        This method updates the pyproject.toml file that was created for the subfolder
        build by adding the specified dependencies to the [project.dependencies] section.

        Args:
            dependencies: List of third-party package names to add (e.g., ["pypdf", "requests"])
        """
        if not self.temp_pyproject or not self.temp_pyproject.exists():
            print(
                f"Warning: Cannot add third-party dependencies - pyproject.toml not found at {self.temp_pyproject}",
                file=sys.stderr,
            )
            return

        if not dependencies:
            return

        print(f"Adding third-party dependencies to pyproject.toml: {', '.join(dependencies)}")
        content = self.temp_pyproject.read_text(encoding="utf-8")
        updated_content = self._add_dependencies_to_pyproject(content, dependencies)
        self.temp_pyproject.write_text(updated_content, encoding="utf-8")

    def _normalize_package_name(self, package_name: str) -> str:
        """
        Normalize package name for PyPI.

        Converts underscores to hyphens, as PyPI package names typically use hyphens
        while Python import names use underscores (e.g., 'better_enum' -> 'better-enum').

        Args:
            package_name: Package name from import statement

        Returns:
            Normalized package name for PyPI
        """
        # Convert underscores to hyphens for PyPI package names
        # This handles the common case where import names use underscores
        # but PyPI package names use hyphens
        return package_name.replace("_", "-")

    def _add_dependencies_to_pyproject(self, content: str, dependencies: list[str]) -> str:
        """
        Add dependencies to pyproject.toml content.

        Adds the specified dependencies to the [project] section's dependencies list.
        If dependencies already exist, merges them. If no dependencies section exists,
        creates one. Package names are normalized (underscores -> hyphens) to match
        PyPI naming conventions.

        Args:
            content: Current pyproject.toml content
            dependencies: List of dependency names to add (will be normalized)

        Returns:
            Updated pyproject.toml content with dependencies added
        """
        if not dependencies:
            return content

        # Normalize package names (convert underscores to hyphens for PyPI)
        normalized_deps = [self._normalize_package_name(dep) for dep in dependencies]

        lines = content.split("\n")
        result = []
        in_project = False
        in_dependencies = False
        dependencies_added = False
        existing_deps: set[str] = set()

        # First pass: find existing dependencies
        for line in lines:
            if line.strip().startswith("[project]"):
                in_project = True
            elif line.strip().startswith("[") and in_project:
                in_project = False
            elif in_project and re.match(r"^\s*dependencies\s*=\s*\[", line):
                in_dependencies = True
            elif in_dependencies:
                # Extract existing dependency names
                dep_match = re.search(r'["\']([^"\']+)["\']', line)
                if dep_match:
                    existing_deps.add(dep_match.group(1))
                if line.strip().endswith("]"):
                    in_dependencies = False

        # Merge with new dependencies (normalized)
        all_deps = sorted(existing_deps | set(normalized_deps))

        # Second pass: build result with dependencies
        in_project = False
        in_dependencies = False
        for line in lines:
            if line.strip().startswith("[project]"):
                in_project = True
                result.append(line)
            elif line.strip().startswith("[") and in_project:
                # End of [project] section, add dependencies if not already present
                if not dependencies_added:
                    result.append("dependencies = [")
                    for dep in all_deps:
                        result.append(f'    "{dep}",')
                    result.append("]")
                    result.append("")
                in_project = False
                result.append(line)
            elif in_project and re.match(r"^\s*dependencies\s*=\s*\[", line):
                # Replace existing dependencies section
                result.append("dependencies = [")
                for dep in all_deps:
                    result.append(f'    "{dep}",')
                result.append("]")
                dependencies_added = True
                in_dependencies = True
            elif in_dependencies:
                # Skip lines in existing dependencies section (already replaced)
                if line.strip().endswith("]"):
                    in_dependencies = False
            else:
                result.append(line)

        # If [project] section exists but no dependencies were added, add them
        if in_project and not dependencies_added:
            result.append("dependencies = [")
            for dep in all_deps:
                result.append(f'    "{dep}",')
            result.append("]")
            result.append("")

        return "\n".join(result)

    def _handle_readme(self) -> None:
        """
        Handle README file for subfolder builds.

        - If README exists in subfolder, copy it to project root
        - If no README exists, create a minimal one with folder name
        - Backup original README if it exists in project root
        """
        # Common README file names
        readme_names = ["README.md", "README.rst", "README.txt", "README"]

        # Check for README in subfolder
        subfolder_readme = None
        for name in readme_names:
            readme_path = self.src_dir / name
            if readme_path.exists():
                subfolder_readme = readme_path
                break

        # Check for existing README in project root
        project_readme = None
        for name in readme_names:
            readme_path = self.project_root / name
            if readme_path.exists():
                project_readme = readme_path
                break

        # Backup original README if it exists
        if project_readme:
            backup_path = self.project_root / f"{project_readme.name}.backup"
            shutil.copy2(project_readme, backup_path)
            self.original_readme_backup = backup_path

        # Use subfolder README if it exists
        if subfolder_readme:
            # Copy subfolder README to project root
            target_readme = self.project_root / subfolder_readme.name
            shutil.copy2(subfolder_readme, target_readme)
            self.temp_readme = target_readme
        else:
            # Create minimal README with folder name
            readme_content = f"# {self.src_dir.name}\n"
            target_readme = self.project_root / "README.md"
            target_readme.write_text(readme_content, encoding="utf-8")
            self.temp_readme = target_readme

    def restore(self) -> None:
        """
        Restore the original pyproject.toml and remove temporary __init__.py if created.

        The root pyproject.toml is never modified during subfolder builds. Instead, it is
        temporarily moved to pyproject.toml.original and then restored after the build.
        This method removes the temporary pyproject.toml and restores the original from
        the backup location, ensuring the original file is never modified.
        """
        # Remove temporary __init__.py if we created it
        if self._temp_init_created:
            init_file = self.src_dir / "__init__.py"
            if init_file.exists():
                try:
                    init_file.unlink()
                except Exception:
                    pass  # Ignore errors during cleanup
            self._temp_init_created = False

        # Restore original README if it was backed up
        backup_path = self.original_readme_backup
        had_backup = backup_path and backup_path.exists()
        original_readme_path = None
        if had_backup:
            original_readme_name = backup_path.stem  # Get name without .backup extension
            original_readme_path = self.project_root / original_readme_name
            shutil.copy2(backup_path, original_readme_path)
            backup_path.unlink()
            self.original_readme_backup = None

        # Remove temporary README if we created it or copied from subfolder
        # Only remove if it's different from the original we just restored
        if self.temp_readme and self.temp_readme.exists():
            # If we restored an original README and the temp is the same file, don't remove it
            if (
                had_backup
                and original_readme_path
                and self.temp_readme.samefile(original_readme_path)
            ):
                # Temp README is the same as the restored original, so don't remove it
                pass
            else:
                # Remove the temp README (either no original existed, or it's a different file)
                try:
                    self.temp_readme.unlink()
                except Exception:
                    pass  # Ignore errors during cleanup
            self.temp_readme = None

        # Restore original pyproject.toml (only if we created/used one)
        if self.temp_pyproject and self.original_pyproject_path:
            original_pyproject = self.original_pyproject_path

            # Remove the temporary pyproject.toml we created
            if original_pyproject.exists():
                try:
                    original_pyproject.unlink()
                except Exception as e:
                    print(
                        f"Warning: Could not remove temporary pyproject.toml: {e}",
                        file=sys.stderr,
                    )

            # Restore the original pyproject.toml from backup if it existed
            if self.original_pyproject_backup and self.original_pyproject_backup.exists():
                self.original_pyproject_backup.rename(original_pyproject)
                self.original_pyproject_backup = None

            self.temp_pyproject = None
            self.original_pyproject_path = None
            self._used_subfolder_pyproject = False

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ARG002
        """Context manager exit - always restore."""
        self.restore()
