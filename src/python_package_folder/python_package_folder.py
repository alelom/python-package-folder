"""
Main entry point for the python-package-folder package.

This module provides the command-line interface for the package.
It can be invoked via:
- The `python-package-folder` command (after installation)
- `python -m python_package_folder`
- Direct import and call to main()
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from .manager import BuildManager


def main() -> int:
    """
    Main entry point for the build script.

    Parses command-line arguments and runs the build process with
    external dependency management.

    Returns:
        Exit code (0 for success, non-zero for errors)
    """
    import argparse

    parser = argparse.ArgumentParser(
        description="Build Python package with external dependency management"
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="Root directory of the project (default: current directory)",
    )
    parser.add_argument(
        "--src-dir",
        type=Path,
        help="Source directory (default: project_root/src)",
    )
    parser.add_argument(
        "--analyze-only",
        action="store_true",
        help="Only analyze imports, don't run build",
    )
    parser.add_argument(
        "--build-command",
        default="uv build",
        help="Command to run for building (default: 'uv build')",
    )
    parser.add_argument(
        "--publish",
        choices=["pypi", "testpypi", "azure"],
        help="Publish to repository after building (pypi, testpypi, or azure)",
    )
    parser.add_argument(
        "--repository-url",
        help="Custom repository URL (required for Azure Artifacts)",
    )
    parser.add_argument(
        "--username",
        help="Username for publishing (will prompt if not provided)",
    )
    parser.add_argument(
        "--password",
        help="Password/token for publishing (will prompt if not provided)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip files that already exist on the repository",
    )
    parser.add_argument(
        "--version",
        help="Set a specific version before building (PEP 440 format, e.g., '1.2.3')",
    )
    parser.add_argument(
        "--no-restore-versioning",
        action="store_true",
        help="Don't restore dynamic versioning after build (keeps static version)",
    )

    args = parser.parse_args()

    try:
        manager = BuildManager(args.project_root, args.src_dir)

        if args.analyze_only:
            external_deps = manager.prepare_build()
            print(f"\nFound {len(external_deps)} external dependencies:")
            for dep in external_deps:
                print(f"  {dep.import_name}: {dep.source_path} -> {dep.target_path}")
            manager.cleanup()
            return 0

        def build_cmd() -> None:
            result = subprocess.run(args.build_command, shell=True, check=False)
            if result.returncode != 0:
                sys.exit(result.returncode)

        if args.publish:
            manager.build_and_publish(
                build_cmd,
                repository=args.publish,
                repository_url=args.repository_url,
                username=args.username,
                password=args.password,
                skip_existing=args.skip_existing,
                version=args.version,
                restore_versioning=not args.no_restore_versioning,
            )
        else:
            # Handle version setting even without publishing
            if args.version:
                from .version import VersionManager

                version_manager = VersionManager(args.project_root)
                original_version = version_manager.get_current_version()
                try:
                    print(f"Setting version to {args.version}...")
                    version_manager.set_version(args.version)
                    manager.run_build(build_cmd)
                    if not args.no_restore_versioning:
                        if original_version:
                            version_manager.set_version(original_version)
                        else:
                            version_manager.restore_dynamic_versioning()
                        print("Restored versioning configuration")
                except Exception as e:
                    print(f"Error managing version: {e}", file=sys.stderr)
                    raise
            else:
                manager.run_build(build_cmd)

        return 0

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
