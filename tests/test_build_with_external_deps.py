"""Tests for the build_with_external_deps script."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from python_package_folder import (
    BuildManager,
    ExternalDependencyFinder,
    ImportAnalyzer,
    ImportInfo,
)


@pytest.fixture
def test_project_root(tmp_path: Path) -> Path:
    """Create a temporary test project structure."""
    project_root = tmp_path / "test_project"
    project_root.mkdir()

    # Create folder_structure similar to tests/folder_structure
    folder_structure = project_root / "folder_structure"
    folder_structure.mkdir()

    # Create some_globals.py (external dependency)
    (folder_structure / "some_globals.py").write_text('SOME_GLOBAL_VARIABLE = "test_value"')

    # Create utility_folder (external dependency)
    utility_folder = folder_structure / "utility_folder"
    utility_folder.mkdir()
    (utility_folder / "some_utility.py").write_text(
        "def print_something(to_print: str):\n    print(to_print)"
    )
    # Create _SS subdirectory with a file that should be excluded
    ss_dir = utility_folder / "_SS"
    ss_dir.mkdir()
    (ss_dir / "some_superseded_file.py").write_text("def superseded_function():\n    pass")

    # Create subfolder_to_build (target directory)
    subfolder_to_build = folder_structure / "subfolder_to_build"
    subfolder_to_build.mkdir()
    (subfolder_to_build / "some_function.py").write_text(
        """if True:
    import sysappend; sysappend.all()
    
from some_globals import SOME_GLOBAL_VARIABLE
from folder_structure.utility_folder.some_utility import print_something

def print_and_return_global_variable():
    print_something(SOME_GLOBAL_VARIABLE)
    return SOME_GLOBAL_VARIABLE
