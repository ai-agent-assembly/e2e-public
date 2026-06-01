"""Shared pytest fixtures for public integration tests."""

from __future__ import annotations

import importlib.util
import os
import shutil

import pytest


@pytest.fixture(scope="session")
def install_mode() -> str:
    """Return the active installation mode from the environment (default: source)."""
    return os.environ.get("AASM_INSTALL_MODE", "source")


def skip_if_binary_missing(binary: str) -> None:
    """Skip the current test when *binary* is not found in PATH."""
    if shutil.which(binary) is None:
        pytest.skip(f"{binary!r} not found in PATH — install the binary to run this test")


def skip_if_package_missing(package: str) -> None:
    """Skip the current test when the Python *package* is not importable."""
    try:
        spec = importlib.util.find_spec(package)
        if spec is None:
            pytest.skip(f"Python package {package!r} not installed")
    except ModuleNotFoundError:
        pytest.skip(f"Python package {package!r} not installed (parent package absent)")
