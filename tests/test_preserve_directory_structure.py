"""Tests for preserving directory structure when copying external dependencies."""

from __future__ import annotations

from pathlib import Path

import pytest

from python_package_folder import BuildManager, ExternalDependencyFinder


@pytest.fixture
def test_project_with_models_structure(tmp_path: Path) -> Path:
    """Create a test project with models/ structure under src/."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()

    # Create src directory
    src_dir = project_root / "src"
    src_dir.mkdir()

    # Create models/Information_extraction/_shared_ie/ structure
    models_dir = src_dir / "models"
    models_dir.mkdir()
    info_extraction_dir = models_dir / "Information_extraction"
    info_extraction_dir.mkdir()
    shared_ie_dir = info_extraction_dir / "_shared_ie"
    shared_ie_dir.mkdir()
    (shared_ie_dir / "__init__.py").write_text("")
    (shared_ie_dir / "ie_enums.py").write_text(
        """from enum import Enum

class TitleblockPlacement(Enum):
    TOP = "top"
    BOTTOM = "bottom"

class EmptyDrawingLikelihood(Enum):
    HIGH = "high"
    LOW = "low"
"""
    )

    # Create data/spreadsheet_creation/ structure
    data_dir = src_dir / "data"
    data_dir.mkdir()
    spreadsheet_creation_dir = data_dir / "spreadsheet_creation"
    spreadsheet_creation_dir.mkdir()
    (spreadsheet_creation_dir / "spreadsheet_formatting_dataclasses.py").write_text(
        """class DataClass:
    pass
"""
    )

    # Create subfolder_to_build
    subfolder = src_dir / "integration" / "empty_drawing_detection"
    subfolder.mkdir(parents=True)
    (subfolder / "detect_empty_drawings.py").write_text(
        """from models.Information_extraction._shared_ie.ie_enums import (
    TitleblockPlacement,
    EmptyDrawingLikelihood,
)
from data.spreadsheet_creation.spreadsheet_formatting_dataclasses import DataClass

def analyze_folder():
    return TitleblockPlacement.TOP, EmptyDrawingLikelihood.HIGH, DataClass()
"""
    )

    return project_root


class TestPreserveDirectoryStructure:
    """Tests for preserving directory structure when copying external dependencies."""

    def test_models_structure_preserved(self, test_project_with_models_structure: Path) -> None:
        """Test that models/ structure is preserved when copying."""
        project_root = test_project_with_models_structure
        src_dir = project_root / "src" / "integration" / "empty_drawing_detection"

        finder = ExternalDependencyFinder(project_root, src_dir)

        # Test target path for models file
        source_file = (
            project_root
            / "src"
            / "models"
            / "Information_extraction"
            / "_shared_ie"
            / "ie_enums.py"
        )
        target = finder._determine_target_path(
            source_file, "models.Information_extraction._shared_ie.ie_enums"
        )

        assert target is not None
        assert target.is_relative_to(src_dir)
        # Should preserve the structure: models/Information_extraction/_shared_ie/ie_enums.py
        assert "models" in str(target)
        assert "Information_extraction" in str(target)
        assert "_shared_ie" in str(target)
        assert target.name == "ie_enums.py"
        # Full path should be: src/integration/empty_drawing_detection/models/Information_extraction/_shared_ie/ie_enums.py
        expected_parts = ["models", "Information_extraction", "_shared_ie", "ie_enums.py"]
        for part in expected_parts:
            assert part in str(target)

    def test_data_structure_preserved(self, test_project_with_models_structure: Path) -> None:
        """Test that data/ structure is preserved when copying."""
        project_root = test_project_with_models_structure
        src_dir = project_root / "src" / "integration" / "empty_drawing_detection"

        finder = ExternalDependencyFinder(project_root, src_dir)

        # Test target path for data file
        source_file = (
            project_root
            / "src"
            / "data"
            / "spreadsheet_creation"
            / "spreadsheet_formatting_dataclasses.py"
        )
        target = finder._determine_target_path(
            source_file, "data.spreadsheet_creation.spreadsheet_formatting_dataclasses"
        )

        assert target is not None
        assert target.is_relative_to(src_dir)
        # Should preserve the structure: data/spreadsheet_creation/spreadsheet_formatting_dataclasses.py
        assert "data" in str(target)
        assert "spreadsheet_creation" in str(target)
        assert target.name == "spreadsheet_formatting_dataclasses.py"

    def test_build_manager_preserves_structure(
        self, test_project_with_models_structure: Path
    ) -> None:
        """Test that BuildManager preserves directory structure when copying."""
        project_root = test_project_with_models_structure
        src_dir = project_root / "src" / "integration" / "empty_drawing_detection"

        # Create pyproject.toml for the test
        (project_root / "pyproject.toml").write_text(
            """[project]
name = "test-package"
version = "0.1.0"

[tool.hatch.build.targets.wheel]
packages = ["src/test_package"]
"""
        )

        manager = BuildManager(project_root, src_dir)

        # Prepare build
        external_deps = manager.prepare_build(version="1.0.0", package_name="test-package")

        # Should find models and data as external dependencies
        models_deps = [dep for dep in external_deps if "models" in dep.import_name.lower()]
        data_deps = [dep for dep in external_deps if "data" in dep.import_name.lower()]

        assert len(models_deps) > 0, "models dependencies should be found"
        assert len(data_deps) > 0, "data dependencies should be found"

        # Verify models structure was copied with full path
        models_path = src_dir / "models" / "Information_extraction" / "_shared_ie" / "ie_enums.py"
        assert models_path.exists(), (
            "models/Information_extraction/_shared_ie/ie_enums.py should be copied with full structure"
        )

        # Verify data structure was copied with full path
        data_path = (
            src_dir / "data" / "spreadsheet_creation" / "spreadsheet_formatting_dataclasses.py"
        )
        assert data_path.exists(), (
            "data/spreadsheet_creation/spreadsheet_formatting_dataclasses.py should be copied with full structure"
        )

        manager.cleanup()
