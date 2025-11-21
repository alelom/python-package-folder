"""
Type definitions for the package.

This module contains the core data structures used throughout the package
for representing import information and external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal


@dataclass
class ImportInfo:
    """
    Information about a detected import statement.

    This class represents a single import statement found in a Python file,
    including its classification and resolved file path.

    Attributes:
        module_name: The name of the module being imported (e.g., "os", "my_module.utils")
        import_type: Type of import - either "import" or "from"
        from_module: For "from" imports, the module name (same as module_name)
        line_number: Line number where the import appears in the source file
        file_path: Path to the file containing this import
        classification: Classification result - one of:
            - "stdlib": Standard library module
            - "third_party": Third-party package from site-packages
            - "local": Module within the source directory
            - "external": Module outside source directory but in the project
            - "ambiguous": Cannot be resolved
        resolved_path: Resolved file path for local/external imports, None otherwise
    """

    module_name: str
    import_type: Literal["import", "from"]
    from_module: str | None = None
    line_number: int = 0
    file_path: Path | None = None
    classification: Literal["stdlib", "third_party", "local", "external", "ambiguous"] | None = None
    resolved_path: Path | None = None


@dataclass
class ExternalDependency:
    """
    Information about an external dependency that needs to be copied.

    This class represents a file or directory that is imported from outside
    the source directory and needs to be temporarily copied into the source
    directory during the build process.

    Attributes:
        source_path: Original location of the dependency (outside src_dir)
        target_path: Destination path within src_dir where it will be copied
        import_name: The module name used in the import statement
        file_path: Path to the file that contains the import statement
    """

    source_path: Path
    target_path: Path
    import_name: str
    file_path: Path
