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

try:
    from importlib import resources
except ImportError:
    import importlib_resources as resources  # type: ignore[no-redef]

from .manager import BuildManager
from .utils import find_project_root, find_source_directory


def resolve_version_via_semantic_release(
    project_root: Path,
    subfolder_path: Path | None = None,
    package_name: str | None = None,
) -> str | None:
    """
    Resolve the next version using semantic-release via Node.js script.

    Args:
        project_root: Root directory of the project
        subfolder_path: Optional path to subfolder (relative to project_root) for Workflow 1
        package_name: Optional package name for subfolder builds

    Returns:
        Version string if a release is determined, None if no release or error
    """
    # Try to find the script in multiple locations:
    # 1. Project root / scripts (for development or when script is in repo)
    # 2. Package installation directory / scripts (for installed package)
    script_paths: list[Path] = [
        project_root / "scripts" / "get-next-version.cjs",
    ]
    
    # Try to locate script in installed package using importlib.resources
    try:
        package = resources.files("python_package_folder")
        script_resource = package / "scripts" / "get-next-version.cjs"
        if script_resource.is_file():
            # Convert Traversable to Path
            script_paths.append(Path(str(script_resource)))
    except (ImportError, ModuleNotFoundError, TypeError, AttributeError):
        # Fallback: try relative to package directory
        package_dir = Path(__file__).parent
        script_paths.append(package_dir / "scripts" / "get-next-version.cjs")
    
    script_path = None
    for path in script_paths:
        if path.exists():
            script_path = path
            break
    
    if not script_path:
        return None

    try:
        # Build command arguments
        cmd = ["node", str(script_path), str(project_root)]
        if subfolder_path and package_name:
            # Workflow 1: subfolder build
            rel_path = subfolder_path.relative_to(project_root) if subfolder_path.is_absolute() else subfolder_path
            cmd.extend([str(rel_path), package_name])
        # Workflow 2: main package (no additional args needed)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            check=False,
        )

        if result.returncode != 0:
            return None

        version = result.stdout.strip()
        if version and version != "none":
            return version

        return None
    except Exception:
        return None


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
        help="Root directory of the project (auto-detected from pyproject.toml if not specified)",
    )
    parser.add_argument(
        "--src-dir",
        type=Path,
        help="Source directory to build (default: auto-detected from current directory or project_root/src)",
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
        help="Set a specific version before building (PEP 440 format, e.g., '1.2.3'). Optional: if omitted, version will be resolved via semantic-release when needed.",
    )
    parser.add_argument(
        "--package-name",
        help="Package name for subfolder builds (default: derived from source directory name)",
    )
    parser.add_argument(
        "--dependency-group",
        dest="dependency_group",
        help="Dependency group name from parent pyproject.toml to include in subfolder build",
    )
    parser.add_argument(
        "--no-restore-versioning",
        action="store_true",
        help="Don't restore dynamic versioning after build (keeps static version)",
    )
    parser.add_argument(
        "--exclude-pattern",
        action="append",
        dest="exclude_patterns",
        help="Additional directory/file patterns to exclude from copying (e.g., '_SS', '__sandbox'). Can be specified multiple times.",
    )

    args = parser.parse_args()

    try:
        # Auto-detect project root if not specified
        if args.project_root:
            project_root = Path(args.project_root).resolve()
        else:
            project_root = find_project_root()
            if project_root is None:
                print(
                    "Error: Could not find project root (pyproject.toml not found).\n"
                    "Please run from a directory with pyproject.toml or specify --project-root",
                    file=sys.stderr,
                )
                return 1
            print(f"Auto-detected project root: {project_root}")

        # Determine source directory
        if args.src_dir:
            src_dir = Path(args.src_dir).resolve()
        else:
            # Auto-detect: use current directory if it has Python files, otherwise use project_root/src
            current_dir = Path.cwd()
            src_dir = find_source_directory(project_root, current_dir=current_dir)
            if src_dir:
                print(f"Auto-detected source directory: {src_dir}")
            else:
                src_dir = project_root / "src"

        manager = BuildManager(project_root, src_dir, exclude_patterns=args.exclude_patterns)

        if args.analyze_only:
            external_deps = manager.prepare_build()
            print(f"\nFound {len(external_deps)} external dependencies:")
            for dep in external_deps:
                print(f"  {dep.import_name}: {dep.source_path} -> {dep.target_path}")
            manager.cleanup()
            return 0

        def build_cmd() -> None:
            # Run build command from project root to ensure pyproject.toml is found
            result = subprocess.run(
                args.build_command,
                shell=True,
                check=False,
                cwd=project_root,
            )
            if result.returncode != 0:
                sys.exit(result.returncode)

        # Check if building a subfolder (not the main src/)
        is_subfolder = not src_dir.is_relative_to(project_root / "src") or (
            src_dir != project_root / "src" and src_dir != project_root
        )

        # Resolve version via semantic-release if not provided and needed
        resolved_version = args.version
        if not resolved_version and not args.analyze_only:
            # Version is needed for subfolder builds or when publishing main package
            if is_subfolder or args.publish:
                print("No --version provided, attempting to resolve via semantic-release...")
                if is_subfolder:
                    # Workflow 1: subfolder build
                    package_name = args.package_name or src_dir.name.replace("_", "-").replace(
                        " ", "-"
                    ).lower().strip("-")
                    subfolder_rel_path = src_dir.relative_to(project_root)
                    resolved_version = resolve_version_via_semantic_release(
                        project_root, subfolder_rel_path, package_name
                    )
                else:
                    # Workflow 2: main package
                    resolved_version = resolve_version_via_semantic_release(project_root)

                if resolved_version:
                    print(f"Resolved version via semantic-release: {resolved_version}")
                else:
                    error_msg = (
                        "Could not resolve version via semantic-release.\n"
                        "This could mean:\n"
                        "  - No release is needed (no relevant commits)\n"
                        "  - semantic-release is not installed or configured\n"
                        "  - Node.js is not available\n\n"
                        "Please either:\n"
                        "  - Install semantic-release: npm install -g semantic-release"
                    )
                    if is_subfolder:
                        error_msg += "\n  - Install semantic-release-commit-filter: npm install -g semantic-release-commit-filter"
                    error_msg += "\n  - Or provide --version explicitly"
                    print(f"Error: {error_msg}", file=sys.stderr)
                    return 1

        # Use resolved version for the rest of the flow
        if resolved_version:
            args.version = resolved_version

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
                package_name=args.package_name,
                dependency_group=args.dependency_group,
            )
        else:
            # Handle version setting even without publishing
            if args.version:
                # Check if subfolder build
                if is_subfolder:
                    from .subfolder_build import SubfolderBuildConfig

                    package_name = args.package_name or src_dir.name.replace("_", "-").replace(
                        " ", "-"
                    ).lower().strip("-")
                    subfolder_config = SubfolderBuildConfig(
                        project_root=project_root,
                        src_dir=src_dir,
                        package_name=package_name,
                        version=args.version,
                        dependency_group=args.dependency_group,
                    )
                    try:
                        subfolder_config.create_temp_pyproject()
                        manager.run_build(build_cmd)
                        if not args.no_restore_versioning:
                            subfolder_config.restore()
                            print("Restored original pyproject.toml")
                    except Exception as e:
                        print(f"Error managing subfolder build: {e}", file=sys.stderr)
                        if subfolder_config:
                            subfolder_config.restore()
                        raise
                else:
                    from .version import VersionManager

                    version_manager = VersionManager(project_root)
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
