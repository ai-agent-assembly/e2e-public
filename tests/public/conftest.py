"""Shared pytest fixtures for public integration tests."""

from __future__ import annotations

import importlib.util
import os
import platform
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


def release_version() -> str | None:
    """Return AASM_RELEASE_VERSION from environment, or None when unset."""
    return os.environ.get("AASM_RELEASE_VERSION")


def platform_asset_suffix() -> str:
    """Return the expected GitHub Release binary asset suffix for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        arch = "x86_64" if machine in ("x86_64", "amd64") else machine
        return f"linux-{arch}.tar.gz"
    if system == "darwin":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"darwin-{arch}.tar.gz"
    return f"{system}-{machine}.tar.gz"