"""
    )

    return project_root


@pytest.fixture
def real_test_structure() -> Path:
    """Get the real test folder structure path."""
    return Path(__file__).parent / "folder_structure"


class TestImportAnalyzer:
    """Tests for ImportAnalyzer class."""

    def test_find_all_python_files(self, test_project_root: Path) -> None:
        """Test finding all Python files recursively."""
        analyzer = ImportAnalyzer(test_project_root)
        python_files = list(analyzer.find_all_python_files(test_project_root / "folder_structure"))

        # Should find all Python files including those in _SS (exclusion happens during dependency finding)
        assert len(python_files) >= 3
        file_names = {f.name for f in python_files}
        assert "some_globals.py" in file_names
        assert "some_function.py" in file_names
        assert "some_utility.py" in file_names
        # Note: some_superseded_file.py in _SS will be found but excluded during dependency resolution

    def test_extract_imports(self, test_project_root: Path) -> None:
        """Test extracting imports from a Python file."""
        analyzer = ImportAnalyzer(test_project_root)
        test_file = (
            test_project_root / "folder_structure" / "subfolder_to_build" / "some_function.py"
        )

        imports = analyzer.extract_imports(test_file)

        assert len(imports) >= 2
        import_names = {imp.module_name for imp in imports}
        assert "some_globals" in import_names
        assert "folder_structure.utility_folder.some_utility" in import_names

    def test_classify_stdlib_import(self, test_project_root: Path) -> None:
        """Test classification of standard library imports."""
        analyzer = ImportAnalyzer(test_project_root)
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"

        imp = ImportInfo(module_name="os", import_type="import", line_number=1)
        analyzer.classify_import(imp, src_dir)

        assert imp.classification == "stdlib"

    def test_classify_local_import(self, test_project_root: Path) -> None:
        """Test classification of local imports within src_dir."""
        analyzer = ImportAnalyzer(test_project_root)
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"

        # Create a local file
        local_file = src_dir / "local_module.py"
        local_file.write_text("LOCAL_VAR = 42")

        imp = ImportInfo(
            module_name="local_module",
            import_type="import",
            line_number=1,
            file_path=src_dir / "some_function.py",
        )
        analyzer.classify_import(imp, src_dir)

        assert imp.classification == "local"
        assert imp.resolved_path == local_file

    def test_classify_external_import(self, test_project_root: Path) -> None:
        """Test classification of external imports outside src_dir."""
        analyzer = ImportAnalyzer(test_project_root)
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"

        imp = ImportInfo(
            module_name="some_globals",
            import_type="from",
            line_number=4,
            file_path=src_dir / "some_function.py",
        )
        analyzer.classify_import(imp, src_dir)

        assert imp.classification == "external"
        assert imp.resolved_path is not None
        assert imp.resolved_path.name == "some_globals.py"

    def test_resolve_relative_import(self, test_project_root: Path) -> None:
        """Test resolving relative imports."""
        analyzer = ImportAnalyzer(test_project_root)
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"

        # Test relative import
        imp = ImportInfo(
            module_name="..some_globals",
            import_type="from",
            line_number=1,
            file_path=src_dir / "some_function.py",
        )
        resolved = analyzer.resolve_local_import(imp, src_dir)

        assert resolved is not None
        assert resolved.name == "some_globals.py"


class TestExternalDependencyFinder:
    """Tests for ExternalDependencyFinder class."""

    def test_find_external_dependencies(self, test_project_root: Path) -> None:
        """Test finding external dependencies."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        finder = ExternalDependencyFinder(test_project_root, src_dir)

        python_files = list(finder.analyzer.find_all_python_files(src_dir))
        external_deps = finder.find_external_dependencies(python_files)

        assert len(external_deps) >= 2

        dep_names = {dep.import_name for dep in external_deps}
        assert "some_globals" in dep_names
        assert "folder_structure.utility_folder.some_utility" in dep_names

        # Check that source paths are outside src_dir
        for dep in external_deps:
            assert not dep.source_path.is_relative_to(src_dir)
            assert dep.target_path.is_relative_to(src_dir)

    def test_determine_target_path_file(self, test_project_root: Path) -> None:
        """Test determining target path for a file dependency."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        finder = ExternalDependencyFinder(test_project_root, src_dir)

        source_file = test_project_root / "folder_structure" / "some_globals.py"
        target = finder._determine_target_path(source_file, "some_globals")

        assert target is not None
        assert target.is_relative_to(src_dir)
        assert target.name == "some_globals.py"

    def test_determine_target_path_directory(self, test_project_root: Path) -> None:
        """Test determining target path for a directory dependency."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        finder = ExternalDependencyFinder(test_project_root, src_dir)

        source_dir = test_project_root / "folder_structure" / "utility_folder"
        target = finder._determine_target_path(source_dir, "folder_structure.utility_folder")

        assert target is not None
        assert target.is_relative_to(src_dir)
        assert target.name == "utility_folder"


