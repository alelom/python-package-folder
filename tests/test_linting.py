"""Tests for code quality checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


class TestLinting:
    """Tests for linting and code quality."""

    def test_ruff_check_passes(self) -> None:
        """Test that ruff linting passes."""
        # Get the project root directory
        project_root = Path(__file__).parent.parent

        # Run ruff check
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "check", "."],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        # If ruff fails, print the output for debugging
        if result.returncode != 0:
            print("Ruff check failed with output:")
            print(result.stdout)
            print(result.stderr)

        assert result.returncode == 0, "Ruff linting should pass without errors"

    def test_ruff_format_check_passes(self) -> None:
        """Test that ruff format check passes.

        Note: This test may fail if files need formatting. Run `ruff format .` to fix.
        """
        # Get the project root directory
        project_root = Path(__file__).parent.parent

        # Run ruff format --check
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "format", "--check", "."],
            cwd=project_root,
            capture_output=True,
            text=True,
        )

        # If ruff format check fails, print the output for debugging
        if result.returncode != 0:
            print("Ruff format check failed with output:")
            print(result.stdout)
            print(result.stderr)
            print("\nTo fix formatting issues, run: ruff format .")

        # Note: We check format but don't fail the test if formatting is needed
        # This allows the test to document that formatting should be checked
        # In CI, the format check step will catch formatting issues
        assert result.returncode == 0, (
            "Ruff format check should pass. Run 'ruff format .' to fix formatting issues."
        )
