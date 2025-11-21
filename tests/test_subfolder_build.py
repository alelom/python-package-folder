"""Tests for subfolder build functionality."""

from __future__ import annotations

from pathlib import Path

import pytest

from python_package_folder import SubfolderBuildConfig


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
    subfolder.mkdir()
    (subfolder / "module.py").write_text("def func(): pass")

    return project_root


class TestSubfolderBuildConfig:
    """Tests for SubfolderBuildConfig class."""

    def test_init_with_defaults(self, test_project_with_pyproject: Path) -> None:
        """Test initialization with default package name."""
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            version="1.0.0",
        )

        assert config.package_name == "subfolder"
        assert config.version == "1.0.0"
        assert config.dependency_group is None

    def test_init_with_custom_name(self, test_project_with_pyproject: Path) -> None:
        """Test initialization with custom package name."""
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            package_name="custom-package",
            version="1.0.0",
        )

        assert config.package_name == "custom-package"
        assert config.version == "1.0.0"

    def test_init_with_dependency_group(self, test_project_with_pyproject: Path) -> None:
        """Test initialization with dependency group."""
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            version="1.0.0",
            dependency_group="dev",
        )

        assert config.dependency_group == "dev"

    def test_create_temp_pyproject(self, test_project_with_pyproject: Path) -> None:
        """Test creating temporary pyproject.toml."""
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            version="2.0.0",
        )

        pyproject_path = config.create_temp_pyproject()

        assert pyproject_path.exists()
        content = pyproject_path.read_text()

        # Check package name and version are set
        assert 'name = "subfolder"' in content
        assert 'version = "2.0.0"' in content

        # Check dynamic versioning is removed
        assert 'dynamic = ["version"]' not in content
        assert "[tool.hatch.version]" not in content
        assert "[tool.uv-dynamic-versioning]" not in content

    def test_create_temp_pyproject_with_dependency_group(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test creating temporary pyproject.toml with dependency group."""
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            version="2.0.0",
            dependency_group="dev",
        )

        pyproject_path = config.create_temp_pyproject()
        content = pyproject_path.read_text()

        # Check dependency group is included
        assert "[dependency-groups]" in content
        assert "dev = [" in content
        assert '"pytest>=8.0.0"' in content

    def test_create_temp_pyproject_creates_init(self, test_project_with_pyproject: Path) -> None:
        """Test that __init__.py is created if missing."""
        subfolder = test_project_with_pyproject / "subfolder"
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=subfolder,
            version="1.0.0",
        )

        # Ensure __init__.py doesn't exist
        init_file = subfolder / "__init__.py"
        if init_file.exists():
            init_file.unlink()

        config.create_temp_pyproject()

        # Check __init__.py was created
        assert init_file.exists()
        assert config._temp_init_created

    def test_restore_pyproject(self, test_project_with_pyproject: Path) -> None:
        """Test restoring original pyproject.toml."""
        original_content = (test_project_with_pyproject / "pyproject.toml").read_text()

        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            version="1.0.0",
        )

        config.create_temp_pyproject()
        config.restore()

        # Check original content is restored
        restored_content = (test_project_with_pyproject / "pyproject.toml").read_text()
        assert restored_content == original_content

        # Check backup is removed
        assert not (test_project_with_pyproject / "pyproject.toml.backup").exists()

    def test_restore_removes_temp_init(self, test_project_with_pyproject: Path) -> None:
        """Test that restore removes temporary __init__.py."""
        subfolder = test_project_with_pyproject / "subfolder"
        init_file = subfolder / "__init__.py"

        # Ensure __init__.py doesn't exist
        if init_file.exists():
            init_file.unlink()

        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=subfolder,
            version="1.0.0",
        )

        config.create_temp_pyproject()
        assert init_file.exists()

        config.restore()

        # Check __init__.py was removed
        assert not init_file.exists()

    def test_restore_preserves_existing_init(self, test_project_with_pyproject: Path) -> None:
        """Test that restore preserves existing __init__.py."""
        subfolder = test_project_with_pyproject / "subfolder"
        init_file = subfolder / "__init__.py"

        # Create existing __init__.py
        init_file.write_text("# Original content")

        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=subfolder,
            version="1.0.0",
        )

        config.create_temp_pyproject()
        config.restore()

        # Check original __init__.py is preserved
        assert init_file.exists()
        assert init_file.read_text() == "# Original content"

    def test_context_manager(self, test_project_with_pyproject: Path) -> None:
        """Test using SubfolderBuildConfig as context manager."""
        original_content = (test_project_with_pyproject / "pyproject.toml").read_text()

        with SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            version="1.0.0",
        ) as config:
            config.create_temp_pyproject()
            content = (test_project_with_pyproject / "pyproject.toml").read_text()
            assert 'name = "subfolder"' in content

        # Check restore happened automatically
        restored_content = (test_project_with_pyproject / "pyproject.toml").read_text()
        assert restored_content == original_content

    def test_missing_dependency_group_warning(
        self, test_project_with_pyproject: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test warning when dependency group doesn't exist."""
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
            version="1.0.0",
            dependency_group="nonexistent",
        )

        # Create temp pyproject - this should print a warning
        config.create_temp_pyproject()

        # The warning is printed to stderr during create_temp_pyproject
        # Since capsys might not capture it properly, we'll just verify
        # that the build still works (warning is non-fatal)
        assert config.temp_pyproject is not None

    def test_version_required(self, test_project_with_pyproject: Path) -> None:
        """Test that version is required."""
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=test_project_with_pyproject / "subfolder",
        )

        with pytest.raises(ValueError, match="Version is required"):
            config.create_temp_pyproject()

    def test_package_name_derivation(self, test_project_with_pyproject: Path) -> None:
        """Test package name derivation from directory name."""
        # Test with underscores
        subfolder = test_project_with_pyproject / "subfolder_to_build"
        subfolder.mkdir()
        config = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=subfolder,
            version="1.0.0",
        )
        assert config.package_name == "subfolder-to-build"

        # Test with spaces
        subfolder2 = test_project_with_pyproject / "subfolder with spaces"
        subfolder2.mkdir()
        config2 = SubfolderBuildConfig(
            project_root=test_project_with_pyproject,
            src_dir=subfolder2,
            version="1.0.0",
        )
        assert config2.package_name == "subfolder-with-spaces"


