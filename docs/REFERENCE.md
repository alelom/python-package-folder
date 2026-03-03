# API Reference

## Configuration

### Exclude Patterns

You can configure exclude patterns in `pyproject.toml` to prevent folders and files from being included in published packages (wheel/sdist). Patterns are matched using regex against any path component (directory or file name).

```toml
[tool.python-package-folder]
exclude-patterns = ["_SS", "__SS", ".*_test.*", "sandbox"]
```

**Pattern Matching:**
- Patterns are regex strings that match against any path component
- If any component in a path matches any pattern, the entire path is excluded
- Examples:
  - `"_SS"` - Matches any path component containing `_SS` (e.g., `data_storage/_SS/...`)
  - `".*_test.*"` - Matches any path component containing `_test` (e.g., `my_test_file.py`, `test_data/`)
  - `"sandbox"` - Matches any path component containing `sandbox`

**Subfolder Builds:**
- Exclude patterns from the root `pyproject.toml` are automatically applied to subfolder builds
- Patterns are injected into the temporary `pyproject.toml` created for subfolder builds

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
                        Optional: if omitted, version will be resolved via
                        conventional commits when needed.
  --package-name PACKAGE_NAME
                        Package name for subfolder builds (default: derived from
                        source directory name)
  --dependency-group DEPENDENCY_GROUP
                        Dependency group name from parent pyproject.toml to include
                        in subfolder build
  --no-restore-versioning
                        Don't restore dynamic versioning after build
```

## Python API

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

Manages temporary build configuration for subfolder builds. If a `pyproject.toml` exists
in the subfolder, it will be used instead of creating a new one.

```python
from python_package_folder import SubfolderBuildConfig
from pathlib import Path

config = SubfolderBuildConfig(
    project_root=Path("."),
    src_dir=Path("subfolder"),
    package_name="my-subfolder",  # Only used if subfolder has no pyproject.toml
    version="1.0.0"  # Only used if subfolder has no pyproject.toml
)

# Create temporary pyproject.toml (or use subfolder's if it exists)
config.create_temp_pyproject()

# ... build process ...

# Restore original configuration
config.restore()
```

**Methods:**
- `create_temp_pyproject() -> Path`: Use subfolder's `pyproject.toml` if it exists (adjusting package paths and ensuring `[build-system]` uses hatchling), otherwise create temporary `pyproject.toml` with subfolder-specific configuration including `[build-system]` section using hatchling
- `restore() -> None`: Restore original `pyproject.toml` and clean up temporary files

**Note**: This class automatically:
- **pyproject.toml handling**: If a `pyproject.toml` exists in the subfolder, it will be used (copied to project root temporarily with adjusted package paths). Otherwise, creates a temporary one from the parent configuration. In both cases, the `[build-system]` section is always set to use hatchling, replacing any existing build-system configuration.
- **README handling**: If a README exists in the subfolder, it will be used instead of the parent README. If no README exists in the subfolder, a minimal README with just the folder name will be created. The original parent README is backed up and restored after the build completes.
- **Package initialization**: Creates `__init__.py` files if needed to make subfolders valid Python packages.
