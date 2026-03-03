# Installation and Requirements

Python >= 3.11 is required.

```bash
uv add python-package-folder

# or

pip install python-package-folder
```

**Note**: For publishing functionality, you'll also need `twine`:

```bash
pip install twine
# or
uv add twine
```

**For secure credential storage**: `keyring` is optional but recommended (install with `pip install keyring`)

**For automatic version resolution**: The tool uses a Python-native implementation that requires no additional dependencies. It follows [Angular Commit Message Conventions](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md) as used by [semantic-release](https://semantic-release.gitbook.io/semantic-release/).
