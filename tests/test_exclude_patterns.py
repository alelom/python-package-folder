"""Tests for exclude patterns functionality."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from python_package_folder import BuildManager, SubfolderBuildConfig
from python_package_folder.utils import read_exclude_patterns


@pytest.fixture
def test_project_with_exclude_patterns(tmp_path: Path) -> Path:
    """Create a test project with exclude patterns in pyproject.toml."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()

    # Create pyproject.toml with exclude patterns
    pyproject_content = """[project]
name = "test-package"
version = "0.1.0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/test_package"]

[tool.python-package-folder]
exclude-patterns = ["_SS", ".*_test.*", "sandbox"]
"""
    (project_root / "pyproject.toml").write_text(pyproject_content)

    # Create source directory structure
    src_dir = project_root / "src" / "test_package"
    src_dir.mkdir(parents=True)

    # Create regular files
    (src_dir / "__init__.py").write_text("")
    (src_dir / "module.py").write_text("def func(): pass")

    # Create files that should be excluded
    (src_dir / "module_test.py").write_text("# test file")
    (src_dir / "test_data.py").write_text("# test data")

    # Create directories that should be excluded
    ss_dir = src_dir / "data_storage" / "_SS"
    ss_dir.mkdir(parents=True)
    (ss_dir / "file.py").write_text("# SS file")

    sandbox_dir = src_dir / "sandbox"
    sandbox_dir.mkdir()
    (sandbox_dir / "file.py").write_text("# sandbox file")

    # Create nested excluded directory
    nested_ss = src_dir / "nested" / "_SS_nested"
    nested_ss.mkdir(parents=True)
    (nested_ss / "file.py").write_text("# nested SS file")

    return project_root


@pytest.fixture
def test_subfolder_project(tmp_path: Path) -> Path:
    """Create a test project with subfolder and exclude patterns."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()

    # Create pyproject.toml with exclude patterns
    pyproject_content = """[project]
name = "test-package"
version = "0.1.0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/test_package"]

[tool.python-package-folder]
exclude-patterns = ["_SS", ".*_test.*"]
"""
    (project_root / "pyproject.toml").write_text(pyproject_content)

    # Create subfolder
    subfolder = project_root / "subfolder"
    subfolder.mkdir()
    (subfolder / "__init__.py").write_text("")
    (subfolder / "module.py").write_text("def func(): pass")

    # Create files that should be excluded
    (subfolder / "module_test.py").write_text("# test file")
    ss_dir = subfolder / "_SS"
    ss_dir.mkdir()
    (ss_dir / "file.py").write_text("# SS file")

    return project_root


class TestReadExcludePatterns:
    """Tests for reading exclude patterns from pyproject.toml."""

    def test_read_exclude_patterns_exists(self, test_project_with_exclude_patterns: Path) -> None:
        """Test reading exclude patterns when they exist."""
        pyproject_path = test_project_with_exclude_patterns / "pyproject.toml"
        patterns = read_exclude_patterns(pyproject_path)

        assert len(patterns) == 3
        assert "_SS" in patterns
        assert ".*_test.*" in patterns
        assert "sandbox" in patterns

    def test_read_exclude_patterns_not_exists(self, tmp_path: Path) -> None:
        """Test reading exclude patterns when section doesn't exist."""
        pyproject_path = tmp_path / "pyproject.toml"
        pyproject_path.write_text("[project]\nname = 'test'")

        patterns = read_exclude_patterns(pyproject_path)
        assert patterns == []

    def test_read_exclude_patterns_file_not_exists(self, tmp_path: Path) -> None:
        """Test reading exclude patterns when file doesn't exist."""
        pyproject_path = tmp_path / "nonexistent.toml"
        patterns = read_exclude_patterns(pyproject_path)
        assert patterns == []


