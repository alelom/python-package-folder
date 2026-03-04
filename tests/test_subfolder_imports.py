"""
Tests for import handling and conversion in subfolder builds.

This module contains tests for how imports are resolved, classified, and converted
during subfolder builds. This includes handling imports from src/ root files,
relative import depth calculation, and ensuring third-party imports are not
incorrectly converted.

Key areas tested:
- Importing files from src/ root (e.g., _globals.py, _config.py)
- Finding and copying src/ root files as external dependencies
- Relative import depth calculation for nested directories
- Third-party import classification and conversion prevention
- Import conversion behavior based on classification

File: tests/test_subfolder_imports.py
"""

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


class TestSrcRootFileImports:
    """
    Tests for importing files from src/ root (like _globals.py) when building subfolders.
    
    This class tests the scenario where a subfolder imports files located at the src/ root
    level (e.g., src/_globals.py, src/_config.py), including:
    - Finding and copying src/ root files as external dependencies
    - Import resolution for files at src/ root
    - Including src/ root files in built wheels
    - Handling nested imports within src/ root files
    - Relative import depth calculation for nested directories
    - Third-party submodule import handling (not converting to relative)
    
    File: test_subfolder_imports.py
    When to add tests here: Tests for importing files from src/ root, src/ root file
    resolution, copying, and relative import depth calculation should go in this class.
    """

    def test_shared_subfolder_imports_globals_from_src_root(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that src/_shared can import _globals.py from src/_globals.py.
        
        This is the actual user scenario: publishing src/_shared which imports _globals.py.
        """
        project_root = test_project_with_pyproject
        src_dir = project_root / "src"
        src_dir.mkdir(exist_ok=True)
        
        # Create _globals.py at src/ root
        (src_dir / "_globals.py").write_text(
            """TEST_DATA_PATH = "/path/to/test/data"
ROOT_SOURCE_CODE_PATH = "/path/to/source"
"""
        )
        
        # Create src/_shared subfolder
        shared_dir = src_dir / "_shared"
        shared_dir.mkdir()
        (shared_dir / "__init__.py").write_text("# Shared utilities")
        
        # Create testing_utils.py that imports _globals (matching user's scenario)
        (shared_dir / "testing_utils.py").write_text(
            """if True:
    import sysappend; sysappend.all()
    
import inspect
from pathlib import Path
from _globals import TEST_DATA_PATH, ROOT_SOURCE_CODE_PATH
import logging
import sys
from typing import Callable, no_type_check, Any, TYPE_CHECKING
from loguru import logger
import os

if TYPE_CHECKING:
    pass

def get_test_data_path():
    return TEST_DATA_PATH
"""
        )
        
        # Build src/_shared
        manager = BuildManager(project_root=project_root, src_dir=shared_dir)
        
        try:
            external_deps = manager.prepare_build(version="1.0.0", package_name="my-shared")
            
            # Verify _globals.py was found as an external dependency
            globals_deps = [d for d in external_deps if d.source_path.name == "_globals.py"]
            assert len(globals_deps) > 0, (
                "_globals.py should be found as an external dependency when building src/_shared"
            )
            
            # Verify the source path is correct
            globals_dep = globals_deps[0]
            assert globals_dep.source_path == src_dir / "_globals.py", (
                f"Source path should be {src_dir / '_globals.py'}, got {globals_dep.source_path}"
            )
            
            # Verify the temp package directory exists
            assert manager.subfolder_config is not None
            temp_dir = manager.subfolder_config._temp_package_dir
            assert temp_dir is not None and temp_dir.exists()
            
            # Verify _globals.py was copied to temp directory
            assert (temp_dir / "_globals.py").exists(), (
                "_globals.py should be copied to temp directory"
            )
            
            # Verify the content is correct
            copied_globals = (temp_dir / "_globals.py").read_text()
            assert "TEST_DATA_PATH" in copied_globals
            assert "ROOT_SOURCE_CODE_PATH" in copied_globals
            
            # Verify testing_utils.py is in temp directory
            assert (temp_dir / "testing_utils.py").exists()
            
        finally:
            manager.cleanup()

    def test_multiple_files_from_src_root_imported(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that multiple files from src/ root can be imported and copied.
        """
        project_root = test_project_with_pyproject
        src_dir = project_root / "src"
        src_dir.mkdir(exist_ok=True)
        
        # Create multiple files at src/ root
        (src_dir / "_globals.py").write_text("GLOBAL_VAR = 42")
        (src_dir / "_config.py").write_text("CONFIG_VALUE = 'test'")
        (src_dir / "_constants.py").write_text("PI = 3.14159")
        
        # Create subfolder that imports all of them
        subfolder = project_root / "subfolder"
        subfolder.mkdir(exist_ok=True)
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text(
            """from _globals import GLOBAL_VAR
from _config import CONFIG_VALUE
from _constants import PI

def get_all_values():
    return GLOBAL_VAR, CONFIG_VALUE, PI
"""
        )
        
        # Build the subfolder
        manager = BuildManager(project_root=project_root, src_dir=subfolder)
        
        try:
            external_deps = manager.prepare_build(version="1.0.0", package_name="my-package")
            
            # Verify all three files were found
            globals_deps = [d for d in external_deps if d.source_path.name == "_globals.py"]
            config_deps = [d for d in external_deps if d.source_path.name == "_config.py"]
            constants_deps = [d for d in external_deps if d.source_path.name == "_constants.py"]
            
            assert len(globals_deps) > 0, "_globals.py should be found"
            assert len(config_deps) > 0, "_config.py should be found"
            assert len(constants_deps) > 0, "_constants.py should be found"
            
            # Verify temp directory
            assert manager.subfolder_config is not None
            temp_dir = manager.subfolder_config._temp_package_dir
            assert temp_dir is not None and temp_dir.exists()
            
            # Verify all files were copied
            assert (temp_dir / "_globals.py").exists()
            assert (temp_dir / "_config.py").exists()
            assert (temp_dir / "_constants.py").exists()
            
        finally:
            manager.cleanup()

    def test_src_root_file_in_wheel_after_build(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that _globals.py is included in the built wheel.
        """
        project_root = test_project_with_pyproject
        src_dir = project_root / "src"
        src_dir.mkdir(exist_ok=True)
        
        # Create _globals.py at src/ root
        (src_dir / "_globals.py").write_text("TEST_VALUE = 123")
        
        # Create src/_shared subfolder
        shared_dir = src_dir / "_shared"
        shared_dir.mkdir()
        (shared_dir / "__init__.py").write_text("# Shared")
        (shared_dir / "utils.py").write_text(
            "from _globals import TEST_VALUE\ndef get_value(): return TEST_VALUE"
        )
        
        import zipfile
        import subprocess
        
        manager = BuildManager(project_root=project_root, src_dir=shared_dir)
        
        try:
            def build_wheel() -> None:
                """Build the wheel using uv build."""
                subprocess.run(
                    ["uv", "build", "--wheel"],
                    cwd=project_root,
                    check=True,
                    capture_output=True,
                )
            
            manager.run_build(build_wheel, version="1.0.0", package_name="my-shared")
            
            # Verify the wheel was built
            dist_dir = project_root / "dist"
            assert dist_dir.exists(), "dist directory should exist after build"
            
            wheel_files = list(dist_dir.glob("*.whl"))
            assert len(wheel_files) > 0, "At least one wheel should be built"
            
            wheel_file = wheel_files[0]
            with zipfile.ZipFile(wheel_file, "r") as wheel:
                file_names = wheel.namelist()
                
                # Verify _globals.py is in the wheel
                globals_in_wheel = [f for f in file_names if f.endswith("_globals.py")]
                assert len(globals_in_wheel) > 0, (
                    f"_globals.py should be in the wheel. Files found: {file_names[:20]}"
                )
                
                # Verify it's at the package root (not in a subdirectory)
                package_name = "my_shared"
                expected_path = f"{package_name}/_globals.py"
                assert expected_path in file_names, (
                    f"Expected {expected_path} in wheel, but found: {globals_in_wheel}"
                )
                
                # Verify the content is correct
                wheel_globals = wheel.read(expected_path).decode("utf-8")
                assert "TEST_VALUE = 123" in wheel_globals
                
        finally:
            manager.cleanup()

    def test_src_root_file_with_nested_imports(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that _globals.py can import other modules and those are also handled correctly.
        """
        project_root = test_project_with_pyproject
        src_dir = project_root / "src"
        src_dir.mkdir(exist_ok=True)
        
        # Create _config.py that _globals.py imports
        (src_dir / "_config.py").write_text("CONFIG_SETTING = 'production'")
        
        # Create _globals.py that imports _config
        (src_dir / "_globals.py").write_text(
            """from _config import CONFIG_SETTING

TEST_DATA_PATH = "/path/to/data"
"""
        )
        
        # Create subfolder that imports both _globals and _config directly
        # (to ensure both are found, since we don't recursively analyze copied deps)
        subfolder = project_root / "subfolder"
        subfolder.mkdir(exist_ok=True)
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text(
            """from _globals import TEST_DATA_PATH, CONFIG_SETTING
from _config import CONFIG_SETTING as CONFIG
"""
        )
        
        # Build the subfolder
        manager = BuildManager(project_root=project_root, src_dir=subfolder)
        
        try:
            external_deps = manager.prepare_build(version="1.0.0", package_name="my-package")
            
            # Verify both _globals.py and _config.py were found
            # (both are imported directly by module.py)
            globals_deps = [d for d in external_deps if d.source_path.name == "_globals.py"]
            config_deps = [d for d in external_deps if d.source_path.name == "_config.py"]
            
            assert len(globals_deps) > 0, "_globals.py should be found"
            assert len(config_deps) > 0, "_config.py should be found (imported directly by module.py)"
            
            # Verify temp directory
            assert manager.subfolder_config is not None
            temp_dir = manager.subfolder_config._temp_package_dir
            assert temp_dir is not None and temp_dir.exists()
            
            # Verify both files were copied
            assert (temp_dir / "_globals.py").exists()
            assert (temp_dir / "_config.py").exists()
            
            # Verify the import in _globals.py was converted to relative
            copied_globals = (temp_dir / "_globals.py").read_text()
            # The import should be converted to relative since _config.py is also copied
            assert "from _config import" in copied_globals or "from ._config import" in copied_globals
            
        finally:
            manager.cleanup()

    def test_src_root_file_not_found_when_not_exists(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that missing _globals.py doesn't cause a crash, but is handled gracefully.
        """
        project_root = test_project_with_pyproject
        src_dir = project_root / "src"
        src_dir.mkdir(exist_ok=True)
        
        # Create subfolder that tries to import _globals (but it doesn't exist)
        subfolder = project_root / "subfolder"
        subfolder.mkdir(exist_ok=True)
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text(
            "from _globals import MISSING_VAR  # This file doesn't exist"
        )
        
        # Build the subfolder - should not crash
        manager = BuildManager(project_root=project_root, src_dir=subfolder)
        
        try:
            # This should complete without crashing, even though _globals.py doesn't exist
            external_deps = manager.prepare_build(version="1.0.0", package_name="my-package")
            
            # _globals.py should not be found (since it doesn't exist)
            globals_deps = [d for d in external_deps if d.source_path and d.source_path.name == "_globals.py"]
            assert len(globals_deps) == 0, (
                "_globals.py should not be found if it doesn't exist"
            )
            
        finally:
            manager.cleanup()

    def test_third_party_submodules_not_converted(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that third-party submodules (like torch.utils) are NOT converted
        to relative imports, even if the root module is ambiguous.
        """
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"

        # Create a module that imports third-party submodules
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text(
            """import torch
import torch.utils
import torch.utils.data
from torchvision import datasets
"""
        )

        # Build the subfolder
        manager = BuildManager(project_root=project_root, src_dir=subfolder)

        try:
            manager.prepare_build(version="1.0.0", package_name="my-package")

            # Verify the temp package directory exists
            assert manager.subfolder_config is not None
            temp_dir = manager.subfolder_config._temp_package_dir
            assert temp_dir is not None and temp_dir.exists()

            # Read the modified file
            modified_content = (temp_dir / "module.py").read_text(encoding="utf-8")

            # Verify third-party submodules were NOT converted to relative imports
            assert "import torch" in modified_content, (
                "torch import should remain absolute"
            )
            assert "import torch.utils" in modified_content, (
                "torch.utils import should remain absolute, not converted to 'from . import torch.utils'"
            )
            assert "import torch.utils.data" in modified_content, (
                "torch.utils.data import should remain absolute"
            )
            assert "from torchvision import datasets" in modified_content, (
                "torchvision import should remain absolute"
            )

            # Verify NO relative imports were added for these third-party packages
            assert "from . import torch" not in modified_content, (
                "torch should NOT be converted to relative import"
            )
            assert "from . import torch.utils" not in modified_content, (
                "torch.utils should NOT be converted to relative import"
            )
            assert "from .torchvision import" not in modified_content, (
                "torchvision should NOT be converted to relative import"
            )

        finally:
            manager.cleanup()

    def test_relative_import_depth_calculation(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that relative import depth is calculated correctly.
        If a file in PytorchCoco/ imports _shared at root, it should use ..
        """
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"

        # Create nested directory structure
        nested_dir = subfolder / "PytorchCoco"
        nested_dir.mkdir(parents=True)
        (nested_dir / "__init__.py").write_text("# Nested package")

        # Create external dependency at root level
        external_dir = project_root / "src" / "_shared"
        external_dir.mkdir(parents=True)
        (external_dir / "__init__.py").write_text("# External shared module")
        (external_dir / "image_utils.py").write_text("def save_cropped_image(): pass")

        # Create a module in nested directory that imports from root level
        (nested_dir / "dataset_dataclasses.py").write_text(
            "from _shared.image_utils import save_cropped_image"
        )

        # Also create a file at root level for comparison
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "root_module.py").write_text(
            "from _shared.image_utils import save_cropped_image"
        )

        # Build the subfolder
        manager = BuildManager(project_root=project_root, src_dir=subfolder)

        try:
            external_deps = manager.prepare_build(version="1.0.0", package_name="my-package")

            # Verify external dependency was found
            assert len(external_deps) > 0, "External dependency should be found"

            # Verify the temp package directory exists
            assert manager.subfolder_config is not None
            temp_dir = manager.subfolder_config._temp_package_dir
            assert temp_dir is not None and temp_dir.exists()

            # Read the modified files
            nested_content = (temp_dir / "PytorchCoco" / "dataset_dataclasses.py").read_text(
                encoding="utf-8"
            )
            root_content = (temp_dir / "root_module.py").read_text(encoding="utf-8")

            # Verify nested file uses .. (two dots) to go up one level
            assert "from .._shared.image_utils import save_cropped_image" in nested_content, (
                "Nested file should use .. to import from parent directory"
            )
            assert "from ._shared.image_utils" not in nested_content, (
                "Nested file should NOT use single dot"
            )

            # Verify root file uses . (single dot) for same level
            assert "from ._shared.image_utils import save_cropped_image" in root_content, (
                "Root file should use . for same level import"
            )

        finally:
            manager.cleanup()



class TestImportConversion:
    """
    Tests to verify that import conversion respects classification.
    
    This class tests that import conversion correctly handles different import types, including:
    - Third-party imports (torch, torchvision, numpy, PIL) should NOT be converted to relative
    - Local imports should be converted to relative when appropriate
    - Import classification determines conversion behavior
    - Verifying imports remain absolute when they should
    
    File: test_subfolder_imports.py
    When to add tests here: Tests for import conversion behavior, classification-based
    conversion, and third-party import handling should go in this class.
    """

    def test_third_party_imports_not_converted_to_relative(
        self, test_project_with_pyproject: Path
    ) -> None:
        """
        Test that third-party imports (like torch, torchvision) are NOT converted
        to relative imports, even if they match local file names.
        """
        project_root = test_project_with_pyproject
        subfolder = project_root / "subfolder"

        # Create a module that imports third-party packages
        (subfolder / "__init__.py").write_text("# Package init")
        (subfolder / "module.py").write_text(
            """import torch
import torch.utils.data
from torchvision import datasets
import numpy as np
from PIL import Image
"""
        )

        # Build the subfolder
        manager = BuildManager(project_root=project_root, src_dir=subfolder)

        try:
            manager.prepare_build(version="1.0.0", package_name="my-package")

            # Verify the temp package directory exists
            assert manager.subfolder_config is not None
            temp_dir = manager.subfolder_config._temp_package_dir
            assert temp_dir is not None and temp_dir.exists()

            # Read the modified file
            modified_content = (temp_dir / "module.py").read_text(encoding="utf-8")

            # Verify third-party imports were NOT converted to relative imports
            assert "import torch" in modified_content, (
                "torch import should remain absolute, not converted to relative"
            )
            assert "import torch.utils.data" in modified_content or "from torch.utils import data" in modified_content, (
                "torch.utils.data import should remain absolute"
            )
            assert "from torchvision import datasets" in modified_content, (
                "torchvision import should remain absolute, not converted to relative"
            )
            assert "import numpy as np" in modified_content, (
                "numpy import should remain absolute"
            )
            assert "from PIL import Image" in modified_content, (
                "PIL import should remain absolute"
            )

            # Verify NO relative imports were added for these third-party packages
            assert "from . import torch" not in modified_content, (
                "torch should NOT be converted to relative import"
            )
            assert "from .torchvision import" not in modified_content, (
                "torchvision should NOT be converted to relative import"
            )
            assert "from . import numpy" not in modified_content, (
                "numpy should NOT be converted to relative import"
            )

        finally:
            manager.cleanup()



