"""
Hatch build hook to automatically include all files from the scripts directory.

This hook ensures all non-Python files in the scripts directory are included
in the wheel without creating duplicates, and automatically includes any new
files added to the directory without requiring manual configuration updates.
"""

import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    """Build hook to include all files from the scripts directory."""

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        """Initialize the build hook and add scripts directory files."""
        # Debug: Print to stderr so it shows in build output
        print(f"[DEBUG] Build hook called. Root: {self.root}", file=sys.stderr)
        
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


# Export the hook class (hatchling might need this)
__all__ = ["CustomBuildHook"]
