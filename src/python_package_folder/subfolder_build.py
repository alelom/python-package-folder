"""
Subfolder build configuration management.

This module handles creating temporary build configurations for subfolders
that need to be built as separate packages with their own names and versions.
"""

from __future__ import annotations

import re
import shutil
import sys
import tempfile
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

from .utils import read_exclude_patterns


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
        self._excluded_files: list[tuple[Path, Path]] = []  # List of (original_path, temp_path) tuples
        self._exclude_temp_dir: Path | None = None
        self._temp_package_dir: Path | None = None
        self._has_existing_dependencies = False  # Track if subfolder toml has dependencies

    def _derive_package_name(self) -> str:
        """
        Derive package name from root project name and source directory name.
        
        Format: {root_project_name}-{subfolder_name}
        Falls back to just subfolder_name if root project name not found.
        """
        # Get root project name from pyproject.toml
        root_project_name = None
        pyproject_path = self.project_root / "pyproject.toml"
        if pyproject_path.exists():
            try:
                if tomllib:
                    with open(pyproject_path, "rb") as f:
                        data = tomllib.load(f)
                        root_project_name = data.get("project", {}).get("name")
                else:
                    # Fallback: simple string parsing
                    content = pyproject_path.read_text(encoding="utf-8")
                    for line in content.split("\n"):
                        if line.strip().startswith("name ="):
                            root_project_name = line.split("=", 1)[1].strip().strip('"').strip("'")
                            break
            except Exception:
                pass
        
        # Use the directory name, replacing invalid characters
        subfolder_name = self.src_dir.name
        # Replace invalid characters with hyphens
        subfolder_name = subfolder_name.replace("_", "-").replace(" ", "-").lower()
        # Remove any leading/trailing hyphens
        subfolder_name = subfolder_name.strip("-")
        
        # Combine with root project name if available
        if root_project_name:
            # Normalize root project name (replace underscores/hyphens consistently)
            root_name_normalized = root_project_name.replace("_", "-").lower()
            return f"{root_name_normalized}-{subfolder_name}"
        else:
            # Fallback to just subfolder name
            return subfolder_name

    def _create_temp_package_directory(self) -> None:
        """
        Create a temporary package directory with the correct import name.
        
        This ensures the installed package has the correct directory structure.
        The package name (with hyphens) is converted to the import name (with underscores).
        For example: 'ml-drawing-assistant-data' -> 'ml_drawing_assistant_data'
        
        The temporary directory is created in the project root with the import name directly.
        This way, hatchling will install it with the correct name without needing force-include.
        """
        if not self.package_name:
            print("DEBUG: No package_name provided, skipping temp package directory creation", file=sys.stderr)
            return
        
        # Convert package name (with hyphens) to import name (with underscores)
        # PyPI package names use hyphens, but Python import names use underscores
        import_name = self.package_name.replace("-", "_")
        
        # Create temporary directory with the import name directly
        # This way, hatchling will install it with the correct name
        import_name_dir = self.project_root / import_name
        
        print(
            f"DEBUG: Creating temporary package directory: {import_name_dir} "
            f"(from src_dir: {self.src_dir}, import name: {import_name})",
            file=sys.stderr,
        )
        
        # Check if the directory already exists and is the correct one
        if import_name_dir.exists() and import_name_dir == self._temp_package_dir:
            # Directory already exists and is the correct one, no need to recreate
            print(f"DEBUG: Temporary package directory already exists: {import_name_dir}", file=sys.stderr)
            return
        
        # Remove if it already exists (from a previous build)
        if import_name_dir.exists():
            print(f"DEBUG: Removing existing temporary package directory: {import_name_dir}", file=sys.stderr)
            shutil.rmtree(import_name_dir)
        
        # Copy the entire source directory contents directly to the import name directory
        # Check if src_dir exists and is a directory before copying
        if not self.src_dir.exists():
            print(
                f"Warning: Source directory does not exist: {self.src_dir}",
                file=sys.stderr,
            )
            self._temp_package_dir = None
            return
        
        if not self.src_dir.is_dir():
            print(
                f"Warning: Source path is not a directory: {self.src_dir}",
                file=sys.stderr,
            )
            self._temp_package_dir = None
            return
        
        # Get exclude patterns from parent pyproject.toml
        exclude_patterns = []
        original_pyproject = self.project_root / "pyproject.toml"
        if original_pyproject.exists():
            exclude_patterns = read_exclude_patterns(original_pyproject)
            print(
                f"DEBUG: Using exclude patterns for temp directory copy: {exclude_patterns}",
                file=sys.stderr,
            )
        
        # Check if src_dir has any files before copying
        src_files = list(self.src_dir.rglob("*"))
        src_files = [f for f in src_files if f.is_file()]
        print(
            f"DEBUG: Source directory {self.src_dir} contains {len(src_files)} files before copy",
            file=sys.stderr,
        )
        
        # Use a copy method that respects exclude patterns and handles missing directories
        try:
            print(f"DEBUG: Starting copy from {self.src_dir} to {import_name_dir}", file=sys.stderr)
            self._copytree_excluding_patterns(self.src_dir, import_name_dir, exclude_patterns)
            self._temp_package_dir = import_name_dir
            
            # Verify files were copied
            copied_files = list(import_name_dir.rglob("*"))
            copied_files = [f for f in copied_files if f.is_file()]
            print(
                f"DEBUG: After copy, temp directory {import_name_dir} contains {len(copied_files)} files",
                file=sys.stderr,
            )
            
            print(
                f"Created temporary package directory: {import_name_dir} "
                f"(import name: {import_name})"
            )
        except Exception as e:
            print(
                f"Warning: Could not create temporary package directory: {e}",
                file=sys.stderr,
            )
            import traceback
            print(f"DEBUG: Traceback: {traceback.format_exc()}", file=sys.stderr)
            # Fall back to using src_dir directly
            self._temp_package_dir = None
    
    def _copytree_excluding_patterns(self, src: Path, dst: Path, exclude_patterns: list[str]) -> None:
        """
        Copy a directory tree, excluding certain patterns and handling missing directories gracefully.
        
        This is similar to BuildManager._copytree_excluding but works without needing
        the BuildManager instance. It respects exclude patterns and skips missing directories
        (e.g., broken symlinks or already-excluded directories).
        
        Args:
            src: Source directory
            dst: Destination directory
            exclude_patterns: List of patterns to exclude (e.g., ['_SS', '__SS', '.*_test.*'])
        """
        default_patterns = [
            "_SS",
            "__SS",
            "_sandbox",
            "__sandbox",
            "_skip",
            "__skip",
            "_test",
            "__test__",
        ]
        all_exclude_patterns = default_patterns + exclude_patterns
        
        def should_exclude(path: Path) -> bool:
            """Check if a path should be excluded."""
            import re
            # Only check parts of the path relative to src_dir, not the entire absolute path
            # This prevents matching test directory names or other parts outside the source
            try:
                rel_path = path.relative_to(src)
                # Check each component of the relative path
                for part in rel_path.parts:
                    # Check if any part matches an exclusion pattern
                    for pattern in all_exclude_patterns:
                        # Determine if pattern is a regex (contains regex special characters)
                        is_regex = any(c in pattern for c in ['.', '*', '+', '?', '^', '$', '[', ']', '(', ')', '{', '}', '|', '\\'])
                        
                        if is_regex:
                            # Use regex matching for patterns like '.*_test.*'
                            try:
                                if re.search(pattern, part):
                                    print(f"DEBUG: Excluding {path} (part '{part}' matches regex pattern '{pattern}')", file=sys.stderr)
                                    return True
                            except re.error:
                                # Invalid regex, fall back to simple string matching
                                if part == pattern or part.startswith(pattern):
                                    print(f"DEBUG: Excluding {path} (part '{part}' matches pattern '{pattern}')", file=sys.stderr)
                                    return True
                        else:
                            # Simple string matching for patterns like '_SS'
                            if part == pattern or part.startswith(pattern):
                                print(f"DEBUG: Excluding {path} (part '{part}' matches pattern '{pattern}')", file=sys.stderr)
                                return True
            except ValueError:
                # Path is not relative to src, check the name only
                for pattern in all_exclude_patterns:
                    is_regex = any(c in pattern for c in ['.', '*', '+', '?', '^', '$', '[', ']', '(', ')', '{', '}', '|', '\\'])
                    if is_regex:
                        try:
                            if re.search(pattern, path.name):
                                return True
                        except re.error:
                            if path.name == pattern or path.name.startswith(pattern):
                                return True
                    else:
                        if path.name == pattern or path.name.startswith(pattern):
                            return True
            return False
        
        # Create destination directory
        dst.mkdir(parents=True, exist_ok=True)
        
        # Copy files and subdirectories, excluding patterns
        copied_count = 0
        excluded_count = 0
        skipped_count = 0
        try:
            items = list(src.iterdir())
            print(f"DEBUG: Copying from {src} to {dst}, found {len(items)} items", file=sys.stderr)
            for item in items:
                if should_exclude(item):
                    print(f"DEBUG: Excluding {item} from temp package directory copy", file=sys.stderr)
                    excluded_count += 1
                    continue
                
                src_item = src / item.name
                dst_item = dst / item.name
                
                # Skip if source doesn't exist (broken symlink, already deleted, etc.)
                if not src_item.exists():
                    print(
                        f"DEBUG: Skipping non-existent item: {src_item}",
                        file=sys.stderr,
                    )
                    skipped_count += 1
                    continue
                
                if src_item.is_file():
                    try:
                        shutil.copy2(src_item, dst_item)
                        copied_count += 1
                        print(f"DEBUG: Copied file {src_item} -> {dst_item}", file=sys.stderr)
                    except (OSError, IOError) as e:
                        print(
                            f"DEBUG: Could not copy file {src_item}: {e}, skipping",
                            file=sys.stderr,
                        )
                        skipped_count += 1
                        continue
                elif src_item.is_dir():
                    try:
                        self._copytree_excluding_patterns(src_item, dst_item, exclude_patterns)
                        copied_count += 1
                        print(f"DEBUG: Copied directory {src_item} -> {dst_item}", file=sys.stderr)
                    except (OSError, IOError) as e:
                        print(
                            f"DEBUG: Could not copy directory {src_item}: {e}, skipping",
                            file=sys.stderr,
                        )
                        skipped_count += 1
                        continue
            print(
                f"DEBUG: Copy summary: {copied_count} items copied, {excluded_count} excluded, {skipped_count} skipped",
                file=sys.stderr,
            )
        except (OSError, IOError) as e:
            # If we can't even iterate the source directory, that's a problem
            raise RuntimeError(f"Cannot iterate source directory {src}: {e}") from e

    def _get_package_structure(self) -> tuple[str, list[str]]:
        """
        Determine the package structure for hatchling.

        Returns:
            Tuple of (packages_path, package_dirs) where:
            - packages_path: The path to the directory containing packages
            - package_dirs: List of package directories to include
        """
        # Use temporary package directory if it exists, otherwise use src_dir
        package_dir = self._temp_package_dir if self._temp_package_dir and self._temp_package_dir.exists() else self.src_dir
        
        print(
            f"DEBUG: _get_package_structure: temp_package_dir={self._temp_package_dir}, "
            f"exists={self._temp_package_dir.exists() if self._temp_package_dir else False}, "
            f"using package_dir={package_dir}",
            file=sys.stderr,
        )
        
        # Check if package_dir itself is a package (has __init__.py)
        has_init = (package_dir / "__init__.py").exists()

        # Check for Python files directly in package_dir
        py_files = list(package_dir.glob("*.py"))
        has_py_files = bool(py_files)

        # Calculate relative path from project root
        try:
            rel_path = package_dir.relative_to(self.project_root)
            packages_path = str(rel_path).replace("\\", "/")
        except ValueError:
            packages_path = None
            print(
                f"DEBUG: Could not calculate relative path from {self.project_root} to {package_dir}",
                file=sys.stderr,
            )

        print(
            f"DEBUG: _get_package_structure returning: packages_path={packages_path}, "
            f"has_init={has_init}, has_py_files={has_py_files}",
            file=sys.stderr,
        )

        # If package_dir has Python files but no __init__.py, we need to make it a package
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
        in_sdist_section = False
        packages_set = False
        only_include_set = False

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
            elif line.strip().startswith("[tool.hatch.build.targets.sdist]"):
                in_sdist_section = True
                result.append(line)
                continue
            elif line.strip().startswith("[") and in_sdist_section:
                # End of sdist section
                in_sdist_section = False
                result.append(line)
            elif in_sdist_section:
                # Replace only-include path if it exists
                if re.match(r"^\s*only-include\s*=", line):
                    only_include_set = True
                    # Replace with correct path
                    only_include_paths = [correct_packages_path]
                    only_include_paths.append("pyproject.toml")
                    only_include_paths.append("README.md")
                    only_include_paths.append("README.rst")
                    only_include_paths.append("README.txt")
                    only_include_paths.append("README")
                    only_include_str = ", ".join(f'"{p}"' for p in only_include_paths)
                    result.append(f"only-include = [{only_include_str}]")
                    continue
                result.append(line)
            elif in_hatch_build_section:
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

        # Use only-include for source distributions to ensure only the subfolder is included
        # This prevents including files from the project root
        # Only add sdist section if it doesn't already exist and only-include wasn't set
        if correct_packages_path:
            # Check if sdist section already exists in result
            sdist_section_exists = any(
                line.strip().startswith("[tool.hatch.build.targets.sdist]")
                for line in result
            )
            # Only add section and only-include if they don't already exist
            if not sdist_section_exists and not only_include_set:
                result.append("")
                result.append("[tool.hatch.build.targets.sdist]")
                # Include only the subfolder directory and necessary files
                only_include_paths = [correct_packages_path]
                # Also include pyproject.toml and README if they exist
                only_include_paths.append("pyproject.toml")
                only_include_paths.append("README.md")
                only_include_paths.append("README.rst")
                only_include_paths.append("README.txt")
                only_include_paths.append("README")
                only_include_str = ", ".join(f'"{p}"' for p in only_include_paths)
                result.append(f"only-include = [{only_include_str}]")

        return "\n".join(result)

    def _update_version_in_pyproject(self, content: str) -> str:
        """
        Update the version in pyproject.toml content to match self.version.
        
        Also checks if version differs and warns the user.
        
        Args:
            content: Content of pyproject.toml
            
        Returns:
            Content with updated version
        """
        if not self.version:
            return content
        
        lines = content.split("\n")
        result = []
        in_project_section = False
        version_set = False
        existing_version = None
        
        for line in lines:
            # Detect [project] section
            if line.strip() == "[project]":
                in_project_section = True
                result.append(line)
                continue
            elif line.strip().startswith("[") and in_project_section:
                # End of [project] section - add version if not set
                if not version_set:
                    result.append(f'version = "{self.version}"')
                    version_set = True
                in_project_section = False
                result.append(line)
            elif in_project_section:
                # Check if this is a version line
                version_match = re.match(r'^\s*version\s*=\s*["\']([^"\']+)["\']', line)
                if version_match:
                    existing_version = version_match.group(1)
                    result.append(f'version = "{self.version}"')
                    version_set = True
                    continue  # Skip the original version line
                else:
                    result.append(line)
            else:
                result.append(line)
        
        # If we never found [project] section or version wasn't set, add it
        if not version_set:
            # Try to find where to insert it - after [project] if it exists
            if "[project]" in content:
                # Insert after [project] line
                new_lines = []
                inserted = False
                for i, line in enumerate(lines):
                    new_lines.append(line)
                    if line.strip() == "[project]" and not inserted:
                        # Insert version right after [project]
                        new_lines.append(f'version = "{self.version}"')
                        inserted = True
                result = new_lines
            else:
                # No [project] section, add it at the beginning
                result.insert(0, "[project]")
                result.insert(1, f'version = "{self.version}"')
        
        # Warn if version differs
        if existing_version and existing_version != self.version:
            print(
                f"\nWarning: Version mismatch in subfolder pyproject.toml",
                file=sys.stderr,
            )
            print(
                f"  - Version in file: {existing_version}",
                file=sys.stderr,
            )
            print(
                f"  - Derived version: {self.version} (from conventional commits/CLI)",
                file=sys.stderr,
            )
            print(
                f"  - Using derived version: {self.version}",
                file=sys.stderr,
            )
            print(
                f"  - The version in the subfolder's pyproject.toml will be updated for this build.\n",
                file=sys.stderr,
            )
        
        return "\n".join(result)

    def _check_and_warn_about_dependencies(self, content: str) -> bool:
        """
        Check if subfolder pyproject.toml has a non-empty dependencies field.
        
        Args:
            content: Content of pyproject.toml
            
        Returns:
            True if dependencies field exists and is non-empty, False otherwise
        """
        if not tomllib:
            # Fallback: simple regex check
            # Look for dependencies = [...] pattern
            deps_match = re.search(r'^\s*dependencies\s*=\s*\[', content, re.MULTILINE)
            if deps_match:
                # Try to find if there are any dependencies in the list
                # This is a simple heuristic - look for non-empty content between [ and ]
                lines = content.split("\n")
                in_project = False
                in_dependencies = False
                dependency_count = 0
                
                for line in lines:
                    if line.strip() == "[project]":
                        in_project = True
                    elif line.strip().startswith("[") and in_project:
                        in_project = False
                    elif in_project and re.match(r"^\s*dependencies\s*=\s*\[", line):
                        in_dependencies = True
                        # Check if line has content after [
                        if "]" not in line:
                            # Multi-line dependencies
                            continue
                        else:
                            # Single line: dependencies = ["pkg1", "pkg2"]
                            deps_str = line.split("[", 1)[1].rsplit("]", 1)[0]
                            if deps_str.strip():
                                return True
                            return False
                    elif in_dependencies:
                        # Check if this line has a dependency (not just whitespace or closing bracket)
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#") and stripped != "]":
                            # Check if it looks like a dependency string
                            if re.search(r'["\'][^"\']+["\']', stripped):
                                dependency_count += 1
                        if "]" in line:
                            return dependency_count > 0
                
                return dependency_count > 0
            return False
        
        # Use tomllib for more accurate parsing
        try:
            data = tomllib.loads(content.encode())
            project = data.get("project", {})
            dependencies = project.get("dependencies", [])
            
            # Check if dependencies list is non-empty
            if dependencies and len(dependencies) > 0:
                return True
            return False
        except Exception:
            # If parsing fails, fall back to regex-based check
            # Look for dependencies = [...] pattern
            deps_match = re.search(r'^\s*dependencies\s*=\s*\[', content, re.MULTILINE)
            if deps_match:
                # Try to find if there are any dependencies in the list
                lines = content.split("\n")
                in_project = False
                in_dependencies = False
                dependency_count = 0
                
                for line in lines:
                    if line.strip() == "[project]":
                        in_project = True
                    elif line.strip().startswith("[") and in_project:
                        in_project = False
                    elif in_project and re.match(r"^\s*dependencies\s*=\s*\[", line):
                        in_dependencies = True
                        # Check if line has content after [
                        if "]" not in line:
                            # Multi-line dependencies
                            continue
                        else:
                            # Single line: dependencies = ["pkg1", "pkg2"]
                            deps_str = line.split("[", 1)[1].rsplit("]", 1)[0]
                            if deps_str.strip():
                                return True
                            return False
                    elif in_dependencies:
                        # Check if this line has a dependency (not just whitespace or closing bracket)
                        stripped = line.strip()
                        if stripped and not stripped.startswith("#") and stripped != "]":
                            # Check if it looks like a dependency string
                            if re.search(r'["\'][^"\']+["\']', stripped):
                                dependency_count += 1
                        if "]" in line:
                            return dependency_count > 0
                
                return dependency_count > 0
            return False

    def _check_and_warn_about_name(self, content: str) -> str | None:
        """
        Check if subfolder pyproject.toml has a name field and warn if it differs from derived.
        
        Args:
            content: Content of pyproject.toml
            
        Returns:
            Name from subfolder toml if found, None otherwise
        """
        if not tomllib:
            # Fallback: simple regex check
            name_match = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if name_match:
                return name_match.group(1)
            return None
        
        # Use tomllib for more accurate parsing
        try:
            data = tomllib.loads(content.encode())
            project = data.get("project", {})
            name = project.get("name")
            return name
        except Exception:
            # If parsing fails, fall back to regex
            name_match = re.search(r'^\s*name\s*=\s*["\']([^"\']+)["\']', content, re.MULTILINE)
            if name_match:
                return name_match.group(1)
            return None

    def _merge_from_parent_pyproject(self, subfolder_content: str, parent_content: str) -> str:
        """
        Merge missing fields from parent pyproject.toml into subfolder content.
        
        Priority: subfolder > parent (only fill missing fields from parent)
        
        This uses string manipulation to add missing fields since we don't have tomli-w
        for proper TOML round-trip. Only common fields are merged.
        
        Args:
            subfolder_content: Content of subfolder pyproject.toml
            parent_content: Content of parent pyproject.toml
            
        Returns:
            Merged content
        """
        if not tomllib:
            # If tomllib not available, return subfolder content as-is
            return subfolder_content
        
        try:
            subfolder_data = tomllib.loads(subfolder_content.encode())
            parent_data = tomllib.loads(parent_content.encode())
            
            # Fields to merge from parent if missing in subfolder
            fields_to_merge = [
                "description", "readme", "requires-python", "authors", 
                "keywords", "classifiers", "license", "urls"
            ]
            
            # Check what's missing and needs to be added
            missing_fields = []
            if "project" in parent_data and "project" in subfolder_data:
                parent_project = parent_data["project"]
                subfolder_project = subfolder_data["project"]
                
                for field in fields_to_merge:
                    if field not in subfolder_project and field in parent_project:
                        missing_fields.append((field, parent_project[field]))
            
            # If no missing fields, return as-is
            if not missing_fields:
                return subfolder_content
            
            # Add missing fields using string manipulation
            # Find [project] section and add fields after it
            lines = subfolder_content.split("\n")
            result = []
            in_project = False
            project_section_end = -1
            
            for i, line in enumerate(lines):
                if line.strip() == "[project]":
                    in_project = True
                    result.append(line)
                elif line.strip().startswith("[") and in_project:
                    # End of [project] section - insert missing fields here
                    project_section_end = i
                    in_project = False
                    # Add missing fields before the next section
                    for field_name, field_value in missing_fields:
                        if field_name == "urls" and isinstance(field_value, dict):
                            # Handle [project.urls] separately
                            continue
                        # Format the field value appropriately
                        formatted = self._format_toml_value(field_name, field_value)
                        if formatted:
                            result.append(formatted)
                    result.append(line)
                else:
                    result.append(line)
            
            # Handle [project.urls] separately if it exists in parent
            if "project" in parent_data and "urls" in parent_data["project"]:
                urls = parent_data["project"]["urls"]
                if isinstance(urls, dict) and "project.urls" not in subfolder_content:
                    # Add [project.urls] section at the end
                    result.append("")
                    result.append("[project.urls]")
                    for key, value in urls.items():
                        result.append(f'{key} = "{value}"')
            
            return "\n".join(result)
            
        except Exception as e:
            print(
                f"Warning: Could not merge from parent pyproject.toml: {e}. Using subfolder content as-is.",
                file=sys.stderr,
            )
            return subfolder_content
    
    def _format_toml_value(self, field_name: str, value: any) -> str | None:
        """
        Format a TOML field value as a string.
        
        Args:
            field_name: Name of the field
            value: Value to format
            
        Returns:
            Formatted string or None if cannot format
        """
        if value is None:
            return None
        
        if isinstance(value, str):
            return f'{field_name} = "{value}"'
        elif isinstance(value, list):
            if not value:
                return None
            # Format list items
            if isinstance(value[0], dict):
                # List of dicts (e.g., authors)
                items = []
                for item in value:
                    if isinstance(item, dict):
                        # Format as inline table: {name = "...", email = "..."}
                        parts = [f'{k} = "{v}"' for k, v in item.items() if v]
                        items.append("{" + ", ".join(parts) + "}")
                return f"{field_name} = [\n    " + ",\n    ".join(items) + "\n]"
            else:
                # List of strings
                items = [f'"{v}"' for v in value]
                return f"{field_name} = [\n    " + ",\n    ".join(items) + "\n]"
        elif isinstance(value, bool):
            return f"{field_name} = {str(value).lower()}"
        elif isinstance(value, (int, float)):
            return f"{field_name} = {value}"
        else:
            return None

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

        # Check if pyproject.toml exists in subfolder FIRST
        # This allows us to handle subfolder pyproject.toml even when parent doesn't exist
        # But first ensure src_dir exists
        if not self.src_dir.exists() or not self.src_dir.is_dir():
            # If src_dir doesn't exist, we can't proceed
            print(
                f"Warning: Source directory does not exist or is not a directory: {self.src_dir}",
                file=sys.stderr,
            )
            return None
        
        subfolder_pyproject = self.src_dir / "pyproject.toml"
        if subfolder_pyproject.exists() and subfolder_pyproject.is_file():
            # Read the subfolder pyproject.toml content IMMEDIATELY after checking it exists
            # This prevents any issues if the file is affected by subsequent operations
            try:
                subfolder_content = subfolder_pyproject.read_text(encoding="utf-8")
            except (FileNotFoundError, OSError) as e:
                # File was deleted or inaccessible between check and read
                print(
                    f"Warning: Could not read subfolder pyproject.toml at {subfolder_pyproject}: {e}. "
                    "Falling back to creating from parent.",
                    file=sys.stderr,
                )
                subfolder_content = None
            
            if subfolder_content is not None:
                # Ensure src_dir is a package (has __init__.py) before creating temp directory
                # This way the __init__.py will be copied to the temp directory
                init_file = self.src_dir / "__init__.py"
                if not init_file.exists():
                    # Create a temporary __init__.py to make it a package
                    init_file.write_text("# Temporary __init__.py for build\n", encoding="utf-8")
                    self._temp_init_created = True
                else:
                    self._temp_init_created = False

                # Create temporary package directory with correct import name
                # This will copy the __init__.py we just created (if any)
                self._create_temp_package_directory()
                
                # Verify temporary package directory was created
                if not self._temp_package_dir or not self._temp_package_dir.exists():
                    print(
                        f"Warning: Temporary package directory was not created. "
                        f"Falling back to using src_dir: {self.src_dir}",
                        file=sys.stderr,
                    )
                
                # Determine which directory to use (temp package dir or src_dir)
                package_dir = self._temp_package_dir if self._temp_package_dir and self._temp_package_dir.exists() else self.src_dir
                # Use the subfolder's pyproject.toml
                print(f"Using existing pyproject.toml from subfolder: {subfolder_pyproject}")
                self._used_subfolder_pyproject = True

                # Store reference to original project root pyproject.toml
                original_pyproject = self.project_root / "pyproject.toml"
                self.original_pyproject_path = original_pyproject

                # Create temporary pyproject.toml file
                temp_pyproject_path = self.project_root / "pyproject.toml.temp"

                # Check for name mismatch and warn (but use subfolder name)
                subfolder_name = self._check_and_warn_about_name(subfolder_content)
                if subfolder_name and subfolder_name != self.package_name:
                    print(
                        f"\nWarning: Package name mismatch in subfolder pyproject.toml",
                        file=sys.stderr,
                    )
                    print(
                        f"  - Name in file: {subfolder_name}",
                        file=sys.stderr,
                    )
                    print(
                        f"  - Derived name: {self.package_name}",
                        file=sys.stderr,
                    )
                    print(
                        f"  - Using name from subfolder toml: {subfolder_name}\n",
                        file=sys.stderr,
                    )
                    # Update package_name to use subfolder's name
                    self.package_name = subfolder_name
                
                # Check for dependencies and warn if automatic detection will be skipped
                self._has_existing_dependencies = self._check_and_warn_about_dependencies(subfolder_content)
                if self._has_existing_dependencies:
                    print(
                        f"\nWarning: Subfolder pyproject.toml contains a non-empty 'dependencies' field.",
                        file=sys.stderr,
                    )
                    print(
                        f"  - Automatic dependency detection will be SKIPPED.",
                        file=sys.stderr,
                    )
                    print(
                        f"  - To enable automatic dependency detection, remove or empty the 'dependencies' field in the subfolder's pyproject.toml.\n",
                        file=sys.stderr,
                    )
                
                # Merge missing fields from parent pyproject.toml if it exists
                if original_pyproject.exists():
                    try:
                        parent_content = original_pyproject.read_text(encoding="utf-8")
                        subfolder_content = self._merge_from_parent_pyproject(subfolder_content, parent_content)
                    except Exception as e:
                        print(
                            f"Warning: Could not merge from parent pyproject.toml: {e}",
                            file=sys.stderr,
                        )
                
                # Adjust packages path to be relative to project root
                # This must be called AFTER _create_temp_package_directory() so _get_package_structure() 
                # can find the temporary directory
                adjusted_content = self._adjust_subfolder_pyproject_packages_path(subfolder_content)
                
                # Update version in subfolder pyproject.toml to match calculated version
                # This ensures the built package version matches what we're trying to publish
                adjusted_content = self._update_version_in_pyproject(adjusted_content)
                
                # Read exclude patterns from root pyproject.toml and inject them (if it exists)
                exclude_patterns = []
                if original_pyproject.exists():
                    exclude_patterns = read_exclude_patterns(original_pyproject)
                    print(
                        f"INFO: Read exclude patterns from {original_pyproject}: {exclude_patterns}",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"INFO: No parent pyproject.toml found at {original_pyproject}, skipping exclude patterns",
                        file=sys.stderr,
                    )
                if exclude_patterns:
                    adjusted_content = self._inject_exclude_patterns(adjusted_content, exclude_patterns)

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

                # Exclude files matching exclude patterns
                if exclude_patterns:
                    self._exclude_files_by_patterns(exclude_patterns)

                return original_pyproject

        # No pyproject.toml in subfolder, create one from parent
        self._used_subfolder_pyproject = False
        print("No pyproject.toml found in subfolder, creating temporary one from parent")

        # Ensure src_dir is a package (has __init__.py) before creating temp directory
        # This way the __init__.py will be copied to the temp directory
        init_file = self.src_dir / "__init__.py"
        if not init_file.exists():
            # Create a temporary __init__.py to make it a package
            init_file.write_text("# Temporary __init__.py for build\n", encoding="utf-8")
            self._temp_init_created = True
        else:
            self._temp_init_created = False

        # Create temporary package directory with correct import name
        # This will copy the __init__.py we just created (if any)
        self._create_temp_package_directory()
        
        # Log the result of temp directory creation
        if self._temp_package_dir and self._temp_package_dir.exists():
            py_files = list(self._temp_package_dir.glob("*.py"))
            print(
                f"DEBUG: Temp package directory created successfully: {self._temp_package_dir}, "
                f"contains {len(py_files)} Python files",
                file=sys.stderr,
            )
        else:
            print(
                f"WARNING: Temp package directory was NOT created. "
                f"Will fall back to using src_dir: {self.src_dir}",
                file=sys.stderr,
            )
        
        # Determine which directory to use (temp package dir or src_dir)
        package_dir = self._temp_package_dir if self._temp_package_dir and self._temp_package_dir.exists() else self.src_dir
        print(
            f"DEBUG: Using package_dir for build: {package_dir} "
            f"(temp_dir={self._temp_package_dir}, src_dir={self.src_dir})",
            file=sys.stderr,
        )

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

        # Read exclude patterns from root pyproject.toml BEFORE moving the file
        exclude_patterns = read_exclude_patterns(original_pyproject)
        print(
            f"INFO: Read exclude patterns from {original_pyproject}: {exclude_patterns}",
            file=sys.stderr,
        )

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
                # Log the package name being set
                import logging
                logger = logging.getLogger(__name__)
                logger.info(f"Setting package name in temporary pyproject.toml: '{self.package_name}'")
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
                original_content, parent_dependency_group, exclude_patterns
            )
        else:
            # Use string manipulation
            modified_content = self._modify_pyproject_string(
                original_content, parent_dependency_group, exclude_patterns
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

        # Exclude files matching exclude patterns
        if exclude_patterns:
            self._exclude_files_by_patterns(exclude_patterns)

        return original_pyproject

    def _modify_pyproject_string(
        self,
        content: str,
        dependency_group: dict[str, list[str]] | None = None,
        exclude_patterns: list[str] | None = None,
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

        # Log the package name being set via string manipulation
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"Setting package name in temporary pyproject.toml (string manipulation): '{self.package_name}'")

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

        # Use only-include for source distributions to ensure only the subfolder is included
        # This prevents including files from the project root
        if package_dirs:
            # Check if sdist section already exists
            sdist_section_exists = any(
                line.strip().startswith("[tool.hatch.build.targets.sdist]")
                for line in result
            )
            # Check if only-include is already set in the sdist section
            only_include_set = False
            if sdist_section_exists:
                in_sdist_section = False
                for line in result:
                    if line.strip().startswith("[tool.hatch.build.targets.sdist]"):
                        in_sdist_section = True
                    elif line.strip().startswith("[") and in_sdist_section:
                        in_sdist_section = False
                    elif in_sdist_section and re.match(r"^\s*only-include\s*=", line):
                        only_include_set = True
                        break

            if not sdist_section_exists or not only_include_set:
                if not sdist_section_exists:
                    result.append("")
                    result.append("[tool.hatch.build.targets.sdist]")
                # Include only the subfolder directory and necessary files
                only_include_paths = [package_dirs[0]]
                # Also include pyproject.toml and README if they exist
                only_include_paths.append("pyproject.toml")
                only_include_paths.append("README.md")
                only_include_paths.append("README.rst")
                only_include_paths.append("README.txt")
                only_include_paths.append("README")
                only_include_str = ", ".join(f'"{p}"' for p in only_include_paths)
                if not only_include_set:
                    result.append(f"only-include = [{only_include_str}]")

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

        # Add exclude patterns if specified
        if exclude_patterns:
            # Find where to insert [tool.python-package-folder] section
            # Usually after [dependency-groups] or at the end
            insert_index = len(result)
            tool_section_exists = False
            tool_section_start = -1
            tool_section_end = -1
            
            # First, search specifically for [tool.python-package-folder]
            for i, line in enumerate(result):
                if line.strip() == "[tool.python-package-folder]":
                    tool_section_exists = True
                    tool_section_start = i
                    # Find end of section (next [section] or end of file)
                    for j in range(i + 1, len(result)):
                        if result[j].strip().startswith("["):
                            tool_section_end = j
                            break
                    if tool_section_end == -1:
                        tool_section_end = len(result)
                    break
            
            # If not found, find a good insertion point before other [tool.*] sections
            if not tool_section_exists:
                for i, line in enumerate(result):
                    if line.strip().startswith("[tool.") and i > 0:
                        # Insert before other tool sections
                        insert_index = i
                        break

            # Format exclude patterns
            patterns_str = ", ".join(f'"{p}"' for p in exclude_patterns)

            if tool_section_exists:
                # Update existing section
                # Check if exclude-patterns already exists in the section
                has_exclude_patterns = False
                for i in range(tool_section_start + 1, tool_section_end):
                    if "exclude-patterns" in result[i]:
                        has_exclude_patterns = True
                        # Update the existing line
                        result[i] = f'exclude-patterns = [{patterns_str}]'
                        break
                
                if not has_exclude_patterns:
                    # Add exclude-patterns to existing section (before the next section)
                    result.insert(tool_section_end, f'exclude-patterns = [{patterns_str}]')
            else:
                # Insert new section
                exclude_lines = [
                    "",
                    "[tool.python-package-folder]",
                    f'exclude-patterns = [{patterns_str}]',
                ]
                result[insert_index:insert_index] = exclude_lines

        return "\n".join(result)

    def _inject_exclude_patterns(self, content: str, exclude_patterns: list[str]) -> str:
        """
        Inject exclude patterns into pyproject.toml content.

        Adds or updates [tool.python-package-folder] exclude-patterns section.

        Args:
            content: pyproject.toml content
            exclude_patterns: List of exclude patterns to inject

        Returns:
            Modified pyproject.toml content with exclude patterns
        """
        if not exclude_patterns:
            return content

        lines = content.split("\n")
        result = []
        tool_section_exists = False
        tool_section_index = -1
        tool_section_end = -1

        # Find [tool.python-package-folder] section
        for i, line in enumerate(lines):
            if line.strip() == "[tool.python-package-folder]":
                tool_section_exists = True
                tool_section_index = i
                # Find end of section
                for j in range(i + 1, len(lines)):
                    if lines[j].strip().startswith("["):
                        tool_section_end = j
                        break
                if tool_section_end == -1:
                    tool_section_end = len(lines)
                break

        if tool_section_exists:
            # Update existing section
            patterns_str = ", ".join(f'"{p}"' for p in exclude_patterns)
            has_exclude_patterns = False
            for i in range(tool_section_index + 1, tool_section_end):
                if "exclude-patterns" in lines[i]:
                    # Update existing line
                    lines[i] = f'exclude-patterns = [{patterns_str}]'
                    has_exclude_patterns = True
                    break
            if not has_exclude_patterns:
                # Add exclude-patterns to existing section
                lines.insert(tool_section_end, f'exclude-patterns = [{patterns_str}]')
            return "\n".join(lines)
        else:
            # Add new section at the end
            patterns_str = ", ".join(f'"{p}"' for p in exclude_patterns)
            lines.append("")
            lines.append("[tool.python-package-folder]")
            lines.append(f'exclude-patterns = [{patterns_str}]')
            return "\n".join(lines)

    def add_third_party_dependencies(self, dependencies: list[str]) -> None:
        """
        Add third-party dependencies to the temporary pyproject.toml.

        This method updates the pyproject.toml file that was created for the subfolder
        build by adding the specified dependencies to the [project.dependencies] section.

        Args:
            dependencies: List of third-party package names to add (e.g., ["pypdf", "requests"])
        """
        # Skip if subfolder toml already has dependencies
        if self._has_existing_dependencies:
            print(
                f"Skipping automatic dependency detection - subfolder pyproject.toml already has dependencies defined.",
                file=sys.stderr,
            )
            return
        
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

    def _exclude_files_by_patterns(self, exclude_patterns: list[str]) -> None:
        """
        Temporarily move files matching exclude patterns out of the source directory.

        Files are moved to a temporary directory and will be restored in restore().
        This ensures excluded files are not included in the build.

        Args:
            exclude_patterns: List of regex patterns to match against path components
        """
        print(f"INFO: Exclude patterns: {exclude_patterns}", file=sys.stderr)
        if not exclude_patterns:
            print("INFO: No exclude patterns to apply", file=sys.stderr)
            return

        # Compile regex patterns for efficiency
        compiled_patterns = [re.compile(pattern) for pattern in exclude_patterns]

        def should_exclude(path: Path) -> bool:
            """Check if a path should be excluded based on patterns."""
            # Check each component of the path
            for part in path.parts:
                # Check if any part matches any pattern
                for pattern in compiled_patterns:
                    if pattern.search(part):
                        return True
            return False

        # Create temporary directory for excluded files
        if self._exclude_temp_dir is None:
            self._exclude_temp_dir = Path(tempfile.mkdtemp(prefix="python-package-folder-excluded-"))

        # Find all files and directories in src_dir that match exclude patterns
        excluded_items: list[Path] = []
        
        # Walk through src_dir and find matching items
        # Sort by depth (shallow first) so we can skip children of excluded directories
        all_items = sorted(self.src_dir.rglob("*"), key=lambda p: len(p.parts))
        
        for item in all_items:
            # Skip if already excluded (parent was excluded)
            if any(
                excluded.is_dir() and (item == excluded or item.is_relative_to(excluded))
                for excluded in excluded_items
            ):
                continue
            
            # Check if this item should be excluded
            try:
                rel_path = item.relative_to(self.src_dir)
                if should_exclude(rel_path):
                    excluded_items.append(item)
            except ValueError:
                # Path is not relative to src_dir, skip
                continue

        # Move excluded items to temporary directory
        for item in excluded_items:
            try:
                # Calculate relative path from src_dir
                rel_path = item.relative_to(self.src_dir)
                # Create corresponding path in temp directory
                temp_path = self._exclude_temp_dir / rel_path
                # Create parent directories if needed
                temp_path.parent.mkdir(parents=True, exist_ok=True)
                
                # Move the item
                if item.exists():
                    shutil.move(str(item), str(temp_path))
                    self._excluded_files.append((item, temp_path))
                    print(f"Excluded {rel_path} from build", file=sys.stderr)
            except Exception as e:
                print(
                    f"Warning: Could not exclude {item}: {e}",
                    file=sys.stderr,
                )

    def _restore_excluded_files(self) -> None:
        """Restore files that were excluded by _exclude_files_by_patterns."""
        # Restore files in reverse order (to handle nested directories correctly)
        for original_path, temp_path in reversed(self._excluded_files):
            try:
                if temp_path.exists():
                    # Ensure parent directory exists
                    original_path.parent.mkdir(parents=True, exist_ok=True)
                    # Move back
                    shutil.move(str(temp_path), str(original_path))
            except Exception as e:
                print(
                    f"Warning: Could not restore excluded file {original_path}: {e}",
                    file=sys.stderr,
                )

        # Clean up temporary directory
        if self._exclude_temp_dir and self._exclude_temp_dir.exists():
            try:
                shutil.rmtree(self._exclude_temp_dir)
            except Exception as e:
                print(
                    f"Warning: Could not remove temporary exclude directory {self._exclude_temp_dir}: {e}",
                    file=sys.stderr,
                )

        self._excluded_files.clear()
        self._exclude_temp_dir = None

    def restore(self) -> None:
        """
        Restore the original pyproject.toml and remove temporary __init__.py if created.

        The root pyproject.toml is never modified during subfolder builds. Instead, it is
        temporarily moved to pyproject.toml.original and then restored after the build.
        This method removes the temporary pyproject.toml and restores the original from
        the backup location, ensuring the original file is never modified.
        """
        # Restore excluded files first
        self._restore_excluded_files()

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

        # Remove temporary package directory if it exists
        if self._temp_package_dir and self._temp_package_dir.exists():
            try:
                shutil.rmtree(self._temp_package_dir)
                print(f"Removed temporary package directory: {self._temp_package_dir}")
            except Exception as e:
                print(
                    f"Warning: Could not remove temporary package directory {self._temp_package_dir}: {e}",
                    file=sys.stderr,
                )
            self._temp_package_dir = None

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ARG002
        """Context manager exit - always restore."""
        self.restore()