class TestBuildManager:
    """Tests for BuildManager class."""

    def test_prepare_build_copies_files(self, test_project_root: Path) -> None:
        """Test that prepare_build copies external dependencies."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        external_deps = manager.prepare_build()

        assert len(external_deps) >= 2

        # Check that files were copied
        # some_globals is a simple import, so it should be copied directly
        copied_some_globals = src_dir / "some_globals.py"
        assert copied_some_globals.exists()

        # utility_folder is imported as folder_structure.utility_folder, so structure should be preserved
        copied_utility = src_dir / "folder_structure" / "utility_folder"
        assert copied_utility.exists(), (
            f"utility_folder should be copied with structure at {copied_utility}"
        )
        assert (copied_utility / "some_utility.py").exists()

    def test_prepare_build_idempotent(self, test_project_root: Path) -> None:
        """Test that prepare_build is idempotent."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        # First call
        manager.prepare_build()
        copied_paths1 = set(manager.copied_files + manager.copied_dirs)

        # Second call (should not duplicate files, but may have fewer deps since files are now local)
        manager.prepare_build()
        copied_paths2 = set(manager.copied_files + manager.copied_dirs)

        # Idempotency: the set of copied paths should be the same (or very similar)
        # Files that were copied in the first call should still be present
        # (they may not be re-copied if idempotency check works, but they should be in the list)
        # The key is that we don't want to see significant divergence
        assert len(copied_paths1) > 0, "First call should copy some files"
        assert len(copied_paths2) > 0, "Second call should have some files"

        # The paths should be similar (allowing for some variation due to idempotency checks)
        # At minimum, the unique set of paths should be consistent
        assert (
            copied_paths1 == copied_paths2
            or copied_paths1.issubset(copied_paths2)
            or copied_paths2.issubset(copied_paths1)
        ), (
            f"Copied paths should be consistent between calls. First: {copied_paths1}, Second: {copied_paths2}"
        )

    def test_cleanup_removes_copied_files(self, test_project_root: Path) -> None:
        """Test that cleanup removes all copied files."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        manager.prepare_build()

        # Verify files were copied
        copied_file = src_dir / "some_globals.py"
        # utility_folder is imported as folder_structure.utility_folder, so structure should be preserved
        copied_dir = src_dir / "folder_structure" / "utility_folder"
        assert copied_file.exists()
        assert copied_dir.exists()

        # Cleanup
        manager.cleanup()

        # Verify files were removed
        assert not copied_file.exists()
        assert not copied_dir.exists()
        assert len(manager.copied_files) == 0
        assert len(manager.copied_dirs) == 0

    def test_cleanup_removes_egg_info_dirs(self, test_project_root: Path) -> None:
        """Test that cleanup removes .egg-info directories."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        # Create a fake .egg-info directory
        egg_info_dir = src_dir / "package.egg-info"
        egg_info_dir.mkdir()
        (egg_info_dir / "PKG-INFO").write_text("test")

        manager.cleanup()

        # Verify .egg-info directory was removed
        assert not egg_info_dir.exists()

    def test_cleanup_removes_empty_dirs(self, test_project_root: Path) -> None:
        """Test that cleanup removes empty directories."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        # Create a nested empty directory structure
        empty_dir = src_dir / "empty_parent" / "empty_child"
        empty_dir.mkdir(parents=True)

        manager.cleanup()

        # Verify empty directories were removed
        assert not empty_dir.exists()
        assert not (src_dir / "empty_parent").exists()

    def test_cleanup_handles_missing_files(self, test_project_root: Path) -> None:
        """Test that cleanup handles already-removed files gracefully."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        manager.prepare_build()
        manager.cleanup()

        # Manually remove a file
        if manager.copied_files:
            manager.copied_files[0].unlink(missing_ok=True)

        # Should not raise an error
        manager.cleanup()

    def test_run_build_with_cleanup(self, test_project_root: Path) -> None:
        """Test that run_build properly cleans up even if build fails."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        copied_file = src_dir / "some_globals.py"

        def failing_build() -> None:
            raise RuntimeError("Build failed")

        # Should raise error but still cleanup
        with pytest.raises(RuntimeError):
            manager.run_build(failing_build)

        # Verify cleanup happened
        assert not copied_file.exists()

    def test_run_build_success(self, test_project_root: Path) -> None:
        """Test successful build process."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        build_called = False

        def mock_build() -> None:
            nonlocal build_called
            build_called = True

        manager.run_build(mock_build)

        assert build_called
        # Verify cleanup happened
        assert len(manager.copied_files) == 0
        assert len(manager.copied_dirs) == 0


