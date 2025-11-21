"""Python package folder - Build Python packages with external dependency management."""

__all__ = (
    "BuildManager",
    "ExternalDependency",
    "ExternalDependencyFinder",
    "ImportAnalyzer",
    "ImportInfo",
    "Publisher",
    "Repository",
    "SubfolderBuildConfig",
    "VersionManager",
    "find_project_root",
    "find_source_directory",
)

from .analyzer import ImportAnalyzer
from .finder import ExternalDependencyFinder
from .manager import BuildManager
from .publisher import Publisher, Repository
from .subfolder_build import SubfolderBuildConfig
from .types import ExternalDependency, ImportInfo
from .utils import find_project_root, find_source_directory
from .version import VersionManager
