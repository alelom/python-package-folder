# python-package-folder <!-- omit from toc -->

[![Tests](https://github.com/alelom/python-package-folder/actions/workflows/ci.yml/badge.svg)](https://github.com/alelom/python-package-folder/actions/workflows/ci.yml)
[![Coverage](https://raw.githubusercontent.com/alelom/python-package-folder/main/coverage.svg)](https://github.com/alelom/python-package-folder)

Easily build and publish any target folder in a repository, including subfolders of a monorepo.  
Together with [sysappend](https://pypi.org/project/sysappend/), this library makes relative imports, flexible import management, and package publishing a breeze.

## Documentation

- [Installation and Requirements](docs/INSTALLATION.md)
- [Usage Guide](docs/USAGE.md) - How it works, Python API, subfolder builds
- [Version Resolution](docs/VERSION_RESOLUTION.md) - Manual and automatic versioning with conventional commits
- [Publishing Packages](docs/PUBLISHING.md) - Publishing to PyPI, TestPyPI, and Azure Artifacts
- [API Reference](docs/REFERENCE.md) - Command-line options and Python API
- [Development](docs/DEVELOPMENT.md) - Contributing and project structure

## Use Cases

### 1) Publishing a Subfolder from src/ in a Monorepo

If you have a monorepo structure with multiple packages in `src/`:

```
project/
├── src/
│   ├── core_package/
│   │   ├── __init__.py
│   │   ├── core.py
│   │   └── README.md
│   ├── api_package/
│   │   ├── __init__.py
│   │   ├── api.py
│   │   └── README.md
│   └── utils_package/
│       ├── __init__.py
│       ├── utils.py
│       └── README.md
├── shared/
│   └── common.py
└── pyproject.toml
```

You can build and publish any subfolder from `src/` as a standalone package:

```bash
# Navigate to the subfolder you want to publish
cd src/api_package

# Build and publish to TestPyPI with version 1.2.0
python-package-folder --publish testpypi --version 1.2.0

# Or publish to PyPI with automatic version resolution via conventional commits
python-package-folder --publish pypi

# Or publish to PyPI with a custom package name
python-package-folder --publish pypi --version 1.2.0 --package-name "my-api-package"

# Include a specific dependency group from the parent pyproject.toml
python-package-folder --publish pypi --version 1.2.0 --dependency-group "dev"
```

The tool will automatically:
1. Detect the project root (where `pyproject.toml` is located)
2. Use `src/api_package` as the source directory
3. Copy any external dependencies (like `shared/common.py`) into the package before building
4. Use the subfolder's README if present, or create a minimal one
5. Create a temporary `pyproject.toml` with the subfolder's package name and version
6. Build and publish the package
7. Clean up all temporary files and restore the original `pyproject.toml`

This is especially useful for monorepos where you want to publish individual packages independently while sharing common code.


### 2) Building Packages with Shared Code

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

## Features

- **Subfolder Build Support**: Build subfolders as separate packages with automatic detection and configuration
  - **Automatic subfolder detection**: Detects when building a subfolder (not the main `src/` directory)
  - Creates any needed file for publishing automatically, cleaning up if not originally in the subfolder after the build/publish process. E.g. copies external dependencies into the source directory before build and cleans them up afterward; temporary `__init__.py` creation for non-package subfolders; uses subfolder README if present, otherwise creates minimal README
  - Automatic package name derivation from subfolder name
  - Automatic temporary `pyproject.toml` creation with correct package structure
  - Dependency group selection: specify which dependency group from parent `pyproject.toml` to include.
  
- **Smart Import Classification and analysis**:
  - Recursively parses all `.py` files to detect `import` and `from ... import ...` statements
  - Handles external dependencies (modules and files that originate from outside the main package directory), and distinguishes standard library imports, 3rd-party packages (from site-packages), local/external/relative/ambiguous imports.

- **Idempotent Operations**: Safely handles repeated runs without duplicating files
- **Build Integration**: Seamlessly integrates with build tools like `uv build`, `pip build`, etc.
- **Version Management**: 
  - Set static versions for publishing (PEP 440 compliant)
  - Temporarily override dynamic versioning during builds
  - Automatic restoration of dynamic versioning after build
  - **Automatic version resolution** via conventional commits (Python-native, no Node.js required)
- **Package Publishing**:
  - Uses twine to publish the built folder/subfolder 
  - Handles publishing to to PyPI, TestPyPI, or Azure Artifacts, with interactive credential prompts, secure storage support

## Quick Start

The simplest way to use this package is via the command-line interface

**Build/publish a specific subfolder in a repository**

Useful for monorepos containing many subfolders that may need publishing as stand-alone packages for external usage.

```bash
# First cd to the specific subfolder
cd src/subfolder_to_build_and_publish

# Build and publish any subdirectory of your repo to TestPyPi (https://test.pypi.org/)
# Version can be provided explicitly or resolved automatically via conventional commits
python-package-folder --publish testpypi --version 0.0.2

# Or let the tool determine the next version automatically from conventional commits
python-package-folder --publish testpypi

# Only analyse (no building)
cd src/subfolder_to_build_and_publish
python-package-folder --analyze-only

# Only build
cd src/subfolder_to_build_and_publish
python-package-folder

# Build with automatic dependency management
python-package-folder --build-command "uv build"
```

You can also target a specific subfolder via commandline, rather than `cd`ing there:

```bash
# Specify custom project root and source directory
python-package-folder --project-root /path/to/project --src-dir /path/to/src --build-command "pip build"
```

## License <!-- omit from toc -->

MIT License - see LICENSE file for details

## Contributing <!-- omit from toc -->

Contributions are welcome! Please feel free to submit a Pull Request.