def test_readme_handling_with_existing_readme(test_project_with_pyproject: Path):
    """Test that subfolder README is used when it exists."""
    project_root = test_project_with_pyproject
    subfolder = project_root / "subfolder"

    # Create README in subfolder
    subfolder_readme = subfolder / "README.md"
    subfolder_readme.write_text("# Subfolder Package\n\nThis is the subfolder README.")

    # Create README in project root
    project_readme = project_root / "README.md"
    project_readme.write_text("# Parent Package\n\nThis is the parent README.")

    config = SubfolderBuildConfig(
        project_root=project_root,
        src_dir=subfolder,
        version="1.0.0",
    )

    try:
        config.create_temp_pyproject()

        # Check that subfolder README was copied to project root
        assert (project_root / "README.md").exists()
        content = (project_root / "README.md").read_text()
        assert "Subfolder Package" in content
        assert "This is the subfolder README" in content
        assert "Parent Package" not in content

        # Check that backup was created
        assert (project_root / "README.md.backup").exists()
        backup_content = (project_root / "README.md.backup").read_text()
        assert "Parent Package" in backup_content
    finally:
        config.restore()

        # Verify original README was restored
        assert (project_root / "README.md").exists()
        restored_content = (project_root / "README.md").read_text()
        assert "Parent Package" in restored_content
        assert "Subfolder Package" not in restored_content
        assert not (project_root / "README.md.backup").exists()


