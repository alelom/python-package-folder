"""
Main entry point for the python-package-folder package.

This module provides the command-line interface for the package.
It can be invoked via:
- The `python-package-folder` command (after installation)
- `python -m python_package_folder`
- Direct import and call to main()
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from importlib import resources
except ImportError:
    import importlib_resources as resources  # type: ignore[no-redef]

from .manager import BuildManager
from .utils import find_project_root, find_source_directory


def is_github_actions() -> bool:
    """Check if running in GitHub Actions."""
    return os.getenv("GITHUB_ACTIONS") == "true"


def check_node_available() -> bool:
    """Check if Node.js is available."""
    return shutil.which("node") is not None


def resolve_version_via_semantic_release(
    project_root: Path,
    subfolder_path: Path | None = None,
    package_name: str | None = None,
    repository: str | None = None,
    repository_url: str | None = None,
) -> str | None:
    """
    Resolve the next version using semantic-release via Node.js script.

    Args:
        project_root: Root directory of the project
        subfolder_path: Optional path to subfolder (relative to project_root) for Workflow 1
        package_name: Optional package name for subfolder builds
        repository: Optional target repository ('pypi', 'testpypi', or 'azure')
        repository_url: Optional repository URL (required for Azure Artifacts)

    Returns:
        Version string if a release is determined, None if no release or error
    """
    # Check for Node.js availability upfront
    if not check_node_available():
        if is_github_actions():
            error_msg = """Node.js is not available in this GitHub Actions workflow.

To fix this, add the following steps BEFORE running python-package-folder:

- name: Setup Node.js
  uses: actions/setup-node@v4
  with:
    node-version: '20'

- name: Install semantic-release
  run: |
    npm install -g semantic-release semantic-release-commit-filter

Alternatively, provide --version explicitly to skip automatic version resolution."""
            print(f"Error: {error_msg}", file=sys.stderr)
        else:
            print(
                "Warning: Node.js not found. Cannot resolve version via semantic-release.",
                file=sys.stderr,
            )
        return None

    # Try to find the script in multiple locations:
    # 1. Project root / scripts (for development or when script is in repo)
    # 2. Package installation directory / scripts (for installed package)
    #    - For normal installs: direct file path
    #    - For zip/pex installs: extract to temporary file using as_file()

    # Track temporary file context for cleanup
    temp_script_context = None

    try:
        # First, try project root (development)
        dev_script = project_root / "scripts" / "get-next-version.cjs"
        if dev_script.exists():
            script_path = dev_script
        else:
            # Try to locate script in installed package using importlib.resources
            script_path = None
            try:
                package = resources.files("python_package_folder")
                script_resource = package / "scripts" / "get-next-version.cjs"
                if script_resource.is_file():
                    # Try direct path conversion first (normal file system install)
                    try:
                        script_path_candidate = Path(str(script_resource))
                        if script_path_candidate.exists():
                            script_path = script_path_candidate
                    except (TypeError, ValueError):
                        pass

                    # If direct path didn't work, try as_file() for zip/pex installs
                    if script_path is None:
                        try:
                            temp_script_context = resources.as_file(script_resource)
                            script_path = temp_script_context.__enter__()
                        except (TypeError, ValueError, OSError):
                            pass
            except (ImportError, ModuleNotFoundError, TypeError, AttributeError, OSError):
                pass

            # Fallback: try relative to package directory
            if script_path is None:
                package_dir = Path(__file__).parent
                fallback_script = package_dir / "scripts" / "get-next-version.cjs"
                if fallback_script.exists():
                    script_path = fallback_script

        if not script_path:
            return None

        # Build command arguments
        cmd = ["node", str(script_path), str(project_root)]
        if subfolder_path and package_name:
            # Workflow 1: subfolder build
            rel_path = (
                subfolder_path.relative_to(project_root)
                if subfolder_path.is_absolute()
                else subfolder_path
            )
            cmd.extend([str(rel_path), package_name])
        elif package_name:
            # Main package build with package_name (for registry queries)
            # Pass null for subfolder_path, then package_name
            cmd.extend(["", package_name])
        # Workflow 2: main package without package_name (no additional args needed)
        
        # Add repository information if provided
        if repository:
            cmd.append(repository)
            if repository_url:
                cmd.append(repository_url)

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=project_root,
            check=False,
        )

        if result.returncode != 0:
            # Log error details for debugging
            if result.stderr:
                print(
                    f"Warning: semantic-release version resolution failed: {result.stderr}",
                    file=sys.stderr,
                )
            elif result.stdout:
                print(
                    f"Warning: semantic-release version resolution failed: {result.stdout}",
                    file=sys.stderr,
                )
            return None

        version = result.stdout.strip()
        if version and version != "none":
            return version

        return None
    except FileNotFoundError:
        # Node.js not found (shouldn't happen if check_node_available() passed, but handle gracefully)
        if is_github_actions():
            error_msg = """Node.js is not available in this GitHub Actions workflow.

