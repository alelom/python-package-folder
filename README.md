# python-package-folder

Python package to automatically analyze, detect, and manage external dependencies when building Python packages. This tool recursively parses all Python files in your project, identifies imports from outside the main package directory, and temporarily copies them into the source directory during the build process.

## Features

- **Automatic Import Analysis**: Recursively parses all `.py` files to detect `import` and `from ... import ...` statements
- **Smart Import Classification**: Distinguishes between:
  - Standard library imports
  - Third-party packages (from site-packages)
  - Local imports (within the source directory)
  - External imports (outside source directory but in the project)
  - Ambiguous imports (unresolvable)
- **External Dependency Detection**: Automatically finds modules and files that originate from outside the main package directory
- **Temporary File Management**: Copies external dependencies into the source directory before build and cleans them up afterward
- **Idempotent Operations**: Safely handles repeated runs without duplicating files
- **Build Integration**: Seamlessly integrates with build tools like `uv build`, `pip build`, etc.
- **Warning System**: Reports ambiguous imports that couldn't be resolved
- **Subfolder Build Support**: Build subfolders as separate packages with automatic project root detection
- **Smart Publishing**: Only uploads distribution files from the current build, filtering out old artifacts
- **Auto-Detection**: Automatically finds project root and source directory when run from any subdirectory
- **Authentication Helpers**: Auto-detects API tokens and uses correct username format

## Installation

```bash
pip install python-package-folder
```

Or using `uv`:

```bash
uv add python-package-folder
```

**Note**: For publishing functionality, you'll also need `twine`:

```bash
pip install twine
# or
uv add twine
```

## Quick Start

### Command Line Usage

The simplest way to use this package is via the command-line interface:

```bash
# Build with automatic dependency management (from project root)
python-package-folder --build-command "uv build"

# Analyze dependencies without building
python-package-folder --analyze-only

# Build from any subdirectory - auto-detects project root and source directory
cd tests/folder_structure/subfolder_to_build
python-package-folder --analyze-only

# Specify custom project root and source directory
python-package-folder --project-root /path/to/project --src-dir /path/to/src --build-command "pip build"
```

### Building from Subdirectories

The tool can automatically detect the project root by searching for `pyproject.toml` in parent directories. This allows you to build subfolders of a main project as separate packages:

```bash
# From a subdirectory, the tool will:
# 1. Find pyproject.toml in parent directories (project root)
# 2. Use current directory as source if it contains Python files
# 3. Build with dependencies from the parent project
# 4. Create a temporary build config with subfolder-specific name and version

cd my_project/subfolder_to_build
python-package-folder --version "1.0.0" --publish pypi
```

**Important**: When building from a subdirectory, you **must** specify `--version` because subfolders are built as separate packages with their own version.

The tool automatically:
- Finds the project root by looking for `pyproject.toml` in parent directories
- Uses the current directory as the source directory if it contains Python files
- Falls back to `project_root/src` if the current directory isn't suitable
- For subfolder builds: creates a temporary `pyproject.toml` with:
  - Package name derived from the subfolder name (or use `--package-name` to override)
  - Version from `--version` argument
  - Proper package path configuration for hatchling
- Creates temporary `__init__.py` files if needed to make subfolders valid Python packages
- Restores the original `pyproject.toml` after build (unless `--no-restore-versioning` is used)
- Cleans up temporary `__init__.py` files after build

**Subfolder Build Example:**
```bash
# Build a subfolder as a separate package
cd tests/folder_structure/subfolder_to_build
python-package-folder --version "0.1.0" --package-name "my-subfolder-package" --publish pypi
```

### Python API Usage

You can also use the package programmatically:

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

# Cleanup copied files
manager.cleanup()
```

Or use the convenience method:

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

## Use Cases

### Building Packages with Shared Code

If your project structure looks like this:

```
project/
├── src/
│   └── my_package/
│       └── main.py
├── shared/
│   ├── utils.py
│   └── helpers.py
└── pyproject.toml
```

And `main.py` imports from `shared/`:

```python
from shared.utils import some_function
from shared.helpers import Helper
```

This package will automatically:
1. Detect that `shared/` is outside `src/`
2. Copy `shared/` into `src/` before building
3. Build your package with all dependencies included
4. Clean up the copied files after build

### Working with sysappend

This package works well with projects using [sysappend](https://pypi.org/project/sysappend/) for flexible import management. When you have imports like:

```python
if True:
    import sysappend; sysappend.all()

