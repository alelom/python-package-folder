"""
Hatch build hook to automatically include all files from the scripts directory.

This hook ensures all non-Python files in the scripts directory are included
in the wheel without creating duplicates, and automatically includes any new
files added to the directory without requiring manual configuration updates.
"""

from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Build hook to include all files from the scripts directory."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Initialize the build hook and add scripts directory files."""
        # Get the source directory for the package
        source_dir = Path(self.root) / "src" / "python_package_folder"
        scripts_dir = source_dir / "scripts"

        # If scripts directory exists, include all files from it
        if scripts_dir.exists() and scripts_dir.is_dir():
            # Add all files from scripts directory to force-include
            # This ensures they're included in the wheel at the correct location
            for script_file in scripts_dir.iterdir():
                if script_file.is_file():
                    # Calculate relative paths
                    source_path = script_file.relative_to(self.root)
                    # Target path inside the wheel package
                    target_path = f"python_package_folder/scripts/{script_file.name}"

                    # Add to force-include (hatchling will handle this)
                    # We need to add it to build_data['force_include']
                    if "force_include" not in build_data:
                        build_data["force_include"] = {}
                    build_data["force_include"][str(source_path)] = target_path
