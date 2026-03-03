"""
Tests for version calculation functionality.

Tests the Python-native version calculator that replaces Node.js semantic-release.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest
import requests

from python_package_folder.version_calculator import (
    calculate_next_version,
    get_commits_since,
    get_latest_git_tag,
    parse_commit_for_bump,
    query_registry_version,
    resolve_version,
)


class TestQueryRegistryVersion:
    """Tests for registry version queries."""

    @patch("python_package_folder.version_calculator.requests.get")
    def test_query_pypi_version(self, mock_get: MagicMock) -> None:
        """Test querying PyPI for latest version."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "info": {"version": "1.2.3"},
            "releases": {"1.2.3": [], "1.2.2": []},
        }
        mock_get.return_value = mock_response

        version = query_registry_version("test-package", "pypi")
        assert version == "1.2.3"
        mock_get.assert_called_once_with(
            "https://pypi.org/pypi/test-package/json", timeout=10
        )

    @patch("python_package_folder.version_calculator.requests.get")
    def test_query_testpypi_version(self, mock_get: MagicMock) -> None:
        """Test querying TestPyPI for latest version."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "info": {"version": "0.9.5"},
            "releases": {"0.9.5": [], "0.9.4": []},
        }
        mock_get.return_value = mock_response

        version = query_registry_version("test-package", "testpypi")
        assert version == "0.9.5"
        mock_get.assert_called_once_with(
            "https://test.pypi.org/pypi/test-package/json", timeout=10
        )

    @patch("python_package_folder.version_calculator.requests.get")
    def test_query_pypi_version_not_found(self, mock_get: MagicMock) -> None:
        """Test querying PyPI when package doesn't exist."""
        mock_response = Mock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        version = query_registry_version("nonexistent-package", "pypi")
        assert version is None

    @patch("python_package_folder.version_calculator.requests.get")
    def test_query_pypi_version_fallback_to_releases(self, mock_get: MagicMock) -> None:
        """Test querying PyPI when info.version is missing, fallback to releases."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "releases": {"1.0.0": [], "1.1.0": [], "1.0.1": []},
        }
        mock_get.return_value = mock_response

        version = query_registry_version("test-package", "pypi")
        # Should get the latest from releases (sorted)
        assert version == "1.1.0"

    @patch("python_package_folder.version_calculator.requests.get")
    def test_query_azure_artifacts_version(self, mock_get: MagicMock) -> None:
        """Test querying Azure Artifacts (basic support, returns None for now)."""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_get.return_value = mock_response

        version = query_registry_version(
            "test-package",
            "azure",
            repository_url="https://pkgs.dev.azure.com/ORG/PROJECT/_packaging/FEED/pypi/upload",
        )
        # Azure Artifacts parsing not fully implemented, returns None
        assert version is None

    @patch("python_package_folder.version_calculator.requests.get")
    def test_query_registry_version_error_handling(self, mock_get: MagicMock) -> None:
        """Test that registry query errors are handled gracefully."""
        mock_get.side_effect = requests.RequestException("Network error")

        version = query_registry_version("test-package", "pypi")
        assert version is None


class TestGetLatestGitTag:
    """Tests for git tag version retrieval."""

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_latest_git_tag_main_package(self, mock_run: MagicMock) -> None:
        """Test getting latest git tag for main package (v1.2.3 format)."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "v1.2.3\nv1.2.2\nv1.1.0\n"
        mock_run.return_value = mock_result

        version = get_latest_git_tag(Path("/tmp/test"), is_subfolder=False)
        assert version == "1.2.3"
        mock_run.assert_called_once()
        assert "v*" in str(mock_run.call_args)

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_latest_git_tag_subfolder(self, mock_run: MagicMock) -> None:
        """Test getting latest git tag for subfolder (package-v1.2.3 format)."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "my-package-v1.2.3\nmy-package-v1.2.2\n"
        mock_run.return_value = mock_result

        version = get_latest_git_tag(
            Path("/tmp/test"), package_name="my-package", is_subfolder=True
        )
        assert version == "1.2.3"
        mock_run.assert_called_once()
        assert "my-package-v*" in str(mock_run.call_args)

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_latest_git_tag_no_tags(self, mock_run: MagicMock) -> None:
        """Test when no git tags exist."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        version = get_latest_git_tag(Path("/tmp/test"), is_subfolder=False)
        assert version is None

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_latest_git_tag_invalid_tags(self, mock_run: MagicMock) -> None:
        """Test when tags exist but don't match version format."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "invalid-tag\nanother-tag\n"
        mock_run.return_value = mock_result

        version = get_latest_git_tag(Path("/tmp/test"), is_subfolder=False)
        assert version is None


class TestGetCommitsSince:
    """Tests for getting commits since a baseline version."""

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_commits_since(self, mock_run: MagicMock) -> None:
        """Test getting commits since a baseline version."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "feat: add new feature\n\nfix: resolve bug\n\n"
        mock_run.return_value = mock_result

        commits = get_commits_since(Path("/tmp/test"), "1.2.3")
        assert len(commits) == 2
        assert "feat: add new feature" in commits[0]
        assert "fix: resolve bug" in commits[1]

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_commits_since_with_subfolder(self, mock_run: MagicMock) -> None:
        """Test getting commits filtered by subfolder path."""
        # Mock git tag lookup first
        mock_tag_result = Mock()
        mock_tag_result.returncode = 0
        mock_tag_result.stdout = "my-package-v1.2.3\n"
        
        # Mock git log result
        mock_log_result = Mock()
        mock_log_result.returncode = 0
        mock_log_result.stdout = "fix: update subfolder/file.py\n\n"
        
        mock_run.side_effect = [mock_tag_result, mock_log_result]

        commits = get_commits_since(
            Path("/tmp/test"), "1.2.3", subfolder_path=Path("src/my_subfolder"), package_name="my-package"
        )
        assert len(commits) == 1
        # Verify git log was called with path filter
        assert mock_run.call_count >= 2
        call_args = str(mock_run.call_args_list)
        assert "src/my_subfolder" in call_args or "my_subfolder" in call_args

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_commits_since_no_commits(self, mock_run: MagicMock) -> None:
        """Test when no commits exist since baseline."""
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_run.return_value = mock_result

        commits = get_commits_since(Path("/tmp/test"), "1.2.3")
        assert commits == []

    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_get_commits_since_git_error(self, mock_run: MagicMock) -> None:
        """Test handling of git command errors."""
        mock_result = Mock()
        mock_result.returncode = 1
        mock_run.return_value = mock_result

        commits = get_commits_since(Path("/tmp/test"), "1.2.3")
        assert commits == []