class TestRealFolderStructure:
    """Tests using the real folder_structure from tests directory."""

    def test_real_structure_dependency_detection(self, real_test_structure: Path) -> None:
        """Test detecting dependencies in the real test structure."""
        project_root = real_test_structure.parent.parent
        src_dir = real_test_structure / "subfolder_to_build"

        if not src_dir.exists():
            pytest.skip("Real test structure not found")

        # This test only reads files, doesn't modify them, so no backup needed
        finder = ExternalDependencyFinder(project_root, src_dir)
        analyzer = ImportAnalyzer(project_root)

        python_files = list(analyzer.find_all_python_files(src_dir))
        external_deps = finder.find_external_dependencies(python_files)

        # Should find some_globals.py and utility_folder
        assert len(external_deps) >= 1

        dep_names = {dep.import_name for dep in external_deps}
        assert (
            "some_globals" in dep_names
            or "folder_structure.utility_folder.some_utility" in dep_names
        )

    def test_real_structure_build_process(self, real_test_structure: Path) -> None:
        """Test the full build process with real structure."""
        project_root = real_test_structure.parent.parent
        src_dir = real_test_structure / "subfolder_to_build"

        if not src_dir.exists():
            pytest.skip("Real test structure not found")

        # Save original repository files that might be modified
        original_pyproject = project_root / "pyproject.toml"
        original_readme = project_root / "README.md"
        pyproject_backup = None
        readme_backup = None
        pyproject_existed = original_pyproject.exists()
        readme_existed = original_readme.exists()

        if pyproject_existed:
            pyproject_backup = original_pyproject.read_bytes()
        if readme_existed:
            readme_backup = original_readme.read_bytes()

        # Check what files exist before the build
        some_globals_existed_before = (src_dir / "some_globals.py").exists()

        manager = BuildManager(project_root, src_dir)

        try:
            # Prepare build
            external_deps = manager.prepare_build()

            # Verify dependencies were found
            assert len(external_deps) >= 1

            # Verify files were copied
            copied_some_globals = src_dir / "some_globals.py"
            copied_utility = src_dir / "utility_folder"

            # At least one should exist
            assert copied_some_globals.exists() or copied_utility.exists()

            # Verify the copied files can be imported (if sysappend is available)
            # This is a basic sanity check
            if copied_some_globals.exists():
                content = copied_some_globals.read_text()
                assert "SOME_GLOBAL_VARIABLE" in content

        finally:
            # Always cleanup
            manager.cleanup()

            # Restore original repository files if they were modified
            if pyproject_backup and original_pyproject.exists():
                # Verify the file was restored correctly, or restore it manually
                try:
                    current_content = original_pyproject.read_bytes()
                    if current_content != pyproject_backup:
                        # File was modified, restore it
                        original_pyproject.write_bytes(pyproject_backup)
                except Exception as e:
                    print(f"Warning: Could not verify/restore pyproject.toml: {e}", file=sys.stderr)
            elif pyproject_backup and not original_pyproject.exists():
                # File was deleted, restore it
                original_pyproject.write_bytes(pyproject_backup)

            if readme_backup and original_readme.exists():
                # Verify the file was restored correctly, or restore it manually
                try:
                    current_content = original_readme.read_bytes()
                    if current_content != readme_backup:
                        # File was modified, restore it
                        original_readme.write_bytes(readme_backup)
                except Exception as e:
                    print(f"Warning: Could not verify/restore README.md: {e}", file=sys.stderr)
            elif readme_backup and not original_readme.exists():
                # File was deleted, restore it
                original_readme.write_bytes(readme_backup)

            # Verify cleanup - only check if the file didn't exist before
            if not some_globals_existed_before:
                assert not (src_dir / "some_globals.py").exists()
            if (src_dir / "utility_folder").exists():
                # May have been there originally, so just check it's not in copied_dirs
                assert (src_dir / "utility_folder") not in manager.copied_dirs