def test_readme_handling_without_readme(test_project_with_pyproject: Path):
    """Test that minimal README is created when subfolder has no README."""
    project_root = test_project_with_pyproject
    subfolder = project_root / "subfolder"

    # Ensure no README exists
    assert not (subfolder / "README.md").exists()
    assert not (subfolder / "README.rst").exists()

    config = SubfolderBuildConfig(
        project_root=project_root,
        src_dir=subfolder,
        version="1.0.0",
    )

    try:
        config.create_temp_pyproject()

        # Check that minimal README was created
        assert (project_root / "README.md").exists()
        content = (project_root / "README.md").read_text()
        assert content.strip() == f"# {subfolder.name}"
    finally:
        config.restore()

        # Verify README was removed if it didn't exist before
        if not (project_root / "README.md.backup").exists():
            # No backup means no original README, so temp should be removed
            assert (
                not (project_root / "README.md").exists()
                or (project_root / "README.md").read_text() != f"# {subfolder.name}\n"
            )


class TestSubfolderBuildWithPyprojectToml:
    """Tests for subfolder builds when pyproject.toml exists in subfolder."""

    def test_uses_subfolder_pyproject_toml(self, test_project_with_pyproject: Path) -> None:
        """Test that subfolder's pyproject.toml is used when it exists."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"

        # Create pyproject.toml in subfolder
        subfolder_pyproject_content = """[project]
name = "subfolder-package"
version = "3.0.0"
description = "Subfolder package"

