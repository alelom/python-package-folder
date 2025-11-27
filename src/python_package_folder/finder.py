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

    def __init__(
        self, project_root: Path, src_dir: Path, exclude_patterns: list[str] | None = None
    ) -> None:
        """
        Initialize the dependency finder.

        Args:
            project_root: Root directory of the project
            src_dir: Source directory to analyze
            exclude_patterns: Additional patterns to exclude (default: common sandbox patterns)
        """
        self.project_root = project_root.resolve()
        self.src_dir = src_dir.resolve()
        self.analyzer = ImportAnalyzer(project_root)
        # Patterns for directories/files to exclude (sandbox, skip, etc.)
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
        self.exclude_patterns = default_patterns + (exclude_patterns or [])

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

                    # Skip excluded paths (sandbox directories, etc.)
                    if self._should_exclude_path(source_path):
                        continue

                    # For files, only copy parent directory if it's a package
                    # Otherwise, copy just the individual file
                    if source_path.is_file():
                        parent_dir = source_path.parent

                        # Only copy parent directory if:
                        # 1. It's a package (has __init__.py), OR
                        # 2. Files from it are actually imported (which is the case here)
                        # But only copy the immediate parent, not entire directory trees
                        parent_is_package = (parent_dir / "__init__.py").exists()
                        files_are_imported = True  # Always true when processing an import

                        # Only copy immediate parent directory, not grandparent directories
                        # This prevents copying entire trees like models/Information_extraction
                        # when we only need models/Information_extraction/_shared_ie
                        should_copy_dir = (
                            not self._should_exclude_path(parent_dir)
                            and (
                                parent_is_package or files_are_imported
                            )  # Package OR files imported
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
                            # Copy just the file
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

        Preserves the original directory structure relative to project_root or src
        to maintain import paths like `from models. ...` or `from data. ...`.

        Args:
            source_path: Path to the source file or directory
            module_name: Module name from the import statement

        Returns:
            Target path within src_dir, or None if cannot be determined
        """
        if not source_path.exists():
            return None

        module_parts = module_name.split(".")

        # Determine the base directory for calculating relative paths
        # If source is under src/, use src/ as base to preserve structure
        src_base = self.project_root / "src"
        if src_base.exists() and source_path.is_relative_to(src_base):
            # Source is under src/, preserve the path structure relative to src/
            # This ensures imports like `from models. ...` work correctly
            try:
                relative_path = source_path.relative_to(src_base)
                target = self.src_dir / relative_path
                return target
            except ValueError:
                pass

        # For sources not under src/, try to preserve structure based on module name
        # Check if the module name structure matches the source path structure
        if len(module_parts) > 1:
            # For directories, check if the module path (excluding the last part for files) matches
            if source_path.is_dir():
                # For directories, check if module parts match the directory structure
                # e.g., module "folder_structure.utility_folder.some_utility" with dir "folder_structure/utility_folder"
                # should preserve "folder_structure/utility_folder" structure
                # Calculate relative path from project_root
                try:
                    relative_path = source_path.relative_to(self.project_root)
                    # If the module starts with the same parts as the relative path, preserve structure
                    relative_parts = list(relative_path.parts)
                    # Check if module_parts[:-1] (excluding the file/module name) matches relative_parts
                    if len(module_parts) > len(relative_parts):
                        # Module has more parts (includes the file name), check if the directory parts match
                        module_dir_parts = module_parts[: len(relative_parts)]
                        if module_dir_parts == relative_parts:
                            # Preserve the full structure
                            target = self.src_dir / relative_path
                            return target
                    # Try matching from the end
                    if len(relative_parts) <= len(module_parts):
                        # Check if the last parts of module match the relative path
                        for i in range(1, min(len(relative_parts), len(module_parts)) + 1):
                            if module_parts[-i:] == relative_parts[-i:]:
                                # Match found, preserve structure based on module name
                                target = self.src_dir / "/".join(
                                    module_parts[: -i + 1 if i > 1 else len(module_parts)]
                                )
                                return target
                except ValueError:
                    pass
                # Fallback: preserve structure based on module name (excluding last part for files)
                target = self.src_dir / "/".join(module_parts[:-1])
                return target
            else:
                # For files, preserve structure based on module name (excluding filename)
                target = self.src_dir / "/".join(module_parts[:-1]) / source_path.name
                return target

        # Simple top-level import - copy directly to src_dir
        # This handles cases like `from some_globals import ...`
        if source_path.is_file():
            target = self.src_dir / source_path.name
        else:
            target = self.src_dir / source_path.name
        return target

    def _should_exclude_path(self, path: Path) -> bool:
        """
        Check if a path should be excluded from copying.

        Excludes paths that match common sandbox/skip patterns like _SS, __SS, etc.

        Args:
            path: Path to check

        Returns:
            True if the path should be excluded, False otherwise
        """
        # Check each component of the path
        for part in path.parts:
            for pattern in self.exclude_patterns:
                # Match if part equals pattern or starts with pattern
                if part == pattern or part.startswith(pattern):
                    return True
        return False

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
