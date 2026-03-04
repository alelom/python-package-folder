# Publishing Packages

The package includes built-in support for publishing to PyPI, TestPyPI, and Azure Artifacts.

## Command Line Publishing

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

## Credentials

**For PyPI/TestPyPI:**
- **Username**: Your PyPI username, or `__token__` for API tokens
- **Password**: Your PyPI password or API token (recommended)
- **Auto-detection**: If you provide an API token (starts with `pypi-`), the tool will automatically use `__token__` as the username, even if you entered a different username

**Common Authentication Issues:**
- **403 Forbidden**: Usually means you used your username instead of `__token__` with an API token. The tool now auto-detects this.
- **TestPyPI vs PyPI**: TestPyPI requires a separate account and token from https://test.pypi.org/manage/account/token/

## Smart File Filtering

When publishing, the tool automatically filters distribution files to only upload those matching the current build:

- **Package name matching**: Only uploads files for the package being built
- **Version matching**: Only uploads files for the specified version
- **Automatic cleanup**: Old build artifacts in `dist/` are ignored, preventing accidental uploads

This ensures that when building a subfolder package, only that package's distribution files are uploaded, not files from previous builds of other packages.

## Version Mismatch Detection

If there's a version mismatch between the built package and the expected version (e.g., when a subfolder's `pyproject.toml` has a different version than the derived version), the error message will show:

- What version was actually built
- What version is expected for publishing
- An explanation of the mismatch
- A solution suggestion

The tool automatically updates the version in the subfolder's `pyproject.toml` to match the derived version, so this error should only occur if the build process fails before the version update takes effect.

To get a PyPI API token:
1. Go to https://pypi.org/manage/account/token/
2. Create a new API token
3. Use `__token__` as username and the token as password

**For Azure Artifacts:**
- **Username**: Your Azure username or feed name
- **Password**: Personal Access Token (PAT) with packaging permissions
- **Repository URL**: Your Azure Artifacts feed URL

## Python API Publishing

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

## Credential Storage

**Note**: The package does not store credentials by default. Credentials must be provided via command-line arguments (`--username` and `--password`) or will be prompted each time you run the publish command. This ensures credentials are not persisted and must be entered fresh each time.

If you previously used an older version that stored credentials in keyring, you can clear them using:

```python
from python_package_folder import Publisher, Repository

publisher = Publisher(repository=Repository.AZURE)
publisher.clear_stored_credentials()
```

Or manually using Python:
```python
import keyring
keyring.delete_password("python-package-folder-azure", "username")
# Also delete the password if you know the username
```
