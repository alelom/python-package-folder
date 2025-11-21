"""
External dependency finding functionality.

This module provides the ExternalDependencyFinder class which identifies
files and directories that are imported from outside the source directory
and need to be temporarily copied during the build process.
"""

from __future__ import annotations

from pathlib import Path

from .analyzer import ImportAnalyzer
from .types import ExternalDependency


class ExternalDependencyFinder:
    """
    Finds external dependencies that need to be copied.

    This class analyzes Python files to identify imports that reference
    modules outside the source directory. It determines which files or
    directories need to be copied and where they should be placed.

    Attributes:
        project_root: Root directory of the project
        src_dir: Source directory where the package code lives
        analyzer: ImportAnalyzer instance for analyzing imports
    """

    def __init__(self, project_root: Path, src_dir: Path) -> None:
        """
        Initialize the dependency finder.

        Args:
            project_root: Root directory of the project
            src_dir: Source directory to analyze
        """
        self.project_root = project_root.resolve()
        self.src_dir = src_dir.resolve()
        self.analyzer = ImportAnalyzer(project_root)

    def find_external_dependencies(self, python_files: list[Path]) -> list[ExternalDependency]:
        """
        Find all external dependencies that need to be copied.

        Analyzes all provided Python files, classifies their imports,
        and identifies which external files/directories need to be copied
        into the source directory.

        Args:
            python_files: List of Python file paths to analyze

        Returns:
            List of ExternalDependency objects representing files/directories
            that need to be copied
        """
        external_deps: list[ExternalDependency] = []
        seen_paths: set[Path] = set()

        for file_path in python_files:
            imports = self.analyzer.extract_imports(file_path)
            for imp in imports:
                self.analyzer.classify_import(imp, self.src_dir)

                if imp.classification == "external" and imp.resolved_path:
                    source_path = imp.resolved_path

                    # For files, check if we should copy the parent directory instead
                    # (e.g., if importing from utility_folder/some_utility.py, copy utility_folder/)
                    if source_path.is_file():
                        # Check if the file is in a directory that should be copied as a whole
                        parent_dir = source_path.parent
                        module_parts = imp.module_name.split(".")

                        # Copy parent directory if:
                        # 1. Module name has multiple parts (suggesting it's a package structure)
                        # 2. Parent is outside src_dir
                        # 3. Parent doesn't contain src_dir (to avoid recursive copies)
                        # 4. Parent is not the project root
                        should_copy_dir = (
                            len(module_parts) > 2  # Has at least package.module structure
                            and not parent_dir.is_relative_to(self.src_dir)
                            and not self.src_dir.is_relative_to(parent_dir)
                            and parent_dir != self.project_root
                            and parent_dir != self.project_root.parent
                        )

                        if should_copy_dir:
                            # Copy the directory instead of just the file
                            track_path = parent_dir
                            source_path = parent_dir
                        else:
                            track_path = source_path
                    elif source_path.is_dir():
                        # Don't copy directories that contain src_dir
                        if self.src_dir.is_relative_to(source_path):
                            continue
                        track_path = source_path
                    else:
                        continue

                    if track_path in seen_paths:
                        continue
                    seen_paths.add(track_path)

                    # Determine target path within src_dir
                    target_path = self._determine_target_path(source_path, imp.module_name)

                    if target_path:
                        # Only add if source is actually outside src_dir
                        if not source_path.is_relative_to(self.src_dir):
                            external_deps.append(
                                ExternalDependency(
                                    source_path=source_path,
                                    target_path=target_path,
                                    import_name=imp.module_name,
                                    file_path=file_path,
                                )
                            )

        return external_deps

    def _determine_target_path(self, source_path: Path, module_name: str) -> Path | None:
        """
        Determine where an external file should be copied within src_dir.

        For files, attempts to maintain the module structure. For directories,
        places them directly in src_dir with their original name.

        Args:
            source_path: Path to the source file or directory
            module_name: Module name from the import statement

        Returns:
            Target path within src_dir, or None if cannot be determined
        """
        if not source_path.exists():
            return None

        # Always create target within src_dir
        module_parts = module_name.split(".")

        if source_path.is_file():
            # For a file, create the directory structure based on module name
            if len(module_parts) > 1:
                # It's a submodule, create the directory structure
                target = self.src_dir / "/".join(module_parts[:-1]) / source_path.name
            else:
                # Top-level module - try to find the main package directory
                # or create a matching structure
                main_pkg = self._find_main_package()
                if main_pkg:
                    target = main_pkg / source_path.name
                else:
                    target = self.src_dir / source_path.name
            return target

        # If it's a directory, copy the whole directory
        if source_path.is_dir():
            # Use the directory name directly in src_dir
            target = self.src_dir / source_path.name
            return target

        return None

    def _find_main_package(self) -> Path | None:
        """
        Find the main package directory within src_dir.

        Looks for directories containing __init__.py files, which indicate
        Python packages.

        Returns:
            Path to the main package directory, or None if not found
        """
        if not self.src_dir.exists():
            return None

        # Look for directories with __init__.py
        package_dirs = [
            d for d in self.src_dir.iterdir() if d.is_dir() and (d / "__init__.py").exists()
        ]

        if package_dirs:
            return package_dirs[0]

        return None
