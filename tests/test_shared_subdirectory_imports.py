"""Tests for imports from _shared subdirectories."""

from __future__ import annotations

from pathlib import Path

import pytest

from python_package_folder import BuildManager, ImportAnalyzer, ImportInfo


@pytest.fixture
def test_project_with_shared(tmp_path: Path) -> Path:
    """Create a test project with _shared subdirectory."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()

    # Create src directory
    src_dir = project_root / "src"
    src_dir.mkdir()

    # Create _shared directory with better_enum.py
    shared_dir = src_dir / "_shared"
    shared_dir.mkdir()
    (shared_dir / "better_enum.py").write_text(
        """class Enum:
    pass
"""
    )

    # Create subfolder_to_build
    subfolder = src_dir / "integration" / "empty_drawing_detection"
    subfolder.mkdir(parents=True)
    (subfolder / "module.py").write_text(
        """from better_enum import Enum

def use_enum():
    return Enum
"""
    )

    return project_root


class TestSharedSubdirectoryImports:
    """Tests for imports from _shared subdirectories."""

    def test_resolve_better_enum_from_shared(self, test_project_with_shared: Path) -> None:
        """Test that better_enum is resolved from src/_shared/better_enum.py."""
        project_root = test_project_with_shared
        src_dir = project_root / "src" / "integration" / "empty_drawing_detection"

        analyzer = ImportAnalyzer(project_root)

        # Create import info for better_enum
        import_info = ImportInfo(
            module_name="better_enum",
            import_type="from",
            line_number=1,
            file_path=src_dir / "module.py",
        )

        # Classify the import
        analyzer.classify_import(import_info, src_dir)

        # Should be classified as external (not third_party)
        assert import_info.classification == "external"
        assert import_info.resolved_path is not None
        assert import_info.resolved_path.name == "better_enum.py"
        # Should resolve to src/_shared/better_enum.py
        assert "_shared" in str(import_info.resolved_path)
        assert import_info.resolved_path.exists()

    def test_better_enum_copied_not_added_as_dependency(
        self, test_project_with_shared: Path
    ) -> None:
        """Test that better_enum is copied as external dependency, not added as third-party."""
        project_root = test_project_with_shared
        src_dir = project_root / "src" / "integration" / "empty_drawing_detection"

        manager = BuildManager(project_root, src_dir)

        # Prepare build
        external_deps = manager.prepare_build(version="1.0.0", package_name="test-package")

        # Should find better_enum as an external dependency to copy
        better_enum_deps = [dep for dep in external_deps if "better_enum" in dep.import_name]
        assert len(better_enum_deps) > 0, "better_enum should be found as external dependency"

        # Verify _shared directory was copied (which contains better_enum.py)
        copied_shared_dir = src_dir / "_shared"
        assert copied_shared_dir.exists(), "_shared directory should be copied to subfolder"
        copied_file = copied_shared_dir / "better_enum.py"
        assert copied_file.exists(), "better_enum.py should be in copied _shared directory"

        # Check that subfolder_config exists (for subfolder builds)
        if manager.subfolder_config:
            # Read the temporary pyproject.toml
            pyproject_path = project_root / "pyproject.toml"
            if pyproject_path.exists():
                content = pyproject_path.read_text()
                # Should NOT have better-enum or better_enum in dependencies
                # (it should be copied, not added as dependency)
                assert '"better-enum"' not in content
                assert '"better_enum"' not in content

        manager.cleanup()