class TestParseCommitForBump:
    """Tests for parsing conventional commits to determine bump type."""

    def test_parse_commit_for_bump_major_breaking_footer(self) -> None:
        """Test BREAKING CHANGE in footer triggers major bump."""
        commit = "feat: add new API\n\nBREAKING CHANGE: old API removed"
        assert parse_commit_for_bump(commit) == "major"

    def test_parse_commit_for_bump_major_breaking_change_lowercase(self) -> None:
        """Test breaking change (lowercase) in footer triggers major bump."""
        commit = "fix: update dependency\n\nbreaking change: minimum version changed"
        assert parse_commit_for_bump(commit) == "major"

    def test_parse_commit_for_bump_major_exclamation(self) -> None:
        """Test ! after type triggers major bump."""
        assert parse_commit_for_bump("feat!: remove deprecated API") == "major"
        assert parse_commit_for_bump("fix!: change behavior") == "major"

    def test_parse_commit_for_bump_major_exclamation_with_scope(self) -> None:
        """Test ! after scope triggers major bump."""
        assert parse_commit_for_bump("feat(api)!: change response format") == "major"
        assert parse_commit_for_bump("fix(parser)!: update parsing logic") == "major"

    def test_parse_commit_for_bump_minor(self) -> None:
        """Test feat: triggers minor bump."""
        assert parse_commit_for_bump("feat: add new feature") == "minor"
        assert parse_commit_for_bump("feat(api): add endpoint") == "minor"

    def test_parse_commit_for_bump_patch_fix(self) -> None:
        """Test fix: triggers patch bump."""
        assert parse_commit_for_bump("fix: resolve bug") == "patch"
        assert parse_commit_for_bump("fix(parser): handle edge case") == "patch"

    def test_parse_commit_for_bump_patch_perf(self) -> None:
        """Test perf: triggers patch bump."""
        assert parse_commit_for_bump("perf: optimize queries") == "patch"
        assert parse_commit_for_bump("perf(cache): improve lookup") == "patch"

    def test_parse_commit_for_bump_none(self) -> None:
        """Test ignored commit types return None."""
        assert parse_commit_for_bump("docs: update README") is None
        assert parse_commit_for_bump("style: format code") is None
        assert parse_commit_for_bump("refactor: reorganize modules") is None
        assert parse_commit_for_bump("test: add unit tests") is None
        assert parse_commit_for_bump("build: update dependencies") is None
        assert parse_commit_for_bump("ci: update workflow") is None
        assert parse_commit_for_bump("chore: cleanup") is None
        assert parse_commit_for_bump("revert: revert previous commit") is None

    def test_parse_commit_for_bump_invalid_format(self) -> None:
        """Test non-conventional commits return None."""
        assert parse_commit_for_bump("random commit message") is None
        assert parse_commit_for_bump("") is None
        assert parse_commit_for_bump("Update file") is None

    def test_parse_commit_for_bump_multiline(self) -> None:
        """Test parsing multiline commit messages."""
        commit = """feat: add new feature

This is a detailed description of the feature.
It can span multiple lines.

More details here."""
        assert parse_commit_for_bump(commit) == "minor"


