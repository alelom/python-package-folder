"""
Allow running the package as a module.

This module enables running the package with:
    python -m python_package_folder

It simply delegates to the main() function from python_package_folder.py.
"""

from .python_package_folder import main

if __name__ == "__main__":
    exit(main())