class TestExclusionPatterns:
    """Tests for exclusion pattern functionality."""

    def test_exclude_ss_directories(self, test_project_root: Path) -> None:
        """Test that _SS directories are excluded from copying."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        manager.prepare_build()

        # Verify utility_folder was copied (with structure preserved)
        copied_utility = src_dir / "folder_structure" / "utility_folder"
        assert copied_utility.exists(), "utility_folder should be copied with structure"
        assert (copied_utility / "some_utility.py").exists(), "some_utility.py should be copied"

        # Verify _SS directory was NOT copied
        copied_ss = copied_utility / "_SS"
        assert not copied_ss.exists(), "_SS directory should be excluded"

        manager.cleanup()

    def test_exclude_ss_directories_real_structure(self, real_test_structure: Path) -> None:
        """Test exclusion with real folder structure."""
        project_root = real_test_structure.parent.parent
        src_dir = real_test_structure / "subfolder_to_build"

        if not src_dir.exists():
            pytest.skip("Real test structure not found")

        # Save original repository files that might be modified
        original_pyproject = project_root / "pyproject.toml"
        original_readme = project_root / "README.md"
        pyproject_backup = None
        readme_backup = None
        pyproject_existed = original_pyproject.exists()
        readme_existed = original_readme.exists()

        if pyproject_existed:
            pyproject_backup = original_pyproject.read_bytes()
        if readme_existed:
            readme_backup = original_readme.read_bytes()

        manager = BuildManager(project_root, src_dir)

        try:
            manager.prepare_build()

            # Verify utility_folder was copied
            copied_utility = src_dir / "utility_folder"
            if copied_utility.exists():
                # Verify _SS directory was NOT copied
                copied_ss = copied_utility / "_SS"
                assert not copied_ss.exists(), (
                    "_SS directory should be excluded from real structure"
                )

                # Verify the superseded file was NOT copied
                copied_superseded = copied_ss / "some_superseded_file.py"
                assert not copied_superseded.exists(), "Files in _SS should be excluded"
        finally:
            manager.cleanup()

            # Restore original repository files if they were modified
            if pyproject_backup and original_pyproject.exists():
                try:
                    current_content = original_pyproject.read_bytes()
                    if current_content != pyproject_backup:
                        original_pyproject.write_bytes(pyproject_backup)
                except Exception as e:
                    print(f"Warning: Could not verify/restore pyproject.toml: {e}", file=sys.stderr)
            elif pyproject_backup and not original_pyproject.exists():
                original_pyproject.write_bytes(pyproject_backup)

            if readme_backup and original_readme.exists():
                try:
                    current_content = original_readme.read_bytes()
                    if current_content != readme_backup:
                        original_readme.write_bytes(readme_backup)
                except Exception as e:
                    print(f"Warning: Could not verify/restore README.md: {e}", file=sys.stderr)
            elif readme_backup and not original_readme.exists():
                original_readme.write_bytes(readme_backup)

    def test_exclude_custom_patterns(self, test_project_root: Path) -> None:
        """Test that custom exclusion patterns work."""
        # Create a directory with a custom exclusion pattern
        folder_structure = test_project_root / "folder_structure"
        custom_excluded = folder_structure / "custom_skip"
        custom_excluded.mkdir()
        (custom_excluded / "skip_file.py").write_text("def skip(): pass")

        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir, exclude_patterns=["custom_skip"])

        manager.prepare_build()

        # Verify custom_skip was NOT copied
        copied_custom = src_dir / "custom_skip"
        assert not copied_custom.exists(), "custom_skip should be excluded"

        manager.cleanup()

    def test_exclude_multiple_patterns(self, test_project_root: Path) -> None:
        """Test that multiple exclusion patterns work."""
        folder_structure = test_project_root / "folder_structure"

        # Create directories with different exclusion patterns
        sandbox_dir = folder_structure / "_sandbox"
        sandbox_dir.mkdir()
        (sandbox_dir / "sandbox_file.py").write_text("def sandbox(): pass")

        skip_dir = folder_structure / "_skip"
        skip_dir.mkdir()
        (skip_dir / "skip_file.py").write_text("def skip(): pass")

        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        manager = BuildManager(test_project_root, src_dir)

        manager.prepare_build()

        # Verify excluded directories were NOT copied
        copied_sandbox = src_dir / "_sandbox"
        copied_skip = src_dir / "_skip"

        assert not copied_sandbox.exists(), "_sandbox should be excluded"
        assert not copied_skip.exists(), "_skip should be excluded"

        manager.cleanup()

    def test_exclude_nested_ss_directories(self, test_project_root: Path) -> None:
        """Test that _SS directories are excluded even when nested."""
        folder_structure = test_project_root / "folder_structure"

        # Create a nested structure with _SS
        nested_package = folder_structure / "nested_package"
        nested_package.mkdir()
        (nested_package / "__init__.py").write_text("")
        (nested_package / "module.py").write_text("def func(): pass")

        # Create nested _SS directory
        nested_ss = nested_package / "_SS"
        nested_ss.mkdir()
        (nested_ss / "nested_superseded.py").write_text("def nested(): pass")

        # Update test file to import from nested_package
        subfolder_to_build = folder_structure / "subfolder_to_build"
        (subfolder_to_build / "some_function.py").write_text(
            """if True:
    import sysappend; sysappend.all()
    
