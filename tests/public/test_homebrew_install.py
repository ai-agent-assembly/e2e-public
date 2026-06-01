"""Homebrew tap and curl installer verification (gated).

Both test groups are explicitly skipped until the upstream prerequisites are
met:

- Homebrew tap tests: require ``homebrew-agent-assembly`` tap to publish a
  formula with a built bottle.  Gate controlled by env var
  ``AASM_HOMEBREW_GATE=1``.
- curl installer tests: require a public static endpoint serving the install
  script.  Gate controlled by env var ``AASM_CURL_INSTALLER_GATE=1``.

Set the respective gate variable to ``1`` (e.g. in CI) to opt the tests in
once the upstream prerequisites are satisfied.
"""

from __future__ import annotations

import os
import subprocess

import pytest

from tests.public.conftest import skip_if_binary_missing

TAP_NAME = "agent-assembly/agent-assembly"
BREW_FORMULA = "aasm"
CURL_INSTALLER_URL = (
    "https://raw.githubusercontent.com/AI-agent-assembly/agent-assembly/master/install.sh"
)

_HOMEBREW_GATE = os.environ.get("AASM_HOMEBREW_GATE", "0") == "1"
_CURL_GATE = os.environ.get("AASM_CURL_INSTALLER_GATE", "0") == "1"

_HOMEBREW_SKIP_REASON = (
    "Homebrew tap formula not yet published — set AASM_HOMEBREW_GATE=1 to enable"
)
_CURL_SKIP_REASON = (
    "curl installer endpoint not yet available — set AASM_CURL_INSTALLER_GATE=1 to enable"
)

COMPONENT_BREW = "homebrew-agent-assembly"


@pytest.mark.release
@pytest.mark.skipif(not _HOMEBREW_GATE, reason=_HOMEBREW_SKIP_REASON)
def test_homebrew_tap_is_valid() -> None:
    """brew tap agent-assembly/agent-assembly succeeds."""
    skip_if_binary_missing("brew")
    result = subprocess.run(
        ["brew", "tap", TAP_NAME],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT_BREW}] brew tap {TAP_NAME!r} failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )


@pytest.mark.release
@pytest.mark.skipif(not _HOMEBREW_GATE, reason=_HOMEBREW_SKIP_REASON)
def test_homebrew_install_aasm() -> None:
    """brew install {formula} installs aasm and aasm --version exits 0."""
    skip_if_binary_missing("brew")
    install_result = subprocess.run(
        ["brew", "install", f"{TAP_NAME}/{BREW_FORMULA}"],
        capture_output=True,
        text=True,
    )
    assert install_result.returncode == 0, (
        f"[{COMPONENT_BREW}] brew install {BREW_FORMULA!r} failed "
        f"(exit {install_result.returncode})\n"
        f"stdout: {install_result.stdout.strip()}\nstderr: {install_result.stderr.strip()}"
    )
    version_result = subprocess.run(
        ["aasm", "--version"],
        capture_output=True,
        text=True,
    )
    assert version_result.returncode == 0, (
        f"[{COMPONENT_BREW}] aasm --version failed after brew install "
        f"(exit {version_result.returncode})\n"
        f"stderr: {version_result.stderr.strip()}"
    )
    assert version_result.stdout.strip(), (
        f"[{COMPONENT_BREW}] aasm --version produced empty output"
    )
