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



# This file has been split into multiple test files.
# See test_subfolder_*.py files for the actual tests.
