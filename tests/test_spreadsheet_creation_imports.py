"""Tests for imports from spreadsheet_creation subdirectory."""

from __future__ import annotations

from pathlib import Path

import pytest

from python_package_folder import BuildManager, ImportAnalyzer, ImportInfo


@pytest.fixture
def test_project_with_spreadsheet_creation(tmp_path: Path) -> Path:
    """Create a test project with spreadsheet_creation subdirectory."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()

    # Create src directory
    src_dir = project_root / "src"
    src_dir.mkdir()

    # Create data/spreadsheet_creation directory with files
    data_dir = src_dir / "data"
    data_dir.mkdir()
    spreadsheet_creation_dir = data_dir / "spreadsheet_creation"
    spreadsheet_creation_dir.mkdir()
    (spreadsheet_creation_dir / "spreadsheet_formatting_dataclasses.py").write_text(
        """class DataClass:
    pass
"""
    )
    (spreadsheet_creation_dir / "spreadsheet_utils.py").write_text(
        """def util_func():
    pass
"""
    )

    # Create subfolder_to_build
    subfolder = src_dir / "integration" / "empty_drawing_detection"
    subfolder.mkdir(parents=True)
    (subfolder / "module.py").write_text(
        """from spreadsheet_formatting_dataclasses import DataClass
from spreadsheet_utils import util_func

def use_spreadsheet():
    return DataClass, util_func
"""
    )

    return project_root


class TestSpreadsheetCreationImports:
    """Tests for imports from spreadsheet_creation subdirectory."""

    def test_resolve_spreadsheet_formatting_dataclasses(
        self, test_project_with_spreadsheet_creation: Path
    ) -> None:
        """Test that spreadsheet_formatting_dataclasses is resolved from data/spreadsheet_creation."""
        project_root = test_project_with_spreadsheet_creation
        src_dir = project_root / "src" / "integration" / "empty_drawing_detection"

        analyzer = ImportAnalyzer(project_root)

        # Create import info for spreadsheet_formatting_dataclasses
        import_info = ImportInfo(
            module_name="spreadsheet_formatting_dataclasses",
            import_type="from",
            line_number=1,
            file_path=src_dir / "module.py",
        )

        # Classify the import
        analyzer.classify_import(import_info, src_dir)

        # Should be classified as external (not third_party)
        assert import_info.classification == "external"
        assert import_info.resolved_path is not None
        assert import_info.resolved_path.name == "spreadsheet_formatting_dataclasses.py"
        # Should resolve to src/data/spreadsheet_creation/spreadsheet_formatting_dataclasses.py
        assert "spreadsheet_creation" in str(import_info.resolved_path)
        assert import_info.resolved_path.exists()

    def test_resolve_spreadsheet_utils(self, test_project_with_spreadsheet_creation: Path) -> None:
        """Test that spreadsheet_utils is resolved from data/spreadsheet_creation."""
        project_root = test_project_with_spreadsheet_creation
        src_dir = project_root / "src" / "integration" / "empty_drawing_detection"

        analyzer = ImportAnalyzer(project_root)

        # Create import info for spreadsheet_utils
        import_info = ImportInfo(
            module_name="spreadsheet_utils",
            import_type="from",
            line_number=2,
            file_path=src_dir / "module.py",
        )

        # Classify the import
        analyzer.classify_import(import_info, src_dir)

        # Should be classified as external (not third_party)
        assert import_info.classification == "external"
        assert import_info.resolved_path is not None
        assert import_info.resolved_path.name == "spreadsheet_utils.py"
        assert "spreadsheet_creation" in str(import_info.resolved_path)
        assert import_info.resolved_path.exists()

    def test_spreadsheet_modules_copied_not_added_as_dependencies(
        self, test_project_with_spreadsheet_creation: Path
    ) -> None:
        """Test that spreadsheet modules are copied, not added as dependencies."""
        project_root = test_project_with_spreadsheet_creation
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

        # Should find spreadsheet modules as external dependencies to copy
        spreadsheet_deps = [
            dep for dep in external_deps if "spreadsheet" in dep.import_name.lower()
        ]
        assert len(spreadsheet_deps) > 0, (
            "spreadsheet modules should be found as external dependencies"
        )

        # Verify spreadsheet_creation directory was copied
        copied_dir = src_dir / "spreadsheet_creation"
        assert copied_dir.exists(), "spreadsheet_creation directory should be copied"
        assert (copied_dir / "spreadsheet_formatting_dataclasses.py").exists(), (
            "spreadsheet_formatting_dataclasses.py should be copied"
        )
        assert (copied_dir / "spreadsheet_utils.py").exists(), (
            "spreadsheet_utils.py should be copied"
        )

        # Check that subfolder_config exists (for subfolder builds)
        if manager.subfolder_config:
            # Read the temporary pyproject.toml
            pyproject_path = project_root / "pyproject.toml"
            if pyproject_path.exists():
                content = pyproject_path.read_text()
                # Should NOT have spreadsheet-formatting-dataclasses or spreadsheet-utils in dependencies
                assert '"spreadsheet-formatting-dataclasses"' not in content
                assert '"spreadsheet-utils"' not in content
                assert '"spreadsheet_formatting_dataclasses"' not in content
                assert '"spreadsheet_utils"' not in content

        manager.cleanup()
