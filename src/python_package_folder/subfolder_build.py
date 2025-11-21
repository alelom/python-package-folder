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

    When building a subfolder as a separate package, this class creates
    a temporary pyproject.toml with the appropriate package name and version.
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
            package_name: Name for the subfolder package (default: derived from src_dir name)
            version: Version for the subfolder package (required if building subfolder)
            dependency_group: Name of dependency group to copy from parent pyproject.toml
        """
        self.project_root = project_root.resolve()
        self.src_dir = src_dir.resolve()
        self.package_name = package_name or self._derive_package_name()
        self.version = version
        self.dependency_group = dependency_group
        self.temp_pyproject: Path | None = None
        self.original_pyproject_backup: Path | None = None
        self._temp_init_created = False
        self.temp_readme: Path | None = None
        self.original_readme_backup: Path | None = None

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
            modified_content = self._modify_pyproject_string(original_content, parent_dependency_group)
        else:
            # Use string manipulation
            modified_content = self._modify_pyproject_string(original_content, parent_dependency_group)

        # Write the modified content
        original_pyproject.write_text(modified_content, encoding="utf-8")
        self.temp_pyproject = original_pyproject

        # Handle README file
        self._handle_readme()

        return original_pyproject

    def _modify_pyproject_string(self, content: str, dependency_group: dict[str, list[str]] | None = None) -> str:
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

        for _i, line in enumerate(lines):
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
            if insert_index < len(result) and result[insert_index].strip().startswith("[dependency-groups]"):
                # Replace existing section
                dep_lines = ["[dependency-groups]"]
                for group_name, deps in dependency_group.items():
                    dep_lines.append(f'{group_name} = [')
                    for dep in deps:
                        dep_lines.append(f'    "{dep}",')
                    dep_lines.append(']')
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
                    dep_lines.append(f'{group_name} = [')
                    for dep in deps:
                        dep_lines.append(f'    "{dep}",')
                    dep_lines.append(']')
                result[insert_index:insert_index] = dep_lines

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
            if had_backup and original_readme_path and self.temp_readme.samefile(original_readme_path):
                # Temp README is the same as the restored original, so don't remove it
                pass
            else:
                # Remove the temp README (either no original existed, or it's a different file)
                try:
                    self.temp_readme.unlink()
                except Exception:
                    pass  # Ignore errors during cleanup
            self.temp_readme = None
        
        # Restore original pyproject.toml
        if self.original_pyproject_backup and self.original_pyproject_backup.exists():
            original_pyproject = self.project_root / "pyproject.toml"
            shutil.copy2(self.original_pyproject_backup, original_pyproject)
            self.original_pyproject_backup.unlink()
            self.original_pyproject_backup = None
            self.temp_pyproject = None

    def __enter__(self) -> Self:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:  # noqa: ARG002
        """Context manager exit - always restore."""
        self.restore()