To fix this, add the following steps BEFORE running python-package-folder:

- name: Setup Node.js
  uses: actions/setup-node@v4
  with:
    node-version: '20'

- name: Install semantic-release
  run: |
    npm install -g semantic-release semantic-release-commit-filter

Alternatively, provide --version explicitly to skip automatic version resolution."""
            print(f"Error: {error_msg}", file=sys.stderr)
        else:
            print(
                "Warning: Node.js not found. Cannot resolve version via semantic-release.",
                file=sys.stderr,
            )
        return None
    except Exception as e:
        # Other errors (e.g., permission issues, script not found)
        print(
            f"Warning: Error resolving version via semantic-release: {e}",
            file=sys.stderr,
        )
        return None
    finally:
        # Clean up temporary file if we extracted from zip/pex
        # This must be at function level to ensure cleanup even on early return
        if temp_script_context is not None:
            try:
                temp_script_context.__exit__(None, None, None)
            except Exception:
                pass


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
        # A subfolder must be within the project root but not the main src/ directory
        is_subfolder = (
            src_dir.is_relative_to(project_root)
            and src_dir != project_root / "src"
            and src_dir != project_root
        )

        # Resolve version via semantic-release if not provided and needed
        resolved_version = args.version
        if not resolved_version and not args.analyze_only:
            # Version is needed for subfolder builds or when publishing main package
            if is_subfolder or args.publish:
                print("No --version provided, attempting to resolve via semantic-release...")
                # Get repository info if publishing
                repository = args.publish if args.publish else None
                repository_url = args.repository_url if args.publish else None
                
                if is_subfolder:
                    # Workflow 1: subfolder build
                    # src_dir is guaranteed to be relative to project_root due to is_subfolder check
                    package_name = args.package_name or src_dir.name.replace("_", "-").replace(
                        " ", "-"
                    ).lower().strip("-")
                    subfolder_rel_path = src_dir.relative_to(project_root)
                    resolved_version = resolve_version_via_semantic_release(
                        project_root,
                        subfolder_rel_path,
                        package_name,
                        repository=repository,
                        repository_url=repository_url,
                    )
                else:
                    # Workflow 2: main package
                    # For main package, we need package_name from pyproject.toml for registry queries
                    package_name_for_registry = None
                    if repository:
                        try:
                            import tomllib
                            pyproject_path = project_root / "pyproject.toml"
                            if pyproject_path.exists():
                                with open(pyproject_path, "rb") as f:
                                    data = tomllib.load(f)
                                    package_name_for_registry = data.get("project", {}).get("name")
                        except Exception:
                            pass
                    
                    resolved_version = resolve_version_via_semantic_release(
                        project_root,
                        subfolder_path=None,
                        package_name=package_name_for_registry,
                        repository=repository,
                        repository_url=repository_url,
                    )

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
