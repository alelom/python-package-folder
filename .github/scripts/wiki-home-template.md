# python-package-folder Documentation

Welcome to the python-package-folder documentation wiki!

## Quick Links

{QUICK_LINKS}

## Overview

Easily build and publish any target folder in a repository, including subfolders of a monorepo.  
Together with [sysappend](https://pypi.org/project/sysappend/), this library makes relative imports, flexible import management, and package publishing a breeze.

## Features

- **Subfolder Build Support**: Build subfolders as separate packages with automatic detection and configuration
- **Smart Import Classification**: Recursively parses all `.py` files to detect and classify imports
- **Automatic Version Resolution**: Resolve versions via conventional commits (Python-native, no Node.js required)
- **Package Publishing**: Publish to PyPI, TestPyPI, or Azure Artifacts

## Quick Start

```bash
# Build and publish a subfolder
cd src/my_subfolder
python-package-folder --publish pypi
```

For more information, see the [Usage Guide](Usage).