from some_globals import SOME_GLOBAL_VARIABLE
from folder_structure.utility_folder.some_utility import print_something
```

The package will correctly identify and copy external dependencies even when they're referenced without full package paths.

## Version Management

The package supports both dynamic versioning (from git tags) and manual version specification.

### Manual Version Setting

You can manually set a version before building and publishing:

```bash
# Build with a specific version
python-package-folder --version "1.2.3"

# Build and publish with a specific version
python-package-folder --version "1.2.3" --publish pypi

# Keep the static version (don't restore dynamic versioning)
python-package-folder --version "1.2.3" --no-restore-versioning
```

The `--version` option:
- Sets a static version in `pyproject.toml` before building
- Temporarily removes dynamic versioning configuration
- Restores the original configuration after build (unless `--no-restore-versioning` is used)
- Validates version format (must be PEP 440 compliant)

**Version Format**: Versions must follow PEP 440 (e.g., `1.2.3`, `1.2.3a1`, `1.2.3.post1`, `1.2.3.dev1`)

### Subfolder Versioning

When building from a subdirectory (not the main `src/` directory), you **must** specify `--version`:

```bash
# Build a subfolder as a separate package
cd my_project/subfolder_to_build
python-package-folder --version "1.0.0" --publish pypi

# With custom package name
python-package-folder --version "1.0.0" --package-name "my-custom-name" --publish pypi
```

For subfolder builds:
- **Version is required**: The tool will error if `--version` is not provided
- **Package name**: Automatically derived from the subfolder name (e.g., `subfolder_to_build` → `subfolder-to-build`)
- **Temporary configuration**: Creates a temporary `pyproject.toml` with:
  - Custom package name (from `--package-name` or derived)
  - Specified version
  - Correct package path for hatchling
- **Package initialization**: Automatically creates `__init__.py` if the subfolder doesn't have one (required for hatchling)
- **Auto-restore**: Original `pyproject.toml` is restored after build, and temporary `__init__.py` files are removed

### Python API for Version Management

```python
from python_package_folder import VersionManager
from pathlib import Path

# Set a version
version_manager = VersionManager(project_root=Path("."))
version_manager.set_version("1.2.3")

# Get current version
current_version = version_manager.get_current_version()

# Restore dynamic versioning
version_manager.restore_dynamic_versioning()
```

### Dynamic Versioning

By default, the package uses `uv-dynamic-versioning` which derives versions from git tags. This is configured in `pyproject.toml`:

```toml
[project]
dynamic = ["version"]

[tool.hatch.version]
source = "uv-dynamic-versioning"

[tool.uv-dynamic-versioning]
vcs = "git"
style = "pep440"
bump = true
```

When you use `--version`, the package temporarily switches to static versioning for that build, then restores the dynamic configuration.

## Publishing Packages

The package includes built-in support for publishing to PyPI, TestPyPI, and Azure Artifacts.

### Command Line Publishing

Publish after building:

```bash
# Publish to PyPI
python-package-folder --publish pypi

# Publish to PyPI with a specific version
python-package-folder --version "1.2.3" --publish pypi

# Publish to TestPyPI (for testing)
python-package-folder --publish testpypi

# Publish to Azure Artifacts
python-package-folder --publish azure --repository-url "https://pkgs.dev.azure.com/ORG/PROJECT/_packaging/FEED/pypi/upload"
```

The command will prompt for credentials if not provided:

```bash
# Provide credentials via command line (less secure)
python-package-folder --publish pypi --username __token__ --password pypi-xxxxx

