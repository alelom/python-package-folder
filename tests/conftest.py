"""Pytest configuration and fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest


@pytest.fixture(autouse=True, scope="session")
def protect_repository_files():
    """
    Automatically protect repository files from test modifications.

    This fixture backs up pyproject.toml and README.md at the start of the test session
    and restores them at the end, ensuring tests never permanently modify repository files.
    """
    # Get the repository root (parent of tests directory)
    repo_root = Path(__file__).parent.parent

    pyproject_path = repo_root / "pyproject.toml"
    readme_path = repo_root / "README.md"

    # Backup original files if they exist
    pyproject_backup = None
    readme_backup = None
    pyproject_existed = pyproject_path.exists()
    readme_existed = readme_path.exists()

    if pyproject_existed:
        pyproject_backup = pyproject_path.read_bytes()
    if readme_existed:
        readme_backup = readme_path.read_bytes()

    # Yield control to tests
    yield

    # Restore original files after all tests
    if pyproject_backup and pyproject_path.exists():
        try:
            current_content = pyproject_path.read_bytes()
            if current_content != pyproject_backup:
                # File was modified, restore it
                pyproject_path.write_bytes(pyproject_backup)
                print(
                    "Warning: Restored modified pyproject.toml after test session",
                    file=sys.stderr,
                )
        except OSError as e:
            print(
                f"Warning: Could not restore pyproject.toml: {e}",
                file=sys.stderr,
            )
    elif pyproject_backup and not pyproject_path.exists():
        # File was deleted, restore it
        try:
            pyproject_path.write_bytes(pyproject_backup)
            print(
                "Warning: Restored deleted pyproject.toml after test session",
                file=sys.stderr,
            )
        except OSError as e:
            print(
                f"Warning: Could not restore pyproject.toml: {e}",
                file=sys.stderr,
            )

    if readme_backup and readme_path.exists():
        try:
            current_content = readme_path.read_bytes()
            if current_content != readme_backup:
                # File was modified, restore it
                readme_path.write_bytes(readme_backup)
                print(
                    "Warning: Restored modified README.md after test session",
                    file=sys.stderr,
                )
        except OSError as e:
            print(
                f"Warning: Could not restore README.md: {e}",
                file=sys.stderr,
            )
    elif readme_backup and not readme_path.exists():
        # File was deleted, restore it
        try:
            readme_path.write_bytes(readme_backup)
            print(
                "Warning: Restored deleted README.md after test session",
                file=sys.stderr,
            )
        except OSError as e:
            print(
                f"Warning: Could not restore README.md: {e}",
                file=sys.stderr,
            )
