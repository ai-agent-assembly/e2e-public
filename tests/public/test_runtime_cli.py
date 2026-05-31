"""Smoke tests for the aasm runtime CLI binary."""

from __future__ import annotations

import subprocess

import pytest

from tests.public.conftest import skip_if_binary_missing

COMPONENT = "agent-assembly"


@pytest.mark.runtime
def test_aasm_version() -> None:
    """aasm --version exits 0 and prints a version string."""
    skip_if_binary_missing("aasm")
    result = subprocess.run(["aasm", "--version"], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"[{COMPONENT}] aasm --version failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    assert result.stdout.strip(), f"[{COMPONENT}] aasm --version produced empty output"


@pytest.mark.runtime
def test_aasm_help() -> None:
    """aasm --help exits 0 and prints usage information."""
    skip_if_binary_missing("aasm")
    result = subprocess.run(["aasm", "--help"], capture_output=True, text=True)
    assert result.returncode == 0, (
        f"[{COMPONENT}] aasm --help failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    output = result.stdout.strip() + result.stderr.strip()
    assert output, f"[{COMPONENT}] aasm --help produced no output"