# Skip existing files on repository
python-package-folder --publish pypi --skip-existing
```

### Credentials

**For PyPI/TestPyPI:**
- **Username**: Your PyPI username, or `__token__` for API tokens
- **Password**: Your PyPI password or API token (recommended)
- **Auto-detection**: If you provide an API token (starts with `pypi-`), the tool will automatically use `__token__` as the username, even if you entered a different username

**Common Authentication Issues:**
- **403 Forbidden**: Usually means you used your username instead of `__token__` with an API token. The tool now auto-detects this.
- **TestPyPI vs PyPI**: TestPyPI requires a separate account and token from https://test.pypi.org/manage/account/token/

### Smart File Filtering

When publishing, the tool automatically filters distribution files to only upload those matching the current build:

- **Package name matching**: Only uploads files for the package being built
- **Version matching**: Only uploads files for the specified version
- **Automatic cleanup**: Old build artifacts in `dist/` are ignored, preventing accidental uploads

This ensures that when building a subfolder package, only that package's distribution files are uploaded, not files from previous builds of other packages.

To get a PyPI API token:
1. Go to https://pypi.org/manage/account/token/
2. Create a new API token
3. Use `__token__` as username and the token as password

**For Azure Artifacts:**
- **Username**: Your Azure username or feed name
- **Password**: Personal Access Token (PAT) with packaging permissions
- **Repository URL**: Your Azure Artifacts feed URL

### Python API Publishing

You can also publish programmatically:

```python
from pathlib import Path
from python_package_folder import BuildManager, Publisher, Repository
import subprocess

# Build and publish in one step
manager = BuildManager(project_root=Path("."), src_dir=Path("src"))

def build():
    subprocess.run(["uv", "build"], check=True)

manager.build_and_publish(
    build,
    repository="pypi",
    username="__token__",
    password="pypi-xxxxx",
    version="1.2.3"  # Optional: set specific version
)
```
```

Or publish separately:

```python
from python_package_folder import Publisher, Repository

# Publish existing distribution
publisher = Publisher(
    repository=Repository.PYPI,
    dist_dir=Path("dist"),
    username="__token__",
    password="pypi-xxxxx"
)
publisher.publish()
```

### Credential Storage

The package uses the `keyring` library (if installed) to securely store credentials. Credentials are stored per repository and will be reused on subsequent runs.

Install keyring for secure credential storage:
```bash
pip install keyring
```

## Command Line Options

```
usage: python-package-folder [-h] [--project-root PROJECT_ROOT]
                             [--src-dir SRC_DIR] [--analyze-only]
                             [--build-command BUILD_COMMAND]
                             [--publish {pypi,testpypi,azure}]
                             [--repository-url REPOSITORY_URL]
                             [--username USERNAME] [--password PASSWORD]
                             [--skip-existing]

Build Python package with external dependency management

options:
  -h, --help            show this help message and exit
  --project-root PROJECT_ROOT
                        Root directory of the project (default: current directory)
  --src-dir SRC_DIR     Source directory (default: project_root/src)
  --analyze-only        Only analyze imports, don't run build
  --build-command BUILD_COMMAND
                        Command to run for building (default: 'uv build')
  --publish {pypi,testpypi,azure}
                        Publish to repository after building
  --repository-url REPOSITORY_URL
                        Custom repository URL (required for Azure Artifacts)
  --username USERNAME   Username for publishing (will prompt if not provided)
  --password PASSWORD   Password/token for publishing (will prompt if not provided)
  --skip-existing       Skip files that already exist on the repository
  --version VERSION     Set a specific version before building (PEP 440 format).
                        Required for subfolder builds.
  --package-name PACKAGE_NAME
                        Package name for subfolder builds (default: derived from
                        source directory name)
  --no-restore-versioning
                        Don't restore dynamic versioning after build
```

## API Reference

### BuildManager

Main class for managing the build process with external dependency handling.

```python
from python_package_folder import BuildManager
from pathlib import Path

manager = BuildManager(
    project_root: Path,      # Root directory of the project
    src_dir: Path | None     # Source directory (default: project_root/src)
)
```

**Methods:**

- `prepare_build() -> list[ExternalDependency]`: Find and copy external dependencies
- `cleanup() -> None`: Remove all copied files and directories
- `run_build(build_command: Callable[[], None]) -> None`: Run build with automatic prepare and cleanup

### ImportAnalyzer

Analyzes Python files to extract and classify import statements.

```python
from python_package_folder import ImportAnalyzer
from pathlib import Path

analyzer = ImportAnalyzer(project_root=Path("."))
python_files = analyzer.find_all_python_files(Path("src"))
imports = analyzer.extract_imports(python_files[0])
analyzer.classify_import(imports[0], src_dir=Path("src"))
```

### ExternalDependencyFinder

Finds external dependencies that need to be copied.

```python
from python_package_folder import ExternalDependencyFinder
from pathlib import Path

finder = ExternalDependencyFinder(
    project_root=Path("."),
    src_dir=Path("src")
)
dependencies = finder.find_external_dependencies(python_files)
```

### Publisher

