# Usage Guide

## How does `python-package-folder` work?

### Build Process

1. **Import Extraction**: Uses Python's AST module to parse all `.py` files and extract import statements
2. **Classification**: Each import is classified as:
   - **stdlib**: Standard library modules
   - **third_party**: Packages installed in site-packages
   - **local**: Modules within the source directory
   - **external**: Modules outside source directory but in the project
   - **ambiguous**: Cannot be resolved
3. **Dependency Resolution**: For external imports, the tool resolves the file path by checking:
   - Parent directories of the source directory
   - Project root and its subdirectories
   - Relative import paths
4. **File Copying**: External dependencies are temporarily copied into the source directory
5. **Build Execution**: Your build command runs with all dependencies in place
6. **Cleanup**: All temporarily copied files are removed after build

### Publishing Process

1. **Build Verification**: Ensures distribution files exist in the `dist/` directory
2. **File Filtering**: Automatically filters distribution files to only include those matching the current package name and version (prevents uploading old artifacts)
3. **Credential Management**: 
   - Prompts for credentials if not provided via command-line arguments
   - Credentials are not stored - you'll be prompted each time (unless provided via `--username` and `--password`)
   - Supports both username/password and API tokens
   - Auto-detects API tokens and uses `__token__` as username
4. **Repository Configuration**: Configures the target repository (PyPI, TestPyPI, or Azure)
5. **Upload**: Uses `twine` to upload distribution files to the repository
6. **Verification**: Confirms successful upload

### Subfolder Build Process

1. **Project Root Detection**: Searches parent directories for `pyproject.toml`
2. **Source Directory Detection**: Uses current directory if it contains Python files, otherwise falls back to `project_root/src`
3. **Package Initialization**: Creates temporary `__init__.py` if subfolder doesn't have one (required for hatchling)
4. **README Handling**: 
   - Checks for README files in the subfolder (README.md, README.rst, README.txt, or README)
   - If found, copies the subfolder README to project root (backing up the original parent README)
   - If not found, creates a minimal README with just the folder name
5. **Configuration Creation**: Creates temporary `pyproject.toml` with:
   - `[build-system]` section using hatchling (replaces any existing build-system configuration)
   - Subfolder-specific package name (derived or custom)
   - Specified version
   - Correct package path for hatchling
6. **Build Execution**: Runs build command with all dependencies in place
7. **Cleanup**: Restores original `pyproject.toml` and removes temporary `__init__.py`

### How does building from Subdirectories work?

This is useful for monorepos containing many subfolders that may need publishing as stand-alone packages for external usage.  
The tool automatically detects the project root by searching for `pyproject.toml` in parent directories.  
This allows you to build subfolders of a main project as separate packages:

```bash
# From a subdirectory, the tool will:
# 1. Find pyproject.toml in parent directories (project root)
# 2. Use current directory as source if it contains Python files
# 3. Build with dependencies from the parent project
# 4. Create a temporary build config with subfolder-specific name and version

cd my_project/subfolder_to_build
python-package-folder --version "1.0.0" --publish pypi
```

The tool **automatically detects** when you're building a subfolder (any directory that's not the main `src/` directory) and sets up the appropriate build configuration.

The tool automatically:
- **Detects subfolder builds**: Automatically identifies when building from a subdirectory
- Finds the project root by looking for `pyproject.toml` in parent directories
- Uses the current directory as the source directory if it contains Python files
- Falls back to `project_root/src` if the current directory isn't suitable
- **For subfolder builds**: Handles `pyproject.toml` configuration:
  - **If `pyproject.toml` exists in subfolder**: Uses that file (copies it to project root temporarily, adjusting package paths and ensuring `[build-system]` uses hatchling)
  - **If no `pyproject.toml` in subfolder**: Creates a temporary `pyproject.toml` with:
    - `[build-system]` section using hatchling (always uses hatchling, even if parent uses setuptools)
    - Package name derived from the subfolder name (e.g., `empty_drawing_detection` → `empty-drawing-detection`)
    - Version from `--version` argument (defaults to `0.0.0` with a warning if not provided)
    - Proper package path configuration for hatchling
    - Dependency groups from parent `pyproject.toml` if specified
- Creates temporary `__init__.py` files if needed to make subfolders valid Python packages
- **README handling for subfolder builds**:
  - If a README file (README.md, README.rst, README.txt, or README) exists in the subfolder, it will be used instead of the parent README
  - If no README exists in the subfolder, a minimal README with just the folder name will be created