class TestCalculateNextVersion:
    """Tests for calculating next version from baseline and commits."""

    def test_calculate_next_version_patch(self) -> None:
        """Test patch version increment (1.2.3 → 1.2.4)."""
        commits = ["fix: resolve bug"]
        version = calculate_next_version("1.2.3", commits)
        assert version == "1.2.4"

    def test_calculate_next_version_minor(self) -> None:
        """Test minor version increment (1.2.3 → 1.3.0)."""
        commits = ["feat: add new feature"]
        version = calculate_next_version("1.2.3", commits)
        assert version == "1.3.0"

    def test_calculate_next_version_major(self) -> None:
        """Test major version increment (1.2.3 → 2.0.0)."""
        commits = ["feat!: remove deprecated API"]
        version = calculate_next_version("1.2.3", commits)
        assert version == "2.0.0"

    def test_calculate_next_version_major_from_breaking_footer(self) -> None:
        """Test major version increment from BREAKING CHANGE footer."""
        commits = ["feat: add feature\n\nBREAKING CHANGE: API changed"]
        version = calculate_next_version("1.2.3", commits)
        assert version == "2.0.0"

    def test_calculate_next_version_highest_bump_wins(self) -> None:
        """Test that highest bump type wins when multiple commits present."""
        commits = [
            "fix: resolve bug",
            "feat: add feature",
            "docs: update README",
        ]
        version = calculate_next_version("1.2.3", commits)
        # Should be minor (highest bump)
        assert version == "1.3.0"

    def test_calculate_next_version_major_overrides_minor(self) -> None:
        """Test that major bump overrides minor and patch."""
        commits = [
            "fix: resolve bug",
            "feat: add feature",
            "feat!: breaking change",
        ]
        version = calculate_next_version("1.2.3", commits)
        assert version == "2.0.0"

    def test_calculate_next_version_no_changes(self) -> None:
        """Test None when no relevant commits."""
        commits = ["docs: update README", "chore: cleanup"]
        version = calculate_next_version("1.2.3", commits)
        assert version is None

    def test_calculate_next_version_empty_commits(self) -> None:
        """Test None when no commits."""
        version = calculate_next_version("1.2.3", [])
        assert version is None

    def test_calculate_next_version_perf_triggers_patch(self) -> None:
        """Test perf: commits trigger patch bump."""
        commits = ["perf: optimize queries"]
        version = calculate_next_version("1.2.3", commits)
        assert version == "1.2.4"