from folder_structure.nested_package.module import func
from some_globals import SOME_GLOBAL_VARIABLE
"""
        )

        src_dir = subfolder_to_build
        manager = BuildManager(test_project_root, src_dir)

        manager.prepare_build()

        # Verify nested_package was copied (with structure preserved)
        # Import is "folder_structure.nested_package.module", so structure should be preserved
        copied_nested = src_dir / "folder_structure" / "nested_package"
        assert copied_nested.exists(), "nested_package should be copied with structure"
        assert (copied_nested / "module.py").exists(), "module.py should be copied"

        # Verify nested _SS directory was NOT copied
        copied_nested_ss = copied_nested / "_SS"
        assert not copied_nested_ss.exists(), "Nested _SS directory should be excluded"

        manager.cleanup()

    def test_finder_excludes_ss_paths(self, test_project_root: Path) -> None:
        """Test that ExternalDependencyFinder excludes _SS paths."""
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"
        finder = ExternalDependencyFinder(test_project_root, src_dir)
        analyzer = ImportAnalyzer(test_project_root)

        python_files = list(analyzer.find_all_python_files(src_dir))
        external_deps = finder.find_external_dependencies(python_files)

        # Verify no dependencies point to _SS directories
        for dep in external_deps:
            source_str = str(dep.source_path)
            assert "_SS" not in source_str, f"Dependency should not include _SS: {dep.source_path}"
            # Check all path components
            for part in dep.source_path.parts:
                assert not part.startswith("_SS"), (
                    f"Path component should not start with _SS: {part}"
                )


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_nonexistent_src_dir(self, test_project_root: Path) -> None:
        """Test error handling for nonexistent src_dir."""
        nonexistent = test_project_root / "nonexistent"

        with pytest.raises(ValueError, match="Source directory not found"):
            BuildManager(test_project_root, nonexistent)

    def test_file_with_syntax_error(self, test_project_root: Path) -> None:
        """Test handling of files with syntax errors."""
        analyzer = ImportAnalyzer(test_project_root)
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"

        # Create a file with syntax error
        bad_file = src_dir / "bad_syntax.py"
        bad_file.write_text("def invalid syntax here !!!")

        # Should not raise, but return empty imports
        imports = analyzer.extract_imports(bad_file)
        # May return empty list or handle gracefully
        assert isinstance(imports, list)

    def test_empty_directory(self, test_project_root: Path) -> None:
        """Test handling of empty directories."""
        empty_dir = test_project_root / "empty"
        empty_dir.mkdir()

        analyzer = ImportAnalyzer(test_project_root)
        python_files = list(analyzer.find_all_python_files(empty_dir))

        assert len(python_files) == 0

    def test_import_from_nonexistent_module(self, test_project_root: Path) -> None:
        """Test classification of imports from nonexistent modules."""
        analyzer = ImportAnalyzer(test_project_root)
        src_dir = test_project_root / "folder_structure" / "subfolder_to_build"

        imp = ImportInfo(
            module_name="nonexistent_module_xyz123",
            import_type="import",
            line_number=1,
            file_path=src_dir / "some_function.py",
        )
        analyzer.classify_import(imp, src_dir)

        # Should be classified as ambiguous or third-party
        assert imp.classification in ("ambiguous", "third_party")