- Restores the original `pyproject.toml` after build (unless `--no-restore-versioning` is used)
- Cleans up temporary `__init__.py` files after build

**Note**: While version is not strictly required (defaults to `0.0.0`), it's recommended to specify `--version` for subfolder builds to ensure proper versioning.

**Subfolder Build Example:**
```bash
# Build a subfolder as a separate package
cd tests/folder_structure/subfolder_to_build
python-package-folder --version "0.1.0" --package-name "my-subfolder-package" --publish pypi

# Build with a specific dependency group from parent pyproject.toml
python-package-folder --version "0.1.0" --dependency-group "dev" --publish pypi

# If subfolder has its own pyproject.toml, it will be used automatically
# (package-name and version arguments are ignored in this case)
cd src/integration/my_package  # assuming my_package/pyproject.toml exists
python-package-folder --publish pypi
```

**Dependency Groups**: When building a subfolder, you can specify a dependency group from the parent `pyproject.toml` to include in the subfolder's build configuration. This allows subfolders to inherit specific dependencies from the parent project:

```bash
# Use the 'dev' dependency group from parent pyproject.toml
python-package-folder --version "1.0.0" --dependency-group "dev" --publish pypi
```

The specified dependency group will be copied from the parent `pyproject.toml`'s `[dependency-groups]` section into the temporary `pyproject.toml` used for the subfolder build.

## Python API Usage

You can also use the package programmatically:

### Basic Usage

```python
from pathlib import Path
from python_package_folder import BuildManager

# Initialize the build manager
manager = BuildManager(
    project_root=Path("."),
    src_dir=Path("src")
)

# Prepare build (finds and copies external dependencies)
external_deps = manager.prepare_build()

print(f"Found {len(external_deps)} external dependencies")
for dep in external_deps:
    print(f"  {dep.import_name}: {dep.source_path} -> {dep.target_path}")

# Run your build process here
# ...

# Cleanup copied files (also restores pyproject.toml if subfolder build)
manager.cleanup()
```

### Using the Convenience Method

```python
from pathlib import Path
from python_package_folder import BuildManager
import subprocess

manager = BuildManager(project_root=Path("."), src_dir=Path("src"))

def build_command():
    subprocess.run(["uv", "build"], check=True)

# Automatically handles prepare, build, and cleanup
manager.run_build(build_command)
```

### Subfolder Builds (Automatic Detection)

The tool automatically detects when you're building a subfolder and sets up the appropriate configuration:

```python
from pathlib import Path
from python_package_folder import BuildManager
import subprocess

# Building a subfolder - automatic detection!
manager = BuildManager(
    project_root=Path("."),
    src_dir=Path("src/integration/empty_drawing_detection")
)

def build_command():
    subprocess.run(["uv", "build"], check=True)

# prepare_build() automatically:
# - Detects this is a subfolder build
# - If pyproject.toml exists in subfolder: uses that file
# - If no pyproject.toml in subfolder: creates temporary one with package name "empty-drawing-detection"
# - Uses version "0.0.0" (or pass version="1.0.0" to override) if creating temporary pyproject.toml
external_deps = manager.prepare_build(version="1.0.0")

# Run build - uses the pyproject.toml (either from subfolder or temporary)
build_command()

# Cleanup restores original pyproject.toml and removes copied files
manager.cleanup()
```

**Note**: If the subfolder has its own `pyproject.toml`, it will be used automatically. The `version` and `package_name` parameters are only used when creating a temporary `pyproject.toml` from the parent configuration.

Or use the convenience method:

```python
manager = BuildManager(
    project_root=Path("."),
    src_dir=Path("src/integration/empty_drawing_detection")
)

def build_command():
    subprocess.run(["uv", "build"], check=True)

# All handled automatically: subfolder detection, pyproject.toml setup, build, cleanup
manager.run_build(build_command, version="1.0.0", package_name="my-custom-name")
```

## Working with sysappend

This package works well with projects using [sysappend](https://pypi.org/project/sysappend/) for flexible import management. When you have imports like:

```python
if True:
    import sysappend; sysappend.all()

from some_globals import SOME_GLOBAL_VARIABLE
from folder_structure.utility_folder.some_utility import print_something
```

The package will correctly identify and copy external dependencies even when they're referenced without full package paths.
