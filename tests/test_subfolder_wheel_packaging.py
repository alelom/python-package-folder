"""Tests for subfolder build functionality."""

from __future__ import annotations

import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

import pytest

from python_package_folder import BuildManager, SubfolderBuildConfig


@pytest.fixture
def test_project_with_pyproject(tmp_path: Path) -> Path:
    """Create a test project with pyproject.toml."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()

    # Create pyproject.toml
    pyproject_content = """[project]
name = "test-package"
version = "0.1.0"
dynamic = ["version"]

[tool.hatch.version]
source = "uv-dynamic-versioning"

[tool.uv-dynamic-versioning]
vcs = "git"
style = "pep440"
bump = true

[tool.hatch.build.targets.wheel]
packages = ["src/test_package"]

[dependency-groups]
dev = [
    "pytest>=8.0.0",
    "pytest-cov>=4.0.0",
]
test = [
    "pytest>=8.0.0",
    "mypy>=1.0.0",
]
"""
    (project_root / "pyproject.toml").write_text(pyproject_content)

    # Create subfolder
    subfolder = project_root / "subfolder"
    subfolder.mkdir(exist_ok=True)
    (subfolder / "module.py").write_text("def func(): pass")

    return project_root


class TestWheelPackaging:
    """
    Tests to verify that wheels are correctly packaged with the right directory structure.
    
    This class tests wheel packaging verification, including:
    - Wheel file structure and contents
    - Package directory naming in wheels (must match Python import name)
    - Verification that package files are included (not just .dist-info)
    - Wheel inspection and validation
    
    File: test_subfolder_wheel_packaging.py
    When to add tests here: Tests for wheel file structure, package directory verification,
    and wheel inspection should go in this class.
    """

    def test_wheel_contains_package_directory_with_correct_name(self, tmp_path: Path) -> None:
        """Test that a built wheel contains the package directory with the correct import name."""
        project_root = tmp_path / "test_project"
        project_root.mkdir()

        # Create pyproject.toml
        pyproject_content = """[project]
name = "test-package"
version = "0.1.0"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
"""
        (project_root / "pyproject.toml").write_text(pyproject_content)

        # Create subfolder with package name that has hyphens
        subfolder = project_root / "src" / "data"
        subfolder.mkdir(parents=True)
        
        # Create some Python files
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text("def hello(): return 'world'")
        (subfolder / "utils.py").write_text("def util(): return 'helper'")

        # Package name with hyphens (like ml-drawing-assistant-data)
        package_name = "ml-drawing-assistant-data"
        import_name = "ml_drawing_assistant_data"  # Expected import name
        version = "1.0.0"

        # Build the wheel
        manager = BuildManager(project_root=project_root, src_dir=subfolder)
        
        def build_wheel() -> None:
            """Build the wheel using uv build."""
            subprocess.run(
                ["uv", "build", "--wheel"],
                cwd=project_root,
                check=True,
                capture_output=True,
            )

        try:
            # run_build will call prepare_build internally, so we don't need to call it explicitly
            manager.run_build(build_wheel, version=version, package_name=package_name)
        finally:
            manager.cleanup()



