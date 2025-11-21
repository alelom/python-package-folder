"""Tests for publisher functionality."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from python_package_folder import Publisher, Repository


@pytest.fixture
def test_dist_dir(tmp_path: Path) -> Path:
    """Create a test dist directory with distribution files."""
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    # Create some distribution files
    (dist_dir / "package-1.0.0-py3-none-any.whl").write_text("fake wheel")
    (dist_dir / "package-1.0.0.tar.gz").write_text("fake source")
    (dist_dir / "other-package-2.0.0-py3-none-any.whl").write_text("fake wheel")

    return dist_dir


class TestPublisher:
    """Tests for Publisher class."""

    def test_init_with_repository_string(self, test_dist_dir: Path) -> None:
        """Test initialization with repository as string."""
        publisher = Publisher(
            repository="pypi",
            dist_dir=test_dist_dir,
        )

        assert publisher.repository == Repository.PYPI

    def test_init_with_repository_enum(self, test_dist_dir: Path) -> None:
        """Test initialization with repository as enum."""
        publisher = Publisher(
            repository=Repository.PYPI_TEST,
            dist_dir=test_dist_dir,
        )

        assert publisher.repository == Repository.PYPI_TEST

    def test_init_invalid_repository(self, test_dist_dir: Path) -> None:
        """Test initialization with invalid repository."""
        with pytest.raises(ValueError, match="Invalid repository"):
            Publisher(repository="invalid", dist_dir=test_dist_dir)

    def test_get_repository_url_pypi(self, test_dist_dir: Path) -> None:
        """Test getting PyPI repository URL."""
        publisher = Publisher(repository=Repository.PYPI, dist_dir=test_dist_dir)

        url = publisher._get_repository_url()

        assert url == "https://upload.pypi.org/legacy/"

    def test_get_repository_url_testpypi(self, test_dist_dir: Path) -> None:
        """Test getting TestPyPI repository URL."""
        publisher = Publisher(repository=Repository.PYPI_TEST, dist_dir=test_dist_dir)

        url = publisher._get_repository_url()

        assert url == "https://test.pypi.org/legacy/"

    def test_get_repository_url_custom(self, test_dist_dir: Path) -> None:
        """Test getting custom repository URL."""
        custom_url = "https://custom.pypi.org/legacy/"
        publisher = Publisher(
            repository=Repository.PYPI,
            dist_dir=test_dist_dir,
            repository_url=custom_url,
        )

        url = publisher._get_repository_url()

        assert url == custom_url

    @patch("python_package_folder.publisher.subprocess.run")
    def test_check_twine_installed(self, mock_run: MagicMock, test_dist_dir: Path) -> None:
        """Test checking if twine is installed."""
        publisher = Publisher(repository=Repository.PYPI, dist_dir=test_dist_dir)

        mock_run.return_value = MagicMock(returncode=0)
        result = publisher._check_twine_installed()

        assert result is True
        mock_run.assert_called_once()

    @patch("python_package_folder.publisher.subprocess.run")
    def test_check_twine_not_installed(self, mock_run: MagicMock, test_dist_dir: Path) -> None:
        """Test when twine is not installed."""
        publisher = Publisher(repository=Repository.PYPI, dist_dir=test_dist_dir)

        mock_run.side_effect = FileNotFoundError()
        result = publisher._check_twine_installed()

        assert result is False

    def test_publish_filters_by_package_name(self, test_dist_dir: Path) -> None:
        """Test that publish filters files by package name."""
        publisher = Publisher(
            repository=Repository.PYPI,
            dist_dir=test_dist_dir,
            package_name="package",
            version="1.0.0",
        )

        # Mock subprocess to capture command
        with patch("python_package_folder.publisher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            # Mock credentials
            with patch.object(publisher, "_get_credentials", return_value=("user", "pass")):
                publisher.publish()

            # Check that only package-1.0.0 files are in the command
            call_args = mock_run.call_args[0][0]
            file_args = [arg for arg in call_args if str(test_dist_dir) in str(arg)]

            assert len(file_args) == 2  # wheel and source dist
            assert all("package-1.0.0" in str(f) for f in file_args)
            assert not any("other-package" in str(f) for f in file_args)

    def test_publish_filters_by_version(self, test_dist_dir: Path) -> None:
        """Test that publish filters files by version."""
        publisher = Publisher(
            repository=Repository.PYPI,
            dist_dir=test_dist_dir,
            package_name="package",
            version="1.0.0",
        )

        with patch("python_package_folder.publisher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with patch.object(publisher, "_get_credentials", return_value=("user", "pass")):
                publisher.publish()

            call_args = mock_run.call_args[0][0]
            file_args = [arg for arg in call_args if str(test_dist_dir) in str(arg)]

            # Should only include 1.0.0 files, not 2.0.0
            assert all("1.0.0" in str(f) for f in file_args)

    def test_publish_no_filtering(self, test_dist_dir: Path) -> None:
        """Test that publish includes all files when no filter specified."""
        publisher = Publisher(
            repository=Repository.PYPI,
            dist_dir=test_dist_dir,
        )

        with patch("python_package_folder.publisher.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)

            with patch.object(publisher, "_get_credentials", return_value=("user", "pass")):
                publisher.publish()

            call_args = mock_run.call_args[0][0]
            file_args = [arg for arg in call_args if str(test_dist_dir) in str(arg)]

            # Should include all distribution files
            assert len(file_args) == 3

    def test_publish_raises_when_no_files(self, tmp_path: Path) -> None:
        """Test that publish raises when no distribution files found."""
        empty_dist = tmp_path / "dist"
        empty_dist.mkdir()

        publisher = Publisher(repository=Repository.PYPI, dist_dir=empty_dist)

        with pytest.raises(ValueError, match="No distribution files found"):
            publisher.publish()

    def test_publish_raises_when_no_matching_files(self, test_dist_dir: Path) -> None:
        """Test that publish raises when no files match filter."""
        publisher = Publisher(
            repository=Repository.PYPI,
            dist_dir=test_dist_dir,
            package_name="nonexistent",
            version="9.9.9",
        )

        with pytest.raises(ValueError, match="No distribution files found matching"):
            publisher.publish()

    def test_auto_detect_token_username(self, test_dist_dir: Path) -> None:
        """Test auto-detection of __token__ when API token is provided."""
        publisher = Publisher(
            repository=Repository.PYPI,
            dist_dir=test_dist_dir,
            username="alelom",
            password="pypi-AgENdGVzdC5weXBpLm9yZwIk",
        )

        username, password = publisher._get_credentials()

        assert username == "__token__"
        assert password == "pypi-AgENdGVzdC5weXBpLm9yZwIk"
