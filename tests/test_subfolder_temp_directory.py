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


class TestTemporaryPackageDirectory:
    """
    Tests for temporary package directory creation and cleanup.
    
    This class tests the temporary package directory functionality, including:
    - Directory creation with correct naming (matching Python import name)
    - File and directory copying from source to temporary directory
    - Cleanup and restoration of original state
    - Handling of __init__.py files in temporary directories
    - Exclusion patterns during copy operations
    
    File: test_subfolder_temp_directory.py
    When to add tests here: Tests for temporary directory creation, copying files/directories,
    cleanup, restoration, and exclusion pattern behavior should go in this class.
    """

    def test_temp_package_directory_created_with_correct_name(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test that temporary package directory is created with correct import name."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        (subfolder / "module.py").write_text("def func(): pass")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        # Package name should be "test-package-subfolder" (with hyphens)
        assert config.package_name == "test-package-subfolder"

        # Create temp pyproject (which creates temp package directory)
        config.create_temp_pyproject()

        # Temp package directory should exist with import name (underscores, no temp prefix)
        import_name = "test_package_subfolder"  # Import name from "test-package-subfolder"
        temp_package_dir = project_root / import_name
        assert temp_package_dir.exists()
        assert config._temp_package_dir == temp_package_dir

        # Temp package directory should contain the subfolder contents
        assert (temp_package_dir / "module.py").exists()

        # Cleanup
        config.restore()

    def test_temp_package_directory_uses_import_name(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test that temp package directory name converts hyphens to underscores."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        (subfolder / "module.py").write_text("def func(): pass")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
            package_name="my-custom-package",  # Package name with hyphens
        )

        config.create_temp_pyproject()

        # Temp directory should use underscores (import name, no temp prefix)
        import_name = "my_custom_package"  # Import name from "my-custom-package"
        temp_package_dir = project_root / import_name
        assert temp_package_dir.exists()
        assert config._temp_package_dir == temp_package_dir

        config.restore()

    def test_temp_package_directory_cleaned_up(self, test_project_with_pyproject: Path) -> None:
        """Test that temporary package directory is cleaned up on restore."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        (subfolder / "module.py").write_text("def func(): pass")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        config.create_temp_pyproject()

        # Verify temp directory exists
        temp_package_dir = config._temp_package_dir
        assert temp_package_dir is not None
        assert temp_package_dir.exists()

        # Restore should clean it up
        config.restore()

        # Temp directory should be removed
        assert not temp_package_dir.exists()
        assert config._temp_package_dir is None

    def test_packages_configuration_uses_temp_directory(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test that packages configuration uses temp directory path."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        (subfolder / "module.py").write_text("def func(): pass")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        pyproject_path = config.create_temp_pyproject()
        assert pyproject_path is not None

        content = pyproject_path.read_text()

        # Packages configuration should use import name (temp directory is renamed to import name)
        # Import name is "test_package_subfolder" (from "test-package-subfolder")
        assert '"test_package_subfolder"' in content or "'test_package_subfolder'" in content

        config.restore()

    def test_temp_package_directory_preserves_structure(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test that temp package directory preserves the original directory structure."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        (subfolder / "module.py").write_text("def func(): pass")
        (subfolder / "submodule").mkdir()
        (subfolder / "submodule" / "__init__.py").write_text("")
        (subfolder / "submodule" / "helper.py").write_text("def helper(): pass")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        config.create_temp_pyproject()

        temp_package_dir = config._temp_package_dir
        assert temp_package_dir is not None

        # Verify structure is preserved
        assert (temp_package_dir / "module.py").exists()
        assert (temp_package_dir / "submodule" / "__init__.py").exists()
        assert (temp_package_dir / "submodule" / "helper.py").exists()

        config.restore()

    def test_temp_package_directory_handles_existing_directory(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test that temp package directory creation handles existing directory."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        (subfolder / "module.py").write_text("def func(): pass")

        # Create a directory that would conflict (using import name directly)
        import_name = "test_package_subfolder"  # Import name from "test-package-subfolder"
        existing_temp_dir = project_root / import_name
        existing_temp_dir.mkdir()
        (existing_temp_dir / "old_file.py").write_text("# Old file")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        # Should remove existing directory and create new one
        config.create_temp_pyproject()

        temp_package_dir = config._temp_package_dir
        assert temp_package_dir is not None
        assert temp_package_dir.exists()
        # Should have new file, not old file
        assert (temp_package_dir / "module.py").exists()
        assert not (temp_package_dir / "old_file.py").exists()

        config.restore()

    def test_temp_package_directory_respects_exclude_patterns_without_matching_test_dirs(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that exclude patterns don't incorrectly match pytest temp directory names.
        
        This test ensures that exclude patterns like '.*test_.*' only match files/directories
        within the source directory, not the pytest temp directory name (e.g., 
        'test_real_world_ml_drawing_assistant_data_scenario').
        
        This is a regression test for the bug where all files were excluded because the
        exclude pattern matching checked the entire absolute path instead of just the
        relative path within src_dir.
        """
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        
        # Create files that should NOT be excluded
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text("def func(): pass")
        (subfolder / "utils.py").write_text("def util(): pass")
        
        # Create a file that SHOULD be excluded (matches pattern)
        (subfolder / "test_helper.py").write_text("def test(): pass")
        (subfolder / "_SS").mkdir()
        (subfolder / "_SS" / "excluded.py").write_text("# Should be excluded")
        
        # Update pyproject.toml with exclude patterns that could match test directory names
        pyproject_path = project_root / "pyproject.toml"
        pyproject_content = pyproject_path.read_text()
        # Add exclude patterns including ones that could match pytest temp dirs
        if "[tool.python-package-folder]" not in pyproject_content:
            pyproject_content += "\n[tool.python-package-folder]\n"
        pyproject_content += 'exclude-patterns = ["_SS", "__SS", ".*_test.*", ".*test_.*", "sandbox"]\n'
        pyproject_path.write_text(pyproject_content)
        
        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
            package_name="my-package",
        )
        
        # Create temp pyproject (which creates temp package directory with exclude patterns)
        config.create_temp_pyproject()
        
        temp_package_dir = config._temp_package_dir
        assert temp_package_dir is not None
        assert temp_package_dir.exists()
        
        # Files that should NOT be excluded should be copied
        assert (temp_package_dir / "__init__.py").exists(), (
            "__init__.py should be copied (doesn't match exclude patterns)"
        )
        assert (temp_package_dir / "module.py").exists(), (
            "module.py should be copied (doesn't match exclude patterns)"
        )
        assert (temp_package_dir / "utils.py").exists(), (
            "utils.py should be copied (doesn't match exclude patterns)"
        )
        
        # Files that SHOULD be excluded should NOT be copied
        assert not (temp_package_dir / "test_helper.py").exists(), (
            "test_helper.py should be excluded (matches '.*test_.*' pattern)"
        )
        assert not (temp_package_dir / "_SS").exists(), (
            "_SS directory should be excluded (matches '_SS' pattern)"
        )
        
        # Verify at least some files were copied (this would fail if all files were excluded)
        all_files = list(temp_package_dir.rglob("*"))
        all_files = [f for f in all_files if f.is_file()]
        assert len(all_files) >= 3, (
            f"Expected at least 3 files to be copied, but only found {len(all_files)}. "
            f"This suggests exclude patterns are incorrectly matching test directory names."
        )
        
        config.restore()

    def test_only_globals_file_copied_not_entire_src_directory(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that when a subfolder imports a file from src/ root (like _globals.py),
        only that file is copied, not the entire src/ directory.
        
        This is a regression test for the bug where the entire src/ directory
        (including features/, integration/, docs/, infrastructure/) was being
        copied when only _globals.py was needed.
        """
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        
        # Create a file in subfolder that imports _globals
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text(
            "from _globals import IS_TESTING\n\ndef func(): return IS_TESTING"
        )
        
        # Create _globals.py at root of src/ (outside subfolder)
        src_dir = project_root / "src"
        src_dir.mkdir(exist_ok=True)
        (src_dir / "_globals.py").write_text("IS_TESTING = False")
        
        # Create other directories in src/ that should NOT be copied
        (src_dir / "features").mkdir()
        (src_dir / "features" / "__init__.py").write_text("# Features")
        (src_dir / "features" / "feature.py").write_text("def feature(): pass")
        
        (src_dir / "integration").mkdir()
        (src_dir / "integration" / "__init__.py").write_text("# Integration")
        (src_dir / "integration" / "integration.py").write_text("def integration(): pass")
        
        (src_dir / "docs").mkdir()
        (src_dir / "docs" / "readme.md").write_text("# Docs")
        
        (src_dir / "infrastructure").mkdir()
        (src_dir / "infrastructure" / "__init__.py").write_text("# Infrastructure")
        
        # Build the subfolder
        manager = BuildManager(project_root=project_root, src_dir=subfolder)
        
        try:
            external_deps = manager.prepare_build(version="1.0.0", package_name="my-package")
            
            # Verify _globals.py was found as an external dependency
            globals_deps = [d for d in external_deps if d.source_path.name == "_globals.py"]
            assert len(globals_deps) > 0, "_globals.py should be found as an external dependency"
            
            # Verify the temp package directory exists
            assert manager.subfolder_config is not None
            temp_dir = manager.subfolder_config._temp_package_dir
            assert temp_dir is not None and temp_dir.exists()
            
            # Verify _globals.py was copied to temp directory
            assert (temp_dir / "_globals.py").exists(), "_globals.py should be copied to temp directory"
            
            # Verify other directories from src/ were NOT copied
            assert not (temp_dir / "features").exists(), (
                "features/ directory should NOT be copied (not imported)"
            )
            assert not (temp_dir / "integration").exists(), (
                "integration/ directory should NOT be copied (not imported)"
            )
            assert not (temp_dir / "docs").exists(), (
                "docs/ directory should NOT be copied (not imported)"
            )
            assert not (temp_dir / "infrastructure").exists(), (
                "infrastructure/ directory should NOT be copied (not imported)"
            )
            
            # Verify only _globals.py and subfolder contents are in temp directory
            all_items = list(temp_dir.iterdir())
            item_names = [item.name for item in all_items]
            
            # Should have _globals.py, __init__.py, module.py, and possibly pyproject.toml
            # But NOT features/, integration/, docs/, infrastructure/
            unexpected_dirs = {"features", "integration", "docs", "infrastructure"}
            found_unexpected = unexpected_dirs.intersection(set(item_names))
            assert len(found_unexpected) == 0, (
                f"Found unexpected directories in temp package: {found_unexpected}. "
                f"Only _globals.py should be copied, not the entire src/ directory."
            )
            
        finally:
            manager.cleanup()



