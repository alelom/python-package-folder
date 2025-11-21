"""
Utility functions for project discovery and path resolution.
"""

from __future__ import annotations

from pathlib import Path


def find_project_root(start_path: Path | None = None) -> Path | None:
    """
    Find the project root by searching for pyproject.toml in parent directories.

    Starts from the given path (or current directory) and walks up the directory
    tree until it finds a directory containing pyproject.toml.

    Args:
        start_path: Starting directory for the search (default: current directory)

    Returns:
        Path to the project root directory, or None if not found
    """
    if start_path is None:
        start_path = Path.cwd()

    current = Path(start_path).resolve()

    # Walk up the directory tree
    while current != current.parent:
        pyproject_path = current / "pyproject.toml"
        if pyproject_path.exists():
            return current
        current = current.parent

    # Check the root directory itself
    if (current / "pyproject.toml").exists():
        return current

    return None


def find_source_directory(project_root: Path, current_dir: Path | None = None) -> Path | None:
    """
    Find the appropriate source directory for building.

    Priority:
    1. If current_dir is provided and contains Python files, use it
    2. If project_root/src exists, use it
    3. If project_root contains Python files directly, use project_root
    4. Return None if nothing suitable is found

    Args:
        project_root: Root directory of the project
        current_dir: Current working directory (default: cwd)

    Returns:
        Path to the source directory, or None if not found
    """
    if current_dir is None:
        current_dir = Path.cwd()

    current_dir = current_dir.resolve()
    project_root = project_root.resolve()

    # Check if current directory is a subdirectory with Python files
    # Prioritize current directory if it's within the project and has Python files
    if current_dir.is_relative_to(project_root) and current_dir != project_root:
        python_files = list(current_dir.glob("*.py"))
        if python_files:
            # Current directory has Python files, use it as source
            return current_dir

    # Check for standard src/ directory
    src_dir = project_root / "src"
    if src_dir.exists() and src_dir.is_dir():
        return src_dir

    # Only check project_root if current_dir is the project_root
    if current_dir == project_root:
        python_files = list(project_root.glob("*.py"))
        if python_files:
            return project_root

    return None


def is_python_package_directory(path: Path) -> bool:
    """
    Check if a directory contains Python package files.

    Args:
        path: Directory to check

    Returns:
        True if the directory contains .py files or __init__.py
    """
    if not path.exists() or not path.is_dir():
        return False

    # Check for Python files
    if any(path.glob("*.py")):
        return True

    # Check for __init__.py
    if (path / "__init__.py").exists():
        return True

    return False
