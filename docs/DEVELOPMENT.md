# Development

## Setup

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

## Project Structure 

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
