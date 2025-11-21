"""
Import analysis functionality.

This module provides the ImportAnalyzer class which is responsible for:
- Finding all Python files in a directory tree
- Extracting import statements using AST parsing
- Classifying imports as stdlib, third-party, local, external, or ambiguous
- Resolving import paths to actual file locations
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path

from .types import ImportInfo


class ImportAnalyzer:
    """
    Analyzes Python files to extract and classify import statements.

    This class uses Python's AST module to parse Python files and extract
    all import statements. It can classify imports into different categories
    and resolve their file paths.

    Attributes:
        project_root: Root directory of the project
        _stdlib_modules: Cached set of standard library module names
    """

    def __init__(self, project_root: Path) -> None:
        """
        Initialize the import analyzer.

        Args:
            project_root: Root directory of the project to analyze
        """
        self.project_root = project_root.resolve()
        self._stdlib_modules: set[str] | None = None

    def find_all_python_files(self, directory: Path) -> list[Path]:
        """
        Recursively find all Python files in a directory.

        Excludes common directories like .venv, venv, __pycache__, etc.

        Args:
            directory: Directory to search for Python files

        Returns:
            List of paths to all .py files found in the directory tree
        """
        exclude_patterns = {
            ".venv",
            "venv",
            "__pycache__",
            ".git",
            ".pytest_cache",
            ".mypy_cache",
            "node_modules",
            ".tox",
            "dist",
            "build",
        }

        python_files = []
        for path in directory.rglob("*.py"):
            if not path.is_file():
                continue

            # Check if any part of the path matches exclusion patterns
            should_exclude = False
            for part in path.parts:
                # Check exact matches
                if part in exclude_patterns:
                    should_exclude = True
                    break
                # Check if part starts with excluded pattern or contains .egg-info
                for pattern in exclude_patterns:
                    if part.startswith(pattern):
                        should_exclude = True
                        break
                # Also exclude .egg-info directories
                if ".egg-info" in part:
                    should_exclude = True
                    break
                if should_exclude:
                    break

            if not should_exclude:
                python_files.append(path)

        return python_files

    def extract_imports(self, file_path: Path) -> list[ImportInfo]:
        """
        Extract all import statements from a Python file.

        Uses AST parsing to find both `import` and `from ... import` statements.
        Handles syntax errors gracefully by returning an empty list.

        Args:
            file_path: Path to the Python file to analyze

        Returns:
            List of ImportInfo objects representing all imports found in the file
        """
        imports: list[ImportInfo] = []

        try:
            content = file_path.read_text(encoding="utf-8")
            tree = ast.parse(content, filename=str(file_path))
        except (SyntaxError, UnicodeDecodeError) as e:
            print(f"Warning: Could not parse {file_path}: {e}", file=sys.stderr)
            return imports

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportInfo(
                            module_name=alias.name,
                            import_type="import",
                            line_number=node.lineno,
                            file_path=file_path,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(
                        ImportInfo(
                            module_name=node.module,
                            import_type="from",
                            from_module=node.module,
                            line_number=node.lineno,
                            file_path=file_path,
                        )
                    )

        return imports

    def get_stdlib_modules(self) -> set[str]:
        """
        Get a set of standard library module names.

        Caches the result for performance. Attempts to discover stdlib modules
        by examining the Python installation directory, with a fallback list
        of common standard library modules.

        Returns:
            Set of standard library module names
        """
        if self._stdlib_modules is not None:
            return self._stdlib_modules

        stdlib_modules: set[str] = set()

        # Get standard library path
        stdlib_path = (
            Path(sys.executable).parent
            / "lib"
            / f"python{sys.version_info.major}.{sys.version_info.minor}"
        )
        if not stdlib_path.exists():
            # Fallback: try to import and check sys.path
            import sysconfig

            stdlib_path = Path(sysconfig.get_path("stdlib"))

        if stdlib_path.exists():
            for item in stdlib_path.iterdir():
                if item.is_file() and item.suffix == ".py":
                    stdlib_modules.add(item.stem)
                elif (
                    item.is_dir()
                    and not item.name.startswith("_")
                    and (item / "__init__.py").exists()
                ):
                    stdlib_modules.add(item.name)

        # Add common stdlib modules that might not be in the directory
        common_stdlib = {
            "sys",
            "os",
            "json",
            "pathlib",
            "typing",
            "collections",
            "itertools",
            "functools",
            "dataclasses",
            "enum",
            "abc",
            "contextlib",
            "io",
            "textwrap",
            "ast",
            "importlib",
            "shutil",
            "subprocess",
        }
        stdlib_modules.update(common_stdlib)

        self._stdlib_modules = stdlib_modules
        return stdlib_modules

    def classify_import(self, import_info: ImportInfo, src_dir: Path) -> None:
        """
        Classify an import as stdlib, third-party, local, external, or ambiguous.

        Modifies the ImportInfo object in place, setting its classification
        and resolved_path attributes.

        Args:
            import_info: ImportInfo object to classify
            src_dir: Source directory to use for determining local vs external
        """
        module_name = import_info.module_name
        stdlib_modules = self.get_stdlib_modules()

        # Check if it's a standard library module
        root_module = module_name.split(".")[0]
        if root_module in stdlib_modules:
            import_info.classification = "stdlib"
            return

        # Try to resolve as a local import
        resolved = self.resolve_local_import(import_info, src_dir)
        if resolved is not None:
            if resolved.is_relative_to(src_dir):
                import_info.classification = "local"
            else:
                import_info.classification = "external"
            import_info.resolved_path = resolved
            return

        # Check if it's a third-party package (in site-packages)
        if self.is_third_party(module_name):
            import_info.classification = "third_party"
            return

        # Mark as ambiguous if we can't determine
        import_info.classification = "ambiguous"

    def resolve_local_import(self, import_info: ImportInfo, src_dir: Path) -> Path | None:
        """
        Try to resolve a local import to a file path.

        Handles both relative imports (starting with .) and absolute imports.
        Checks multiple potential locations including parent directories
        of the source directory.

        Args:
            import_info: ImportInfo object with the import to resolve
            src_dir: Source directory to use as reference

        Returns:
            Path to the resolved file, or None if not found
        """
        module_name = import_info.module_name

        # Handle relative imports
        if import_info.file_path:
            file_dir = import_info.file_path.parent
            if module_name.startswith("."):
                # Relative import
                parts = module_name.split(".")
                level = sum(1 for p in parts if p == "")
                module_parts = [p for p in parts if p]

                if level > 0:
                    # Go up 'level' directories
                    current = file_dir
                    for _ in range(level - 1):
                        current = current.parent
                    base_path = current
                else:
                    base_path = file_dir

                if module_parts:
                    potential_path = base_path / "/".join(module_parts)
                else:
                    potential_path = base_path

                # Try as module
                if (potential_path / "__init__.py").exists():
                    return potential_path / "__init__.py"
                if potential_path.with_suffix(".py").exists():
                    return potential_path.with_suffix(".py")
                if potential_path.is_dir() and (potential_path / "__init__.py").exists():
                    return potential_path / "__init__.py"

        # Handle absolute imports - check if it's in the project
        # First check if it's in src_dir
        module_path_str = module_name.replace(".", "/")
        potential_paths = [
            src_dir / module_path_str / "__init__.py",
            (src_dir / module_path_str).with_suffix(".py"),
            self.project_root / module_path_str / "__init__.py",
            (self.project_root / module_path_str).with_suffix(".py"),
        ]

        for path in potential_paths:
            if path.exists():
                return path

        # Check parent directories of src_dir and project_root for external dependencies
        # Check up to project_root's parent
        check_dirs = [src_dir.parent] + list(src_dir.parents)
        for parent in check_dirs:
            if parent == self.project_root.parent:
                break
            if not parent.exists():
                continue

            # Try as module directory
            potential = parent / module_name.replace(".", "/")
            if potential.is_dir() and (potential / "__init__.py").exists():
                return potential / "__init__.py"
            if potential.with_suffix(".py").is_file():
                return potential.with_suffix(".py")

            # Also check if the parent itself contains the module
            potential_file = parent / f"{module_name.split('.')[-1]}.py"
            if potential_file.exists():
                return potential_file

        return None

    def is_third_party(self, module_name: str) -> bool:
        """
        Check if a module is a third-party package.

        Uses importlib to find the module and checks if its location
        is in site-packages or dist-packages.

        Args:
            module_name: Name of the module to check

        Returns:
            True if the module is a third-party package, False otherwise
        """
        root_module = module_name.split(".")[0]
        try:
            spec = importlib.util.find_spec(root_module)
            if spec and spec.origin:
                origin_path = Path(spec.origin)
                # Check if it's in site-packages
                return "site-packages" in str(origin_path) or "dist-packages" in str(origin_path)
        except (ImportError, ValueError, AttributeError):
            pass
        return False
