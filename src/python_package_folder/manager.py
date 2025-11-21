"""
Build management functionality.

This module provides the BuildManager class which orchestrates the entire
build process: finding external dependencies, copying them temporarily,
running the build command, and cleaning up afterward.
"""

from __future__ import annotations

import shutil
import sys
from collections.abc import Callable
from pathlib import Path

try:
    import tomllib
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None

from .analyzer import ImportAnalyzer
from .finder import ExternalDependencyFinder
from .subfolder_build import SubfolderBuildConfig
from .types import ExternalDependency, ImportInfo


class BuildManager:
    """
    Manages the build process with external dependency handling.

    This is the main class for using the package. It coordinates finding
    external dependencies, copying them into the source directory, running
    the build, and cleaning up.

    Attributes:
        project_root: Root directory of the project
        src_dir: Source directory containing the package code
        copied_files: List of file paths that were copied (for cleanup)
        copied_dirs: List of directory paths that were copied (for cleanup)
    """

    def __init__(self, project_root: Path, src_dir: Path | None = None) -> None:
        """
        Initialize the build manager.

        Args:
            project_root: Root directory of the project
            src_dir: Source directory (defaults to project_root/src, or current dir if it has Python files)

        Raises:
            ValueError: If the source directory does not exist or is invalid
        """
        from .utils import find_source_directory

        self.project_root = project_root.resolve()

        # If src_dir not provided, try to find it intelligently
        if src_dir is None:
            src_dir = find_source_directory(self.project_root)
            if src_dir is None:
                # Fallback to standard src/ directory
                src_dir = self.project_root / "src"

        self.src_dir = Path(src_dir).resolve()

        # Validate source directory
        if not self.src_dir.exists():
            raise ValueError(f"Source directory not found: {self.src_dir}")

        if not self.src_dir.is_dir():
            raise ValueError(f"Source path is not a directory: {self.src_dir}")

        # Check if it's a valid Python package directory
        if not any(self.src_dir.glob("*.py")) and not (self.src_dir / "__init__.py").exists():
            # Allow empty directories for now, but warn
            pass

        self.copied_files: list[Path] = []
        self.copied_dirs: list[Path] = []

    def find_src_package_dir(self) -> Path | None:
        """
        Find the main package directory within src/.

        Looks for directories with __init__.py files. If multiple are found,
        tries to match one with the project name from pyproject.toml.

        Returns:
            Path to the main package directory, or src_dir if not found
        """
        if not self.src_dir.exists():
            return None

        # Look for directories with __init__.py
        package_dirs = [
            d for d in self.src_dir.iterdir() if d.is_dir() and (d / "__init__.py").exists()
        ]

        if len(package_dirs) == 1:
            return package_dirs[0]

        # If multiple, try to find the one matching the project name
        project_name = self._get_project_name()
        if project_name:
            for pkg_dir in package_dirs:
                if pkg_dir.name.replace("-", "_") == project_name.replace("-", "_"):
                    return pkg_dir

        # Return the first one or src_dir itself
        return package_dirs[0] if package_dirs else self.src_dir

    def _get_project_name(self) -> str | None:
        """
        Get the project name from pyproject.toml.

        Uses tomllib (Python 3.11+) or tomli as fallback to parse the file.
        Falls back to simple string parsing if TOML parsing is unavailable.

        Returns:
            Project name from pyproject.toml, or None if not found
        """
        pyproject_path = self.project_root / "pyproject.toml"
        if not pyproject_path.exists():
            return None

        try:
            if tomllib:
                content = pyproject_path.read_bytes()
                data = tomllib.loads(content)
                return data.get("project", {}).get("name")
            else:
                # Fallback: simple parsing
                content = pyproject_path.read_text(encoding="utf-8")
                for line in content.split("\n"):
                    if line.strip().startswith("name ="):
                        return line.split("=", 1)[1].strip().strip('"').strip("'")
        except Exception:
            pass

        return None

    def prepare_build(self) -> list[ExternalDependency]:
        """
        Prepare for build by finding and copying external dependencies.

        This method:
        1. Finds all Python files in the source directory
        2. Analyzes them for external dependencies
        3. Copies external files/directories into the source directory
        4. Reports any ambiguous imports

        Returns:
            List of ExternalDependency objects that were copied
        """
        analyzer = ImportAnalyzer(self.project_root)
        finder = ExternalDependencyFinder(self.project_root, self.src_dir)

        # Find all Python files in src/
        python_files = analyzer.find_all_python_files(self.src_dir)

        # Find external dependencies
        external_deps = finder.find_external_dependencies(python_files)

        # Copy external dependencies
        for dep in external_deps:
            self._copy_dependency(dep)

        # Report ambiguous imports
        self._report_ambiguous_imports(python_files)

        return external_deps

    def _copy_dependency(self, dep: ExternalDependency) -> None:
        """
        Copy an external dependency to the target location.

        Handles both files and directories. Checks for idempotency to avoid
        duplicate copies. Creates parent directories as needed.

        Args:
            dep: ExternalDependency object with source and target paths
        """
        source = dep.source_path
        target = dep.target_path

        if not source.exists():
            print(f"Warning: External dependency not found: {source}", file=sys.stderr)
            return

        # Create target directory if needed
        target.parent.mkdir(parents=True, exist_ok=True)

        # Check if already copied (idempotency)
        if target.exists():
            # Check if it's the same file
            if source.is_file() and target.is_file():
                try:
                    if source.samefile(target):
                        return  # Already in place, skip
                except OSError:
                    # Files are different, proceed with copy
                    pass
            elif source.is_dir() and target.is_dir():
                # For directories, check if they have the same structure
                # Simple check: if target has __init__.py and source does too, assume copied
                # Also check if target has any Python files
                source_has_init = (source / "__init__.py").exists()
                target_has_init = (target / "__init__.py").exists()
                if source_has_init == target_has_init:
                    # Check if target has at least some files from source
                    source_files = {f.name for f in source.rglob("*.py")}
                    target_files = {f.name for f in target.rglob("*.py")}
                    if source_files and target_files and source_files.issubset(target_files):
                        # Assume already copied if structure matches
                        return

        try:
            if source.is_file():
                shutil.copy2(source, target)
                self.copied_files.append(target)
                print(f"Copied external file: {source} -> {target}")
            elif source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                shutil.copytree(source, target)
                self.copied_dirs.append(target)
                print(f"Copied external directory: {source} -> {target}")
        except Exception as e:
            print(f"Error copying {source} to {target}: {e}", file=sys.stderr)

    def _report_ambiguous_imports(self, python_files: list[Path]) -> None:
        """
        Report any ambiguous imports that couldn't be resolved.

        Prints warnings to stderr for imports that couldn't be classified
        as stdlib, third-party, local, or external.

        Args:
            python_files: List of Python files to check for ambiguous imports
        """
        analyzer = ImportAnalyzer(self.project_root)
        ambiguous: list[ImportInfo] = []

        for file_path in python_files:
            imports = analyzer.extract_imports(file_path)
            for imp in imports:
                analyzer.classify_import(imp, self.src_dir)
                if imp.classification == "ambiguous":
                    ambiguous.append(imp)

        if ambiguous:
            print("\nWarning: Found ambiguous imports that could not be resolved:", file=sys.stderr)
            for imp in ambiguous:
                print(
                    f"  {imp.module_name} (line {imp.line_number} in {imp.file_path})",
                    file=sys.stderr,
                )

    def cleanup(self) -> None:
        """
        Remove all copied files and directories.

        This method removes all files and directories that were copied
        during prepare_build(). It handles errors gracefully and clears
        the internal tracking lists.
        """
        # Remove copied directories first (they may contain files)
        for dir_path in reversed(self.copied_dirs):
            if dir_path.exists():
                try:
                    shutil.rmtree(dir_path)
                    print(f"Removed copied directory: {dir_path}")
                except Exception as e:
                    print(f"Error removing {dir_path}: {e}", file=sys.stderr)

        # Remove copied files
        for file_path in self.copied_files:
            if file_path.exists():
                try:
                    file_path.unlink()
                    print(f"Removed copied file: {file_path}")
                except Exception as e:
                    print(f"Error removing {file_path}: {e}", file=sys.stderr)

        self.copied_files.clear()
        self.copied_dirs.clear()

    def run_build(self, build_command: Callable[[], None]) -> None:
        """
        Run the build process with dependency management.

        This is a convenience method that:
        1. Calls prepare_build() to find and copy dependencies
        2. Executes the provided build_command
        3. Always calls cleanup() afterward, even if build fails

        Args:
            build_command: Callable that executes the build process

        Example:
            ```python
            def build():
                subprocess.run(["uv", "build"], check=True)

            manager.run_build(build)
            ```
        """
        try:
            print("Analyzing project for external dependencies...")
            external_deps = self.prepare_build()

            if external_deps:
                print(f"\nFound {len(external_deps)} external dependencies")
                print("Copied external dependencies into source directory\n")
            else:
                print("No external dependencies found\n")

            print("Running build...")
            # Build command should run from project root to find pyproject.toml
            import os

            original_cwd = os.getcwd()
            try:
                os.chdir(self.project_root)
                build_command()
            finally:
                os.chdir(original_cwd)

        finally:
            print("\nCleaning up copied files...")
            self.cleanup()

    def build_and_publish(
        self,
        build_command: Callable[[], None],
        repository: str | None = None,
        repository_url: str | None = None,
        username: str | None = None,
        password: str | None = None,
        skip_existing: bool = False,
        version: str | None = None,
        restore_versioning: bool = True,
        package_name: str | None = None,
        dependency_group: str | None = None,
    ) -> None:
        """
        Build and publish the package in one operation.

        This method combines build and publish operations:
        1. Sets version if specified
        2. Prepares external dependencies
        3. Runs the build command
        4. Publishes to the specified repository
        5. Cleans up copied files
        6. Restores versioning configuration if requested

        Args:
            build_command: Callable that executes the build process
            repository: Target repository ('pypi', 'testpypi', or 'azure')
            repository_url: Custom repository URL (required for Azure)
            username: Username for publishing (will prompt if not provided)
            password: Password/token for publishing (will prompt if not provided)
            skip_existing: If True, skip files that already exist on the repository
            version: Manual version to set before building (PEP 440 format)
            restore_versioning: If True, restore dynamic versioning after build
            package_name: Package name for subfolder builds (default: derived from src_dir name)
            dependency_group: Name of dependency group to copy from parent pyproject.toml

        Example:
            ```python
            def build():
                subprocess.run(["uv", "build"], check=True)

            manager.build_and_publish(build, repository="pypi", version="1.2.3")
            ```
        """
        from .publisher import Publisher
        from .version import VersionManager

        version_manager = None
        original_version = None
        subfolder_config = None

        # Check if we're building a subfolder (not the main src/ directory)
        is_subfolder_build = not self.src_dir.is_relative_to(self.project_root / "src") or (
            self.src_dir != self.project_root / "src" and self.src_dir != self.project_root
        )

        try:
            # For subfolder builds, create a temporary pyproject.toml
            if is_subfolder_build and version:
                if not package_name:
                    # Derive package name from subfolder
                    package_name = self.src_dir.name.replace("_", "-").replace(" ", "-").lower().strip("-")
                print(f"Building subfolder as package '{package_name}' version '{version}'...")
                subfolder_config = SubfolderBuildConfig(
                    project_root=self.project_root,
                    src_dir=self.src_dir,
                    package_name=package_name,
                    version=version,
                    dependency_group=dependency_group,
                )
                subfolder_config.create_temp_pyproject()
            elif version:
                # Regular build with version override
                version_manager = VersionManager(self.project_root)
                original_version = version_manager.get_current_version()
                print(f"Setting version to {version}...")
                version_manager.set_version(version)

            # Build the package
            self.run_build(build_command)

            # Publish if repository is specified
            if repository:
                # Determine package name and version for filtering
                publish_package_name = None
                publish_version = version
                
                if is_subfolder_build and package_name:
                    publish_package_name = package_name
                elif not is_subfolder_build:
                    # For regular builds, get package name from pyproject.toml
                    try:
                        import tomllib
                    except ImportError:
                        try:
                            import tomli as tomllib
                        except ImportError:
                            tomllib = None
                    
                    if tomllib:
                        pyproject_path = self.project_root / "pyproject.toml"
                        if pyproject_path.exists():
                            with pyproject_path.open("rb") as f:
                                data = tomllib.load(f)
                                if "project" in data and "name" in data["project"]:
                                    publish_package_name = data["project"]["name"]
                
                publisher = Publisher(
                    repository=repository,
                    dist_dir=self.project_root / "dist",
                    repository_url=repository_url,
                    username=username,
                    password=password,
                    package_name=publish_package_name,
                    version=publish_version,
                )
                publisher.publish(skip_existing=skip_existing)
        finally:
            # Restore subfolder config if used
            if subfolder_config and restore_versioning:
                try:
                    subfolder_config.restore()
                    print("Restored original pyproject.toml")
                except Exception as e:
                    print(f"Warning: Could not restore pyproject.toml: {e}", file=sys.stderr)

            # Restore versioning if needed
            if version_manager and restore_versioning:
                try:
                    if original_version:
                        version_manager.set_version(original_version)
                    else:
                        version_manager.restore_dynamic_versioning()
                    print("Restored versioning configuration")
                except Exception as e:
                    print(f"Warning: Could not restore versioning: {e}", file=sys.stderr)

            # Cleanup is already handled by run_build, but ensure it's done
            if self.copied_files or self.copied_dirs:
                self.cleanup()
