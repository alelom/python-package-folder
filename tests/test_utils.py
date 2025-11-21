"""Tests for utility functions."""

from __future__ import annotations

from pathlib import Path

import pytest

from python_package_folder import find_project_root, find_source_directory
from python_package_folder.utils import is_python_package_directory


class TestFindProjectRoot:
    """Tests for find_project_root function."""

    def test_find_project_root_in_current_dir(self, tmp_path: Path) -> None:
        """Test finding project root in current directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "pyproject.toml").write_text("[project]\nname = 'test'")

        found = find_project_root(project_root)

        assert found == project_root

    def test_find_project_root_in_parent(self, tmp_path: Path) -> None:
        """Test finding project root in parent directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "pyproject.toml").write_text("[project]\nname = 'test'")

        subdir = project_root / "subdir" / "nested"
        subdir.mkdir(parents=True)

        found = find_project_root(subdir)

        assert found == project_root

    def test_find_project_root_not_found(self, tmp_path: Path) -> None:
        """Test when project root is not found."""
        some_dir = tmp_path / "some_dir"
        some_dir.mkdir()

        found = find_project_root(some_dir)

        assert found is None

    def test_find_project_root_defaults_to_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Test that find_project_root defaults to current directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "pyproject.toml").write_text("[project]\nname = 'test'")

        monkeypatch.chdir(project_root)

        found = find_project_root()

        assert found == project_root


class TestFindSourceDirectory:
    """Tests for find_source_directory function."""

    def test_find_source_directory_with_python_files(self, tmp_path: Path) -> None:
        """Test finding source directory with Python files."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "pyproject.toml").write_text("[project]\nname = 'test'")

        subdir = project_root / "subdir"
        subdir.mkdir()
        (subdir / "module.py").write_text("def func(): pass")

        found = find_source_directory(project_root, subdir)

        assert found == subdir

    def test_find_source_directory_with_init(self, tmp_path: Path) -> None:
        """Test finding source directory with __init__.py."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "pyproject.toml").write_text("[project]\nname = 'test'")

        subdir = project_root / "subdir"
        subdir.mkdir()
        (subdir / "__init__.py").write_text("")

        found = find_source_directory(project_root, subdir)

        assert found == subdir

    def test_find_source_directory_falls_back_to_src(self, tmp_path: Path) -> None:
        """Test falling back to src/ directory."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "pyproject.toml").write_text("[project]\nname = 'test'")

        src_dir = project_root / "src"
        src_dir.mkdir()
        package_dir = src_dir / "package"
        package_dir.mkdir()
        (package_dir / "__init__.py").write_text("")

        # Current dir has no Python files
        current_dir = project_root / "docs"
        current_dir.mkdir()

        found = find_source_directory(project_root, current_dir)

        assert found == src_dir

    def test_find_source_directory_no_src(self, tmp_path: Path) -> None:
        """Test when src/ doesn't exist and current dir has no Python files."""
        project_root = tmp_path / "project"
        project_root.mkdir()
        (project_root / "pyproject.toml").write_text("[project]\nname = 'test'")

        current_dir = project_root / "docs"
        current_dir.mkdir()

        found = find_source_directory(project_root, current_dir)

        assert found is None


class TestIsPythonPackageDirectory:
    """Tests for is_python_package_directory function."""

    def test_is_python_package_with_init(self, tmp_path: Path) -> None:
        """Test directory with __init__.py."""
        pkg_dir = tmp_path / "package"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text("")

        assert is_python_package_directory(pkg_dir) is True

    def test_is_python_package_with_py_files(self, tmp_path: Path) -> None:
        """Test directory with Python files."""
        pkg_dir = tmp_path / "package"
        pkg_dir.mkdir()
        (pkg_dir / "module.py").write_text("def func(): pass")

        assert is_python_package_directory(pkg_dir) is True

    def test_is_not_python_package(self, tmp_path: Path) -> None:
        """Test directory without Python files."""
        pkg_dir = tmp_path / "package"
        pkg_dir.mkdir()
        (pkg_dir / "readme.txt").write_text("Some text")

        assert is_python_package_directory(pkg_dir) is False

    def test_is_not_python_package_empty(self, tmp_path: Path) -> None:
        """Test empty directory."""
        pkg_dir = tmp_path / "package"
        pkg_dir.mkdir()

        assert is_python_package_directory(pkg_dir) is False

