"""
Subfolder build configuration management.

This module handles creating temporary build configurations for subfolders
that need to be built as separate packages with their own names and versions.
"""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

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

    When building a subfolder as a separate package, this class creates
    a temporary pyproject.toml with the appropriate package name and version.
    """

    def __init__(
        self,
        project_root: Path,
        src_dir: Path,
        package_name: str | None = None,
        version: str | None = None,
    ) -> None:
        """
        Initialize subfolder build configuration.

        Args:
            project_root: Root directory containing the main pyproject.toml
            src_dir: Source directory being built (subfolder)
            package_name: Name for the subfolder package (default: derived from src_dir name)
            version: Version for the subfolder package (required if building subfolder)
        """
        self.project_root = project_root.resolve()
        self.src_dir = src_dir.resolve()
        self.package_name = package_name or self._derive_package_name()
        self.version = version
        self.temp_pyproject: Path | None = None
        self.original_pyproject_backup: Path | None = None
        self._temp_init_created = False

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
        
        # Check for subdirectories that might be packages
        subdirs = [d for d in self.src_dir.iterdir() if d.is_dir() and not d.name.startswith(".")]
        
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

    def create_temp_pyproject(self) -> Path:
        """
        Create a temporary pyproject.toml for the subfolder build.

        This creates a pyproject.toml in the project root that overrides
        the package name and version for building the subfolder.

        Returns:
            Path to the temporary pyproject.toml file
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

        # Read the original pyproject.toml
        original_pyproject = self.project_root / "pyproject.toml"
        if not original_pyproject.exists():
            raise FileNotFoundError(f"pyproject.toml not found: {original_pyproject}")

        original_content = original_pyproject.read_text(encoding="utf-8")

        # Create a backup
        backup_path = self.project_root / "pyproject.toml.backup"
        shutil.copy2(original_pyproject, backup_path)
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

            # For now, use string manipulation (tomli-w not in stdlib)
            modified_content = self._modify_pyproject_string(original_content)
        else:
            # Use string manipulation
            modified_content = self._modify_pyproject_string(original_content)

        # Write the modified content
        original_pyproject.write_text(modified_content, encoding="utf-8")
        self.temp_pyproject = original_pyproject

        return original_pyproject

    def _modify_pyproject_string(self, content: str) -> str:
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

        # Get package structure
        packages_path, package_dirs = self._get_package_structure()
        if not package_dirs:
            package_dirs = []

        for i, line in enumerate(lines):
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
                if re.match(r'^\s*packages\s*=', line):
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
                if re.match(r'^\s*name\s*=', line):
                    result.append(f'name = "{self.package_name}"')
                    name_set = True
                    continue
                # Modify version
                elif re.match(r'^\s*version\s*=', line):
                    result.append(f'version = "{self.version}"')
                    version_set = True
                    continue
                # Remove version from dynamic
                elif re.match(r'^\s*dynamic\s*=\s*\[', line):
                    in_dynamic = True
                    # Remove "version" from the list
                    line = re.sub(r'"version"', "", line)
                    line = re.sub(r"'version'", "", line)
                    line = re.sub(r",\s*,", ",", line)
                    line = re.sub(r"\[\s*,", "[", line)
                    line = re.sub(r",\s*\]", "]", line)
                    if re.match(r'^\s*dynamic\s*=\s*\[\s*\]', line):
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
        
        # Ensure packages is always set for subfolder builds
        if not packages_set and package_dirs:
            # Add the section if it doesn't exist
            if "[tool.hatch.build.targets.wheel]" not in "\n".join(result):
                result.append("")
                result.append("[tool.hatch.build.targets.wheel]")
            packages_str = ", ".join(f'"{p}"' for p in package_dirs)
            result.append(f"packages = [{packages_str}]")

        return "\n".join(result)

    def restore(self) -> None:
        """Restore the original pyproject.toml and remove temporary __init__.py if created."""
        # Remove temporary __init__.py if we created it
        if self._temp_init_created:
            init_file = self.src_dir / "__init__.py"
            if init_file.exists():
                try:
                    init_file.unlink()
                except Exception:
                    pass  # Ignore errors during cleanup
            self._temp_init_created = False
        
        # Restore original pyproject.toml
        if self.original_pyproject_backup and self.original_pyproject_backup.exists():
            original_pyproject = self.project_root / "pyproject.toml"
            shutil.copy2(self.original_pyproject_backup, original_pyproject)
            self.original_pyproject_backup.unlink()
            self.original_pyproject_backup = None
            self.temp_pyproject = None

    def __enter__(self) -> "SubfolderBuildConfig":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - always restore."""
        self.restore()