class TestResolveVersion:
    """Integration tests for resolve_version function."""

    @patch("python_package_folder.version_calculator.query_registry_version")
    @patch("python_package_folder.version_calculator.get_commits_since")
    @patch("python_package_folder.version_calculator.calculate_next_version")
    def test_resolve_version_registry_first(
        self,
        mock_calculate: MagicMock,
        mock_commits: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Test that registry query is tried first."""
        mock_registry.return_value = "1.2.3"
        mock_commits.return_value = ["feat: add feature"]
        mock_calculate.return_value = "1.3.0"

        version, error = resolve_version(
            Path("/tmp/test"),
            package_name="test-package",
            repository="pypi",
        )

        assert version == "1.3.0"
        assert error is None
        mock_registry.assert_called_once()
        mock_commits.assert_called_once_with(Path("/tmp/test"), "1.2.3", None, "test-package")

    @patch("python_package_folder.version_calculator.query_registry_version")
    @patch("python_package_folder.version_calculator.get_latest_git_tag")
    @patch("python_package_folder.version_calculator.get_commits_since")
    @patch("python_package_folder.version_calculator.calculate_next_version")
    def test_resolve_version_git_fallback(
        self,
        mock_calculate: MagicMock,
        mock_commits: MagicMock,
        mock_git_tag: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Test fallback to git tags when registry query fails."""
        mock_registry.return_value = None
        mock_git_tag.return_value = "1.2.3"
        mock_commits.return_value = ["fix: resolve bug"]
        mock_calculate.return_value = "1.2.4"

        version, error = resolve_version(
            Path("/tmp/test"),
            package_name="test-package",
            repository="pypi",
        )

        assert version == "1.2.4"
        assert error is None
        mock_registry.assert_called_once()
        mock_git_tag.assert_called_once()

    @patch("python_package_folder.version_calculator.query_registry_version")
    @patch("python_package_folder.version_calculator.get_latest_git_tag")
    @patch("python_package_folder.version_calculator.subprocess.run")
    def test_resolve_version_no_baseline(
        self,
        mock_subprocess: MagicMock,
        mock_git_tag: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Test first release behavior when no baseline version is found."""
        mock_registry.return_value = None
        mock_git_tag.return_value = None
        
        # Mock git log for first release with conventional commits
        mock_result = Mock()
        mock_result.returncode = 0
        mock_result.stdout = "feat: initial feature\n\n"
        mock_subprocess.return_value = mock_result

        version, error = resolve_version(
            Path("/tmp/test"),
            package_name="test-package",
            repository="pypi",
        )

        # For first release with feat commit, should calculate 0.1.0 (0.0.0 + minor)
        assert version == "0.1.0"
        assert error is None

    @patch("python_package_folder.version_calculator.query_registry_version")
    @patch("python_package_folder.version_calculator.get_commits_since")
    @patch("python_package_folder.version_calculator.calculate_next_version")
    def test_resolve_version_subfolder(
        self,
        mock_calculate: MagicMock,
        mock_commits: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Test version resolution for subfolder builds."""
        mock_registry.return_value = "1.2.3"
        mock_commits.return_value = ["fix: update subfolder/file.py"]
        mock_calculate.return_value = "1.2.4"

        version, error = resolve_version(
            Path("/tmp/test"),
            package_name="my-package",
            subfolder_path=Path("src/my_subfolder"),
            repository="pypi",
        )

        assert version == "1.2.4"
        assert error is None
        # Verify subfolder path and package_name were passed to get_commits_since
        mock_commits.assert_called_once()
        call_args = mock_commits.call_args
        assert call_args[0][2] == Path("src/my_subfolder")
        assert call_args[0][3] == "my-package"

    @patch("python_package_folder.version_calculator.query_registry_version")
    @patch("python_package_folder.version_calculator.get_commits_since")
    @patch("python_package_folder.version_calculator.calculate_next_version")
    def test_resolve_version_no_release_needed(
        self,
        mock_calculate: MagicMock,
        mock_commits: MagicMock,
        mock_registry: MagicMock,
    ) -> None:
        """Test when no release is needed (no relevant commits)."""
        mock_registry.return_value = "1.2.3"
        mock_commits.return_value = ["docs: update README"]
        mock_calculate.return_value = None

        version, error = resolve_version(
            Path("/tmp/test"),
            package_name="test-package",
            repository="pypi",
        )

        assert version is None
        assert error is None  # No error, just no release needed