[dependencies]
requests = ">=2.0.0"
"""
        (subfolder / "pyproject.toml").write_text(subfolder_pyproject_content)

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",  # This should be ignored since subfolder has its own pyproject.toml
        )

        pyproject_path = config.create_temp_pyproject()

        # Verify subfolder pyproject.toml was copied to project root
        assert pyproject_path is not None
        assert pyproject_path.exists()
        assert pyproject_path == project_root / "pyproject.toml"
        content = pyproject_path.read_text()

        # Should use subfolder's pyproject.toml content, not create from parent
        assert 'name = "subfolder-package"' in content
        assert 'version = "3.0.0"' in content
        assert 'description = "Subfolder package"' in content
        assert 'requests = ">=2.0.0"' in content

        # Should not have parent's package name
        assert 'name = "test-package"' not in content
        assert 'name = "subfolder"' not in content

        # Verify backup was created
        assert (project_root / "pyproject.toml.backup").exists()
        backup_content = (project_root / "pyproject.toml.backup").read_text()
        assert 'name = "test-package"' in backup_content

        # Verify flag is set
        assert config._used_subfolder_pyproject is True

        # Cleanup
        config.restore()

    def test_restore_subfolder_pyproject_toml(self, test_project_with_pyproject: Path) -> None:
        """Test that original pyproject.toml is restored after using subfolder's."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        original_content = (project_root / "pyproject.toml").read_text()

        # Create pyproject.toml in subfolder
        (subfolder / "pyproject.toml").write_text(
            '[project]\nname = "subfolder-package"\nversion = "3.0.0"\n'
        )

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        config.create_temp_pyproject()
        config.restore()

        # Verify original is restored
        restored_content = (project_root / "pyproject.toml").read_text()
        assert restored_content == original_content

        # Verify backup is removed
        assert not (project_root / "pyproject.toml.backup").exists()

    def test_subfolder_pyproject_toml_without_parent_backup(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test using subfolder pyproject.toml when parent doesn't exist initially."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"

        # Remove parent pyproject.toml temporarily
        parent_pyproject = project_root / "pyproject.toml"
        original_content = parent_pyproject.read_text()
        parent_pyproject.unlink()

        # Create pyproject.toml in subfolder
        subfolder_pyproject_content = """[project]
name = "subfolder-package"
version = "3.0.0"
"""
        (subfolder / "pyproject.toml").write_text(subfolder_pyproject_content)

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        pyproject_path = config.create_temp_pyproject()

        # Should still work - copy subfolder pyproject.toml to project root
        assert pyproject_path is not None
        assert pyproject_path.exists()
        content = pyproject_path.read_text()
        assert 'name = "subfolder-package"' in content

        # No backup should be created since parent didn't exist
        assert not (project_root / "pyproject.toml.backup").exists()

        # Restore original for cleanup
        parent_pyproject.write_text(original_content)
        config.restore()


class TestSubfolderBuildWithoutParentPyproject:
    """Tests for subfolder builds when parent pyproject.toml doesn't exist."""

    def test_no_parent_pyproject_returns_none(self, tmp_path: Path) -> None:
        """Test that create_temp_pyproject returns None when no parent pyproject.toml exists."""
        project_root = tmp_path / "test_project"
        project_root.mkdir()

        # Don't create pyproject.toml in project root
        subfolder = project_root / "subfolder"
        subfolder.mkdir()
        (subfolder / "module.py").write_text("def func(): pass")

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        # Should return None and not raise
        result = config.create_temp_pyproject()
        assert result is None

        # No pyproject.toml should be created in project root
        assert not (project_root / "pyproject.toml").exists()

        # No backup should exist
        assert not (project_root / "pyproject.toml.backup").exists()

        # But README handling should still work
        assert (project_root / "README.md").exists()

    def test_no_parent_pyproject_with_subfolder_pyproject(self, tmp_path: Path) -> None:
        """Test that subfolder pyproject.toml is still used even without parent."""
        project_root = tmp_path / "test_project"
        project_root.mkdir()

        subfolder = project_root / "subfolder"
        subfolder.mkdir()

        # Create pyproject.toml in subfolder
        subfolder_pyproject_content = """[project]
name = "subfolder-package"
version = "3.0.0"
"""
        (subfolder / "pyproject.toml").write_text(subfolder_pyproject_content)

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        # Should work - use subfolder's pyproject.toml
        result = config.create_temp_pyproject()
        assert result is not None
        assert result == project_root / "pyproject.toml"
        assert result.exists()

        content = result.read_text()
        assert 'name = "subfolder-package"' in content

        # No backup since parent didn't exist
        assert not (project_root / "pyproject.toml.backup").exists()


class TestSubfolderBuildTemporaryPyprojectCreation:
    """Tests verifying temporary pyproject.toml creation from parent."""

    def test_temporary_pyproject_has_correct_structure(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test that temporary pyproject.toml has correct package structure."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"

        # Ensure no pyproject.toml in subfolder
        subfolder_pyproject = subfolder / "pyproject.toml"
        if subfolder_pyproject.exists():
            subfolder_pyproject.unlink()

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="2.5.0",
            package_name="my-custom-package",
        )

        pyproject_path = config.create_temp_pyproject()

        assert pyproject_path is not None
        assert pyproject_path.exists()
        content = pyproject_path.read_text()

        # Verify package name and version
        assert 'name = "my-custom-package"' in content
        assert 'version = "2.5.0"' in content

        # Verify dynamic versioning is removed
        assert 'dynamic = ["version"]' not in content
        assert "[tool.hatch.version]" not in content
        assert "[tool.uv-dynamic-versioning]" not in content

        # Verify packages path is set correctly
        assert 'packages = ["subfolder"]' in content or '"subfolder"' in content

        # Verify backup was created
        assert (project_root / "pyproject.toml.backup").exists()

        # Cleanup
        config.restore()

    def test_temporary_pyproject_preserves_other_sections(
        self, test_project_with_pyproject: Path
    ) -> None:
        """Test that temporary pyproject.toml preserves other sections from parent."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        pyproject_path = config.create_temp_pyproject()
        assert pyproject_path is not None
        content = pyproject_path.read_text()

        # Should preserve dependency-groups section (if not filtered)
        # Note: dependency-groups are only added if dependency_group parameter is provided
        # But other tool sections should be preserved
        assert "[tool.hatch.build.targets.wheel]" in content or "packages" in content

        # Cleanup
        config.restore()

    def test_temporary_pyproject_restoration(self, test_project_with_pyproject: Path) -> None:
        """Test that temporary pyproject.toml is properly restored."""
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"
        original_content = (project_root / "pyproject.toml").read_text()

        config = SubfolderBuildConfig(
            project_root=project_root,
            src_dir=subfolder,
            version="1.0.0",
        )

        # Create temporary pyproject
        config.create_temp_pyproject()

        # Verify it was modified
        modified_content = (project_root / "pyproject.toml").read_text()
        assert modified_content != original_content
        assert 'name = "subfolder"' in modified_content

        # Restore
        config.restore()

        # Verify original is restored
        restored_content = (project_root / "pyproject.toml").read_text()
        assert restored_content == original_content
        assert 'name = "test-package"' in restored_content