Publishes built packages to PyPI, TestPyPI, or Azure Artifacts.

```python
from python_package_folder import Publisher, Repository
from pathlib import Path

publisher = Publisher(
    repository=Repository.PYPI,
    dist_dir=Path("dist"),
    username="__token__",
    password="pypi-xxxxx",
    package_name="my-package",  # Optional: filter files by package name
    version="1.2.3"              # Optional: filter files by version
)
publisher.publish()
```

**Methods:**
- `publish(skip_existing: bool = False) -> None`: Publish the package (automatically filters by package_name/version if provided)
- `publish_interactive(skip_existing: bool = False) -> None`: Publish with interactive credential prompts

**Note**: When `package_name` and `version` are provided, only distribution files matching those parameters are uploaded. This prevents uploading old build artifacts.

### VersionManager

Manages package version in pyproject.toml.

```python
from python_package_folder import VersionManager
from pathlib import Path

version_manager = VersionManager(project_root=Path("."))

# Set a static version
version_manager.set_version("1.2.3")

# Get current version
version = version_manager.get_current_version()

# Restore dynamic versioning
version_manager.restore_dynamic_versioning()
```

**Methods:**
- `set_version(version: str) -> None`: Set a static version (validates PEP 440 format)
- `get_current_version() -> str | None`: Get current version from pyproject.toml
- `restore_dynamic_versioning() -> None`: Restore dynamic versioning configuration

### SubfolderBuildConfig

Manages temporary build configuration for subfolder builds.

```python
from python_package_folder import SubfolderBuildConfig
from pathlib import Path

config = SubfolderBuildConfig(
    project_root=Path("."),
    src_dir=Path("subfolder"),
    package_name="my-subfolder",
    version="1.0.0"
)

# Create temporary pyproject.toml
config.create_temp_pyproject()

# ... build process ...

# Restore original configuration
config.restore()
```

**Methods:**
- `create_temp_pyproject() -> Path`: Create temporary `pyproject.toml` with subfolder-specific configuration
- `restore() -> None`: Restore original `pyproject.toml` and clean up temporary files

**Note**: This class automatically creates `__init__.py` files if needed to make subfolders valid Python packages.

## How It Works

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
   - Prompts for credentials if not provided
   - Uses `keyring` for secure storage (if available)
   - Supports both username/password and API tokens
   - Auto-detects API tokens and uses `__token__` as username
4. **Repository Configuration**: Configures the target repository (PyPI, TestPyPI, or Azure)
5. **Upload**: Uses `twine` to upload distribution files to the repository
6. **Verification**: Confirms successful upload

### Subfolder Build Process

1. **Project Root Detection**: Searches parent directories for `pyproject.toml`
2. **Source Directory Detection**: Uses current directory if it contains Python files, otherwise falls back to `project_root/src`
3. **Package Initialization**: Creates temporary `__init__.py` if subfolder doesn't have one (required for hatchling)
4. **Configuration Creation**: Creates temporary `pyproject.toml` with:
   - Subfolder-specific package name (derived or custom)
   - Specified version
   - Correct package path for hatchling
5. **Build Execution**: Runs build command with all dependencies in place
6. **Cleanup**: Restores original `pyproject.toml` and removes temporary `__init__.py`

## Requirements

- Python >= 3.11
- **For publishing**: `twine` is required (install with `pip install twine`)
- **For secure credential storage**: `keyring` is optional but recommended (install with `pip install keyring`)

## Development

### Setup

```bash
# Clone the repository
git clone https://github.com/alelom/python-package-folder.git
cd python-package-folder

# Install dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run linting
make lint
```

### Project Structure

```
python-package-folder/
├── src/
│   └── python_package_folder/
│       ├── __init__.py          # Package exports
│       ├── types.py             # Type definitions
│       ├── analyzer.py           # Import analysis
│       ├── finder.py             # Dependency finding
│       ├── manager.py            # Build management
│       └── python_package_folder.py  # CLI entry point
├── tests/
│   ├── test_build_with_external_deps.py
│   └── folder_structure/        # Test fixtures
├── devtools/
│   └── lint.py                  # Development tools
└── pyproject.toml
```

## License

MIT License - see LICENSE file for details

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Author

Alessio Lombardi - [GitHub](https://github.com/alelom)

## Related Projects

- [sysappend](https://pypi.org/project/sysappend/) - Flexible import management for Python projects