class TestExcludePatternsInBuild:
    """Tests for exclude patterns in build process."""

    def test_exclude_patterns_in_temp_pyproject(
        self, test_project_with_exclude_patterns: Path
    ) -> None:
        """Test that exclude patterns are injected into temporary pyproject.toml."""
        project_root = test_project_with_exclude_patterns
        src_dir = project_root / "src" / "test_package"

        # This is detected as a subfolder build
        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=src_dir,
            package_name="test-package",
            version="1.0.0",
        )

        temp_pyproject = config.create_temp_pyproject()
        assert temp_pyproject is not None

        # Check that exclude patterns are in the temporary pyproject.toml
        content = temp_pyproject.read_text()
        assert "[tool.python-package-folder]" in content
        assert "exclude-patterns" in content
        assert "_SS" in content
        assert ".*_test.*" in content
        assert "sandbox" in content

        config.restore()

    def test_exclude_patterns_subfolder_build(self, test_subfolder_project: Path) -> None:
        """Test that exclude patterns from root are applied to subfolder builds."""
        project_root = test_subfolder_project
        subfolder = project_root / "subfolder"

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            package_name="subfolder",
            version="1.0.0",
        )

        # Create temporary pyproject.toml
        temp_pyproject = config.create_temp_pyproject()
        assert temp_pyproject is not None

        # Check that exclude patterns are in the temporary pyproject.toml
        content = temp_pyproject.read_text()
        assert "[tool.python-package-folder]" in content
        assert "exclude-patterns" in content
        assert "_SS" in content
        assert ".*_test.*" in content

        config.restore()

    def test_exclude_patterns_no_subfolder_toml(self, test_project_with_exclude_patterns: Path) -> None:
        """Test that exclude patterns are read correctly when there's no subfolder pyproject.toml."""
        project_root = test_project_with_exclude_patterns
        src_dir = project_root / "src" / "test_package"

        # This simulates the scenario where there's no subfolder pyproject.toml
        # and we need to read exclude patterns from the root before it's moved
        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=src_dir,
            package_name="test-package",
            version="1.0.0",
        )

        # Create temporary pyproject.toml (this will read exclude patterns before moving root toml)
        temp_pyproject = config.create_temp_pyproject()
        assert temp_pyproject is not None

        # Check that exclude patterns are in the temporary pyproject.toml
        content = temp_pyproject.read_text()
        assert "[tool.python-package-folder]" in content
        assert "exclude-patterns" in content
        assert "_SS" in content
        assert ".*_test.*" in content
        assert "sandbox" in content

        # Verify there's only ONE [tool.python-package-folder] section (no duplicates)
        sections = [line for line in content.split("\n") if line.strip() == "[tool.python-package-folder]"]
        assert len(sections) == 1, f"Found {len(sections)} duplicate [tool.python-package-folder] sections"

        config.restore()

    def test_exclude_patterns_no_duplicate_section(self, tmp_path: Path) -> None:
        """Test that exclude patterns don't create duplicate sections when original already has it."""
        project_root = tmp_path / "test_project"
        project_root.mkdir()

        # Create pyproject.toml with existing [tool.python-package-folder] section
        pyproject_content = """[project]
name = "test-package"
version = "0.1.0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/test_package"]

[tool.python-package-folder]
exclude-patterns = ["_SS", ".*_test.*"]

[tool.pylint.'TYPECHECK']
generated-members = ["networkx.*"]
"""
        (project_root / "pyproject.toml").write_text(pyproject_content)

        # Create source directory
        src_dir = project_root / "src" / "test_package"
        src_dir.mkdir(parents=True)
        (src_dir / "__init__.py").write_text("")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=src_dir,
            package_name="test-package",
            version="1.0.0",
        )

        # Create temporary pyproject.toml
        temp_pyproject = config.create_temp_pyproject()
        assert temp_pyproject is not None

        # Check that there's only ONE [tool.python-package-folder] section
        content = temp_pyproject.read_text()
        sections = [line for line in content.split("\n") if line.strip() == "[tool.python-package-folder]"]
        assert len(sections) == 1, f"Found {len(sections)} duplicate [tool.python-package-folder] sections: {sections}"

        # Verify exclude-patterns is present
        assert "exclude-patterns" in content
        assert "_SS" in content

        config.restore()
