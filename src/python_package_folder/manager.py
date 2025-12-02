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

    def __init__(
        self,
        project_root: Path,
        src_dir: Path | None = None,
        exclude_patterns: list[str] | None = None,
    ) -> None:
        """
        Initialize the build manager.

        Args:
            project_root: Root directory of the project
            src_dir: Source directory (defaults to project_root/src, or current dir if it has Python files)
            exclude_patterns: Additional patterns to exclude from copying (e.g., ['_SS', '__sandbox'])

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

        self.copied_files: list[Path] = []
        self.copied_dirs: list[Path] = []
        self.exclude_patterns = exclude_patterns or []
        self.finder = ExternalDependencyFinder(
            self.project_root, self.src_dir, exclude_patterns=exclude_patterns
        )
        self.subfolder_config: SubfolderBuildConfig | None = None
        # Cache for package name lookups (expensive operation)
        self._packages_distributions_cache: dict[str, list[str]] | None = None
        # Track files with modified imports and their original content
        self._modified_import_files: dict[Path, str] = {}

        # Check if it's a valid Python package directory
        if not any(self.src_dir.glob("*.py")) and not (self.src_dir / "__init__.py").exists():
            # Allow empty directories for now, but warn
            pass

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

    def _is_subfolder_build(self) -> bool:
        """
        Check if we're building a subfolder (not the main src/ directory).

        Returns:
            True if this is a subfolder build, False otherwise
        """
        # Check if src_dir is not the main src/ directory
        main_src = self.project_root / "src"
        return (
            self.src_dir != main_src
            and self.src_dir != self.project_root
            and self.src_dir.is_relative_to(self.project_root)
        )

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

    def prepare_build(
        self,
        version: str | None = None,
        package_name: str | None = None,
        dependency_group: str | None = None,
    ) -> list[ExternalDependency]:
        """
        Prepare for build by finding and copying external dependencies.

        This method automatically detects if you're building a subfolder (not the main src/
        directory) and sets up pyproject.toml appropriately:
        - If pyproject.toml exists in the subfolder, it will be used
        - Otherwise, creates a temporary pyproject.toml with the correct package configuration
        For subfolder builds without their own pyproject.toml, if no version is provided,
        it defaults to "0.0.0" with a warning.

        Process:
        1. Detects if this is a subfolder build and sets up pyproject.toml if needed:
           - If pyproject.toml exists in subfolder: uses that file
           - If no pyproject.toml in subfolder: creates temporary one from parent
        2. Finds all Python files in the source directory
        3. Analyzes them for external dependencies
        4. Copies external files/directories into the source directory
        5. Reports any ambiguous imports

        Args:
            version: Version for subfolder builds. If building a subfolder and version is None,
                defaults to "0.0.0" with a warning. Only used when creating temporary pyproject.toml
                (ignored if subfolder has its own pyproject.toml). For regular builds, this parameter
                is ignored.
            package_name: Package name for subfolder builds. If None, derived from src_dir name
                (e.g., "empty_drawing_detection" -> "empty-drawing-detection"). Only used when
                creating temporary pyproject.toml (ignored if subfolder has its own pyproject.toml).
                Ignored for regular builds.
            dependency_group: Name of dependency group to copy from parent pyproject.toml.
                Only used for subfolder builds when creating temporary pyproject.toml.

        Returns:
            List of ExternalDependency objects that were copied

        Example:
            ```python
            # Regular build (main src/ directory)
            manager = BuildManager(project_root=Path("."), src_dir=Path("src"))
            deps = manager.prepare_build()  # No version needed

            # Subfolder build (automatic detection)
            manager = BuildManager(
                project_root=Path("."),
                src_dir=Path("src/integration/empty_drawing_detection")
            )
            # Version defaults to "0.0.0" if not provided
            deps = manager.prepare_build(version="1.0.0", package_name="my-package")
            ```
        """
        # Check if this is a subfolder build and set up config if needed
        if self._is_subfolder_build():
            # For subfolder builds, we need a version
            # If not provided, use a default version
            if not version:
                version = "0.0.0"
                print(
                    f"Warning: No version specified for subfolder build. Using default version '{version}'",
                    file=sys.stderr,
                )

            if not package_name:
                # Derive package name from subfolder
                package_name = (
                    self.src_dir.name.replace("_", "-").replace(" ", "-").lower().strip("-")
                )

            print(
                f"Detected subfolder build. Setting up package '{package_name}' version '{version}'..."
            )
            self.subfolder_config = SubfolderBuildConfig(
                project_root=self.project_root,
                src_dir=self.src_dir,
                package_name=package_name,
                version=version,
                dependency_group=dependency_group,
            )
            temp_pyproject = self.subfolder_config.create_temp_pyproject()
            # If temp_pyproject is None, it means no parent pyproject.toml exists
            # This is acceptable for tests or dependency-only operations
            if temp_pyproject is None:
                self.subfolder_config = None

        analyzer = ImportAnalyzer(self.project_root)

        # Find all Python files in src/
        python_files = analyzer.find_all_python_files(self.src_dir)

        # Find external dependencies using the configured finder
        external_deps = self.finder.find_external_dependencies(python_files)

        # Copy external dependencies
        for dep in external_deps:
            self._copy_dependency(dep)

        # For subfolder builds, fix imports
        if self._is_subfolder_build() and external_deps:
            # Fix relative imports in copied dependency files (convert to absolute)
            self._fix_relative_imports_in_copied_files(external_deps)
            # Convert absolute imports of copied dependencies and local files to relative imports
            self._convert_imports_to_relative(python_files, external_deps)

        # For subfolder builds, extract third-party dependencies and add to pyproject.toml
        if self._is_subfolder_build() and self.subfolder_config:
            # Re-analyze all Python files (including copied dependencies) to find third-party imports
            print("Analyzing Python files for third-party dependencies...")
            all_python_files = analyzer.find_all_python_files(self.src_dir)
            print(f"Found {len(all_python_files)} Python files to analyze")
            third_party_deps = self._extract_third_party_dependencies(all_python_files, analyzer)
            if third_party_deps:
                print(
                    f"Found {len(third_party_deps)} third-party dependencies: {', '.join(third_party_deps)}"
                )
                self.subfolder_config.add_third_party_dependencies(third_party_deps)
            else:
                print("No third-party dependencies found in subfolder code")

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
                # If copying a Python file, ensure parent directory has __init__.py
                # This helps type checkers resolve imports correctly
                if source.suffix == ".py" and target.parent != self.src_dir:
                    init_file = target.parent / "__init__.py"
                    if not init_file.exists():
                        init_file.write_text("", encoding="utf-8")
                        self.copied_files.append(init_file)
            elif source.is_dir():
                if target.exists():
                    shutil.rmtree(target)
                # Use custom copy function that excludes certain patterns
                self._copytree_excluding(source, target)
                self.copied_dirs.append(target)
                print(f"Copied external directory: {source} -> {target}")
        except Exception as e:
            print(f"Error copying {source} to {target}: {e}", file=sys.stderr)

    def _copytree_excluding(self, src: Path, dst: Path) -> None:
        """
        Copy a directory tree, excluding certain patterns.

        Excludes directories matching patterns like _SS, __SS, _sandbox, etc.
        Ensures __init__.py files exist in directories containing Python files
        so that type checkers can resolve imports correctly.

        Args:
            src: Source directory
            dst: Destination directory
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
        exclude_patterns = default_patterns + self.exclude_patterns

        def should_exclude(path: Path) -> bool:
            """Check if a path should be excluded."""
            # Check each component of the path
            for part in path.parts:
                # Check if any part matches an exclusion pattern
                for pattern in exclude_patterns:
                    # Match if part equals pattern or starts with pattern
                    if part == pattern or part.startswith(pattern):
                        return True
            return False

        # Create destination directory
        dst.mkdir(parents=True, exist_ok=True)

        has_python_files = False
        copied_python_files = []

        # Copy files and subdirectories, excluding patterns
        for item in src.iterdir():
            if should_exclude(item):
                continue

            src_item = src / item.name
            dst_item = dst / item.name

            if src_item.is_file():
                shutil.copy2(src_item, dst_item)
                if src_item.suffix == ".py":
                    has_python_files = True
                    copied_python_files.append(dst_item)
            elif src_item.is_dir():
                self._copytree_excluding(src_item, dst_item)
                # Check if the subdirectory has Python files
                if any(dst_item.rglob("*.py")):
                    has_python_files = True

        # Ensure __init__.py exists in directories containing Python files
        # This is needed for type checkers to resolve imports correctly
        # Also ensure all parent directories in the path have __init__.py
        if has_python_files:
            init_file = dst / "__init__.py"
            if not init_file.exists():
                # Create an empty __init__.py file
                init_file.write_text("", encoding="utf-8")
                self.copied_files.append(init_file)

            # Ensure all parent directories up to src_dir also have __init__.py
            # This helps type checkers resolve nested imports like:
            # from empty_drawing_detection.models.Information_extraction._shared_ie.ie_enums import ...
            current = dst
            while current != self.src_dir and current.is_relative_to(self.src_dir):
                parent_init = current.parent / "__init__.py"
                if (
                    parent_init.parent != self.src_dir
                    and not parent_init.exists()
                    and any(current.parent.rglob("*.py"))
                ):
                    parent_init.write_text("", encoding="utf-8")
                    self.copied_files.append(parent_init)
                current = current.parent

    def _get_package_name_from_import(self, module_name: str) -> str | None:
        """
        Get the actual PyPI package name from an import module name.

        This handles cases where the import name differs from the package name
        (e.g., 'import fitz' from 'pymupdf' package).

        Args:
            module_name: The module name from the import statement

        Returns:
            The actual package name, or None if not found
        """
        root_module = module_name.split(".")[0]
        try:
            # Try Python 3.10+ first (has packages_distributions)
            import importlib.metadata as importlib_metadata

            # Use packages_distributions() if available (Python 3.10+)
            # Cache the result since it's expensive to call
            if hasattr(importlib_metadata, "packages_distributions"):
                if self._packages_distributions_cache is None:
                    # Cache the packages_distributions() result
                    self._packages_distributions_cache = importlib_metadata.packages_distributions()
                packages_map = self._packages_distributions_cache
                # packages_map is a dict mapping module names to list of distribution names
                if root_module in packages_map:
                    # Return the first distribution name (usually there's only one)
                    dist_names = packages_map[root_module]
                    if dist_names:
                        return dist_names[0]

            # Fallback: search all distributions (this can be slow, so limit search)
            # Only check top-level package matches to speed up search
            dist_count = 0
            max_distributions_to_check = 1000  # Limit to prevent excessive searching
            for dist in importlib_metadata.distributions():
                dist_count += 1
                if dist_count > max_distributions_to_check:
                    # Too many distributions, give up to avoid hanging
                    break
                try:
                    # Check distribution name first (fast check)
                    dist_name = dist.metadata.get("Name", "")
                    # If distribution name matches or contains the module name, check files
                    if dist_name.lower().replace(
                        "-", "_"
                    ) == root_module.lower() or root_module.lower() in dist_name.lower().replace(
                        "-", "_"
                    ):
                        # Check if this distribution provides the module by looking at its files
                        files = dist.files or []
                        # Limit file checking to first 100 files per distribution
                        file_count = 0
                        for file in files:
                            file_count += 1
                            if file_count > 100:
                                break
                            file_str = str(file)
                            # Check if file is the module itself or in a package directory
                            if (
                                file.suffix == ".py"
                                and (file.stem == root_module or file.stem == "__init__")
                            ) or (
                                "/" in file_str
                                and (
                                    file_str.startswith(f"{root_module}/")
                                    or file_str.startswith(f"{root_module.replace('_', '-')}/")
                                )
                            ):
                                return dist.metadata["Name"]
                except Exception:
                    continue

        except ImportError:
            try:
                # Fallback for older Python versions
                import importlib_metadata

                # Search all distributions
                for dist in importlib_metadata.distributions():
                    try:
                        files = dist.files or []
                        for file in files:
                            file_str = str(file)
                            if (
                                file.suffix == ".py"
                                and (file.stem == root_module or file.stem == "__init__")
                            ) or (
                                "/" in file_str
                                and (
                                    file_str.startswith(f"{root_module}/")
                                    or file_str.startswith(f"{root_module.replace('_', '-')}/")
                                )
                            ):
                                return dist.metadata["Name"]
                    except Exception:
                        continue
            except ImportError:
                pass
        except Exception:
            pass

        return None

    def _extract_third_party_dependencies(
        self, python_files: list[Path], analyzer: ImportAnalyzer
    ) -> list[str]:
        """
        Extract third-party package dependencies from Python files.

        Analyzes all Python files to find imports classified as "third_party"
        and returns a list of unique package names. Handles cases where the
        import name differs from the package name (e.g., 'fitz' -> 'pymupdf').

        Args:
            python_files: List of Python file paths to analyze
            analyzer: ImportAnalyzer instance to use for classification

        Returns:
            List of unique third-party package names (e.g., ["pypdf", "requests", "pymupdf"])
        """
        third_party_packages: set[str] = set()
        # Cache package name lookups to avoid repeated expensive searches
        package_name_cache: dict[str, str | None] = {}

        total_files = len(python_files)
        for idx, file_path in enumerate(python_files):
            if idx > 0 and idx % 50 == 0:
                print(f"  Analyzing file {idx}/{total_files}...", end="\r", flush=True)

            imports = analyzer.extract_imports(file_path)
            for imp in imports:
                analyzer.classify_import(imp, self.src_dir)

                # Extract the root package name (first part of module name)
                root_module = imp.module_name.split(".")[0]

                # Skip if it's a standard library module
                stdlib_modules = analyzer.get_stdlib_modules()
                if root_module in stdlib_modules:
                    continue

                # Skip if it's local or external (already copied, don't add as dependency)
                if imp.classification in ("local", "external"):
                    continue

                # If classified as third_party, try to get actual package name
                if imp.classification == "third_party":
                    # Double-check: if it resolves to a file in src_dir, it's actually local
                    # (might have been copied and now resolves locally)
                    if imp.resolved_path and imp.resolved_path.is_relative_to(self.src_dir):
                        continue  # Skip - it's a local file, not a third-party package
                    # Check cache first
                    if root_module not in package_name_cache:
                        package_name_cache[root_module] = self._get_package_name_from_import(
                            imp.module_name
                        )
                    actual_package = package_name_cache[root_module]
                    if actual_package:
                        third_party_packages.add(actual_package)
                    else:
                        # Fallback to using the import name
                        third_party_packages.add(root_module)
                # If it's ambiguous or unresolved, and not stdlib/local/external,
                # only add as dependency if we can verify it's actually an installed package
                elif imp.classification == "ambiguous" or imp.classification is None:
                    # Check if it's not a local or external module
                    if not imp.resolved_path:
                        # Try to verify it's actually an installed package before adding
                        # Check cache first
                        if root_module not in package_name_cache:
                            package_name_cache[root_module] = self._get_package_name_from_import(
                                imp.module_name
                            )
                        actual_package = package_name_cache[root_module]
                        # Only add if we can verify it's an actual installed package
                        # Don't add ambiguous imports that we can't verify
                        if actual_package:
                            third_party_packages.add(actual_package)
                        # If we can't verify it's a package, don't add it
                        # (it's likely a local file that wasn't resolved properly)

        if total_files > 50:
            print()  # New line after progress indicator

        return sorted(list(third_party_packages))

    def _fix_relative_imports_in_copied_files(
        self, external_deps: list[ExternalDependency]
    ) -> None:
        """
        Fix relative imports in copied dependency files.

        When files are copied into the subfolder, their relative imports (like
        `from ._shared.shared_dataclasses import ...`) break because the file
        structure has changed. Convert these to absolute imports based on the
        target location.

        Args:
            external_deps: List of external dependencies that were copied
        """
        import ast
        import re

        # Find all Python files in copied dependencies
        copied_files: list[Path] = []
        for dep in external_deps:
            if dep.target_path.is_file() and dep.target_path.suffix == ".py":
                copied_files.append(dep.target_path)
            elif dep.target_path.is_dir():
                copied_files.extend(dep.target_path.rglob("*.py"))

        for file_path in copied_files:
            try:
                content = file_path.read_text(encoding="utf-8")
                original_content = content
                lines = content.split("\n")
                modified = False

                try:
                    tree = ast.parse(content, filename=str(file_path))
                except SyntaxError:
                    continue

                lines_to_modify: dict[int, str] = {}

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.module is None:
                            continue

                        # Check if this is a relative import (level > 0)
                        if node.level == 0:
                            continue

                        line_num = node.lineno - 1
                        if line_num < 0 or line_num >= len(lines):
                            continue

                        original_line = lines[line_num]

                        # Convert relative import to absolute based on target location
                        # When a file is copied to the package root, relative imports need to be absolute
                        # For example: from ._shared.shared_dataclasses -> from _shared.shared_dataclasses
                        if node.module:
                            # Remove the leading dots and convert to absolute
                            # If it was `from ._shared.shared_dataclasses`, it becomes `from _shared.shared_dataclasses`
                            absolute_module = node.module
                            new_line = re.sub(
                                rf"^(\s*)from\s+\.+{re.escape(node.module)}\s+import",
                                rf"\1from {absolute_module} import",
                                original_line,
                            )
                        else:
                            # from . import X -> from . import X (keep as relative, but at package root level)
                            # Actually, if we're at package root, this should work as-is
                            # But if the file was in a subdirectory, we need to adjust
                            # For now, keep it as relative import
                            continue

                        if new_line != original_line:
                            lines_to_modify[line_num] = new_line
                            modified = True

                if modified:
                    for line_num, new_line in lines_to_modify.items():
                        lines[line_num] = new_line

                    new_content = "\n".join(lines)
                    if file_path not in self._modified_import_files:
                        self._modified_import_files[file_path] = original_content

                    file_path.write_text(new_content, encoding="utf-8")
                    print(f"Fixed relative imports in copied file: {file_path}")

            except Exception as e:
                print(
                    f"Warning: Could not fix imports in copied file {file_path}: {e}",
                    file=sys.stderr,
                )

    def _convert_imports_to_relative(
        self, python_files: list[Path], external_deps: list[ExternalDependency]
    ) -> None:
        """
        Convert absolute imports to relative imports for subfolder builds.

        For subfolder builds, when external dependencies are copied into the subfolder,
        imports need to be converted from absolute to relative so they work correctly
        when the package is installed. This includes:
        1. Imports of copied dependencies (e.g., `from _shared.image_utils` -> `from ._shared.image_utils`)
        2. Imports of local files within the subfolder (e.g., `from detect_empty_drawings_utils` -> `from .detect_empty_drawings_utils`)

        Args:
            python_files: List of Python files in the source directory
            external_deps: List of external dependencies that were copied
        """
        import ast
        import re

        # Build a set of import names that were copied
        copied_import_names: set[str] = set()
        for dep in external_deps:
            root_module = dep.import_name.split(".")[0]
            copied_import_names.add(root_module)
            copied_import_names.add(dep.import_name)

        # Build a set of local file names in the subfolder (excluding copied dependencies)
        local_file_names: set[str] = set()
        for file_path in python_files:
            # Skip files that are part of copied dependencies
            is_copied_file = any(file_path.is_relative_to(dep.target_path) for dep in external_deps)
            if is_copied_file:
                continue
            if not file_path.is_relative_to(self.src_dir):
                continue
            # Get the module name (filename without .py extension)
            if file_path.suffix == ".py":
                module_name = file_path.stem
                if module_name != "__init__":
                    local_file_names.add(module_name)

        # Only modify files that are in the original subfolder (not the copied dependencies)
        for file_path in python_files:
            # Skip files that are part of copied dependencies
            is_copied_file = any(file_path.is_relative_to(dep.target_path) for dep in external_deps)
            if is_copied_file:
                continue

            # Skip if file is not in src_dir (shouldn't happen, but safety check)
            if not file_path.is_relative_to(self.src_dir):
                continue

            try:
                content = file_path.read_text(encoding="utf-8")
                original_content = content
                lines = content.split("\n")
                modified = False

                # Parse the file with AST to find imports accurately
                try:
                    tree = ast.parse(content, filename=str(file_path))
                except SyntaxError:
                    # Skip files with syntax errors
                    continue

                # Track which lines need to be modified
                lines_to_modify: dict[int, str] = {}

                for node in ast.walk(tree):
                    if isinstance(node, ast.ImportFrom):
                        if node.module is None:
                            continue

                        # Check if this import matches a copied dependency or a local file
                        root_module = node.module.split(".")[0]
                        is_copied_dependency = (
                            root_module in copied_import_names or node.module in copied_import_names
                        )
                        is_local_file = root_module in local_file_names

                        if not is_copied_dependency and not is_local_file:
                            continue

                        # Get the line content
                        line_num = node.lineno - 1  # Convert to 0-based index
                        if line_num < 0 or line_num >= len(lines):
                            continue

                        original_line = lines[line_num]

                        # Skip if already a relative import
                        if original_line.strip().startswith("from ."):
                            continue

                        # Convert absolute import to relative import
                        # from _shared.image_utils import ... -> from ._shared.image_utils import ...
                        new_line = re.sub(
                            rf"^(\s*)from\s+{re.escape(node.module)}\s+import",
                            rf"\1from .{node.module} import",
                            original_line,
                        )

                        if new_line != original_line:
                            lines_to_modify[line_num] = new_line
                            modified = True

                    elif isinstance(node, ast.Import):
                        # Handle "import X" statements
                        for alias in node.names:
                            root_module = alias.name.split(".")[0]
                            is_copied_dependency = root_module in copied_import_names
                            is_local_file = root_module in local_file_names

                            if not is_copied_dependency and not is_local_file:
                                continue

                            line_num = node.lineno - 1
                            if line_num < 0 or line_num >= len(lines):
                                continue

                            original_line = lines[line_num]

                            # Skip if already a relative import
                            if original_line.strip().startswith("import ."):
                                continue

                            # Convert "import _shared" to "from . import _shared"
                            # This is more complex, so we'll use a regex replacement
                            new_line = re.sub(
                                rf"^(\s*)import\s+{re.escape(alias.name)}\b",
                                rf"\1from . import {alias.name}",
                                original_line,
                            )

                            if new_line != original_line:
                                lines_to_modify[line_num] = new_line
                                modified = True

                # Apply modifications
                if modified:
                    for line_num, new_line in lines_to_modify.items():
                        lines[line_num] = new_line

                    new_content = "\n".join(lines)
                    # Store original content for restoration
                    if file_path not in self._modified_import_files:
                        self._modified_import_files[file_path] = original_content

                    # Write modified content
                    file_path.write_text(new_content, encoding="utf-8")
                    print(f"Converted imports to relative in: {file_path}")

            except Exception as e:
                print(
                    f"Warning: Could not modify imports in {file_path}: {e}",
                    file=sys.stderr,
                )

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

        This method removes all files and directories that were copied during prepare_build().
        It also restores the original pyproject.toml if a temporary one was created for a
        subfolder build. Additionally, it removes all .egg-info directories created during
        the build process and cleans up any empty directories that remain after removing
        copied files. It handles errors gracefully and clears the internal tracking lists.

        This is automatically called by run_build(), but you can call it manually if you
        use prepare_build() directly.

        Example:
            ```python
            manager = BuildManager(project_root=Path("."), src_dir=Path("src"))
            deps = manager.prepare_build()
            # ... do your build ...
            manager.cleanup()  # Restores pyproject.toml, removes copied files, .egg-info dirs, and empty dirs
            ```
        """
        # Restore subfolder config if it was created
        if self.subfolder_config:
            try:
                self.subfolder_config.restore()
                print("Restored original pyproject.toml")
            except Exception as e:
                print(f"Warning: Could not restore pyproject.toml: {e}", file=sys.stderr)
            self.subfolder_config = None

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

        # Restore files with modified imports
        for file_path, original_content in self._modified_import_files.items():
            if file_path.exists():
                try:
                    file_path.write_text(original_content, encoding="utf-8")
                    print(f"Restored original imports in: {file_path}")
                except Exception as e:
                    print(
                        f"Warning: Could not restore imports in {file_path}: {e}",
                        file=sys.stderr,
                    )
        self._modified_import_files.clear()

        # Remove all .egg-info directories in src_dir and project_root
        self._cleanup_egg_info_dirs()

        # Remove empty directories that may remain after cleanup
        self._cleanup_empty_dirs()

    def _cleanup_egg_info_dirs(self) -> None:
        """
        Remove all .egg-info directories in the source directory and project root.

        These directories are created by setuptools during the build process and
        should be cleaned up after the build completes.
        """
        # Search in src_dir and project_root
        search_dirs = [self.src_dir, self.project_root]

        for search_dir in search_dirs:
            if not search_dir.exists():
                continue

            # Find all .egg-info directories
            for egg_info_dir in search_dir.rglob("*.egg-info"):
                if egg_info_dir.is_dir():
                    try:
                        shutil.rmtree(egg_info_dir)
                        print(f"Removed .egg-info directory: {egg_info_dir}")
                    except Exception as e:
                        print(
                            f"Warning: Could not remove .egg-info directory {egg_info_dir}: {e}",
                            file=sys.stderr,
                        )

    def _cleanup_empty_dirs(self) -> None:
        """
        Remove empty directories in the source directory after cleanup.

        After removing copied files and directories, some parent directories may
        become empty. This method recursively removes empty directories starting
        from the deepest level.
        """
        if not self.src_dir.exists():
            return

        # Collect all directories in src_dir, sorted by depth (deepest first)
        all_dirs: list[Path] = []
        for item in self.src_dir.rglob("*"):
            if item.is_dir():
                all_dirs.append(item)

        # Sort by path depth (deepest first) so we remove children before parents
        all_dirs.sort(key=lambda p: len(p.parts), reverse=True)

        # Remove empty directories (but not src_dir itself)
        for dir_path in all_dirs:
            if dir_path == self.src_dir:
                continue

            try:
                # Check if directory is empty
                if dir_path.exists() and not any(dir_path.iterdir()):
                    dir_path.rmdir()
                    print(f"Removed empty directory: {dir_path}")
            except (OSError, PermissionError):
                # Directory not empty or permission error - skip it
                pass
            except Exception as e:
                print(
                    f"Warning: Could not remove directory {dir_path}: {e}",
                    file=sys.stderr,
                )

    def run_build(
        self,
        build_command: Callable[[], None],
        version: str | None = None,
        package_name: str | None = None,
        dependency_group: str | None = None,
    ) -> None:
        """
        Run the build process with dependency management.

        This is a convenience method that automatically handles the full build lifecycle:
        1. Calls prepare_build() to find and copy dependencies (with automatic subfolder detection)
        2. Executes the provided build_command
        3. Always calls cleanup() afterward, even if build fails

        For subfolder builds, this method automatically detects the subfolder and creates a
        temporary pyproject.toml with the correct package configuration. The build command
        should be runnable from the project root (e.g., "uv build", "python -m build").

        Args:
            build_command: Callable that executes the build process. Should run from project root.
            version: Version for subfolder builds. If building a subfolder and version is None,
                defaults to "0.0.0" with a warning. Ignored for regular builds.
            package_name: Package name for subfolder builds. If None, derived from src_dir name.
                Ignored for regular builds.
            dependency_group: Name of dependency group to copy from parent pyproject.toml.
                Only used for subfolder builds.

        Example:
            ```python
            from pathlib import Path
            from python_package_folder import BuildManager
            import subprocess

            # Regular build
            manager = BuildManager(project_root=Path("."), src_dir=Path("src"))
            def build():
                subprocess.run(["uv", "build"], check=True)
            manager.run_build(build)

            # Subfolder build (automatic detection)
            manager = BuildManager(
                project_root=Path("."),
                src_dir=Path("src/integration/empty_drawing_detection")
            )
            manager.run_build(build, version="1.0.0")
            ```
        """
        try:
            print("Analyzing project for external dependencies...")
            external_deps = self.prepare_build(
                version=version, package_name=package_name, dependency_group=dependency_group
            )

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

        try:
            # For non-subfolder builds with version, use VersionManager
            if version and not self._is_subfolder_build():
                version_manager = VersionManager(self.project_root)
                original_version = version_manager.get_current_version()
                print(f"Setting version to {version}...")
                version_manager.set_version(version)

            # Build the package (prepare_build will handle subfolder config if needed)
            # Capture package name BEFORE cleanup (which happens in run_build)
            captured_package_name = None
            if self._is_subfolder_build():
                # We need to get the package name before run_build cleans up subfolder_config
                if not package_name:
                    # Derive from src_dir name (same logic as in prepare_build)
                    captured_package_name = (
                        self.src_dir.name.replace("_", "-").replace(" ", "-").lower().strip("-")
                    )
                else:
                    captured_package_name = package_name

            self.run_build(
                build_command,
                version=version,
                package_name=package_name,
                dependency_group=dependency_group,
            )

            # Publish if repository is specified
            if repository:
                # Determine package name and version for filtering
                publish_package_name = None
                publish_version = version
                is_subfolder_build = self._is_subfolder_build()

                if is_subfolder_build:
                    # Use captured package name (subfolder_config was cleaned up in run_build)
                    if captured_package_name:
                        publish_package_name = captured_package_name
                    elif self.subfolder_config:
                        # Fallback: if somehow subfolder_config still exists
                        publish_package_name = self.subfolder_config.package_name
                    elif package_name:
                        publish_package_name = package_name
                    else:
                        # Last resort: derive from src_dir name
                        publish_package_name = (
                            self.src_dir.name.replace("_", "-").replace(" ", "-").lower().strip("-")
                        )
                else:
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

                # Ensure we have package name and version for filtering
                if is_subfolder_build and not publish_package_name:
                    raise ValueError(
                        "Could not determine package name for subfolder build. "
                        "Please specify --package-name explicitly."
                    )
                if is_subfolder_build and not publish_version:
                    raise ValueError(
                        "Version is required for subfolder builds. "
                        "Please specify --version explicitly."
                    )

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
            # Restore versioning if needed (subfolder config is handled by cleanup)
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
