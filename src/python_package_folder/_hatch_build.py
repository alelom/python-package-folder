"""
Hatch build hook to automatically include all files from the scripts directory.

This hook ensures all non-Python files in the scripts directory are included
in the wheel without creating duplicates, and automatically includes any new
files added to the directory without requiring manual configuration updates.

Also filters files based on exclude patterns from pyproject.toml.
"""

import re
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface

from .utils import read_exclude_patterns


class CustomBuildHook(BuildHookInterface):
    """Build hook to include all files from the scripts directory and filter exclude patterns."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Initialize the build hook and add scripts directory files."""
        # Debug: Print to stderr so it shows in build output
        print(f"[DEBUG] Build hook called. Root: {self.root}", file=sys.stderr)
        
        # Read exclude patterns from pyproject.toml
        pyproject_path = Path(self.root) / "pyproject.toml"
        exclude_patterns = read_exclude_patterns(pyproject_path)
        
        if exclude_patterns:
            print(f"[DEBUG] Found {len(exclude_patterns)} exclude pattern(s): {exclude_patterns}", file=sys.stderr)
            # Filter build_data entries based on exclude patterns
            self._filter_build_data(build_data, exclude_patterns)
        
        # Try multiple possible locations for the scripts directory
        # 1. Source layout: src/python_package_folder/scripts
        # 2. Sdist layout: python_package_folder/scripts (after extraction)
        # 3. Alternative sdist layout: scripts/ (if extracted differently)
        possible_scripts_dirs = [
            Path(self.root) / "src" / "python_package_folder" / "scripts",
            Path(self.root) / "python_package_folder" / "scripts",
            Path(self.root) / "scripts",
        ]
        
        scripts_dir = None
        for possible_dir in possible_scripts_dirs:
            if possible_dir.exists() and possible_dir.is_dir():
                scripts_dir = possible_dir
                print(f"[DEBUG] Found scripts dir at: {scripts_dir}", file=sys.stderr)
                break
        
        if scripts_dir is None:
            print(f"[DEBUG] Scripts directory not found. Tried: {[str(d) for d in possible_scripts_dirs]}", file=sys.stderr)
            return

        # If scripts directory exists, include all files from it
        if scripts_dir.exists() and scripts_dir.is_dir():
            # Add all files from scripts directory to force-include
            # This ensures they're included in the wheel at the correct location
            for script_file in scripts_dir.iterdir():
                if script_file.is_file():
                    # Calculate relative paths from project root
                    try:
                        source_path = script_file.relative_to(self.root)
                    except ValueError:
                        # If relative_to fails, try to construct path manually
                        # This can happen with sdist layouts
                        if "python_package_folder" in str(script_file):
                            # Extract the part after python_package_folder
                            parts = script_file.parts
                            try:
                                idx = parts.index("python_package_folder")
                                source_path = Path(*parts[idx:])
                            except (ValueError, IndexError):
                                # Fallback: use the filename
                                source_path = Path("python_package_folder") / "scripts" / script_file.name
                        else:
                            source_path = Path("python_package_folder") / "scripts" / script_file.name
                    
                    # Target path inside the wheel package (always the same)
                    target_path = f"python_package_folder/scripts/{script_file.name}"

                    print(f"[DEBUG] Adding {source_path} -> {target_path}", file=sys.stderr)

                    # Add to force-include (hatchling will handle this)
                    # We need to add it to build_data['force_include']
                    if "force_include" not in build_data:
                        build_data["force_include"] = {}
                    build_data["force_include"][str(source_path)] = target_path
            
            print(f"[DEBUG] force_include now has {len(build_data.get('force_include', {}))} entries", file=sys.stderr)

    def _filter_build_data(self, build_data: dict[str, Any], exclude_patterns: list[str]) -> None:
        """
        Filter build_data entries based on exclude patterns.

        Removes files/directories that match any of the exclude patterns from
        build_data. Patterns are matched against any path component using regex.

        Args:
            build_data: Hatchling build data dictionary
            exclude_patterns: List of regex patterns to match against paths
        """
        # Compile regex patterns for efficiency
        compiled_patterns = [re.compile(pattern) for pattern in exclude_patterns]

        def should_exclude(path_str: str) -> bool:
            """Check if a path should be excluded based on patterns."""
            # Check each component of the path
            path = Path(path_str)
            for part in path.parts:
                # Check if any part matches any pattern
                for pattern in compiled_patterns:
                    if pattern.search(part):
                        return True
            return False

        # Filter force_include entries
        if "force_include" in build_data and isinstance(build_data["force_include"], dict):
            original_count = len(build_data["force_include"])
            filtered = {
                source: target
                for source, target in build_data["force_include"].items()
                if not should_exclude(source) and not should_exclude(target)
            }
            build_data["force_include"] = filtered
            excluded_count = original_count - len(filtered)
            if excluded_count > 0:
                print(
                    f"[DEBUG] Excluded {excluded_count} file(s) from force_include based on exclude patterns",
                    file=sys.stderr,
                )

        # Filter other file collections that might exist
        # Hatchling may store files in different keys depending on the build target
        for key in ["shared_data", "artifacts"]:
            if key in build_data and isinstance(build_data[key], dict):
                original_count = len(build_data[key])
                filtered = {
                    source: target
                    for source, target in build_data[key].items()
                    if not should_exclude(source) and not should_exclude(target)
                }
                build_data[key] = filtered
                excluded_count = original_count - len(filtered)
                if excluded_count > 0:
                    print(
                        f"[DEBUG] Excluded {excluded_count} file(s) from {key} based on exclude patterns",
                        file=sys.stderr,
                    )

        # Filter files list if it exists (for sdist)
        if "files" in build_data and isinstance(build_data["files"], list):
            original_count = len(build_data["files"])
            filtered = [
                file_entry
                for file_entry in build_data["files"]
                if not should_exclude(str(file_entry))
            ]
            build_data["files"] = filtered
            excluded_count = original_count - len(filtered)
            if excluded_count > 0:
                print(
                    f"[DEBUG] Excluded {excluded_count} file(s) from files list based on exclude patterns",
                    file=sys.stderr,
                )


# Export the hook class (hatchling might need this)
__all__ = ["CustomBuildHook"]
