"""Homebrew tap and curl installer verification (gated).

Both test groups are explicitly skipped until the upstream prerequisites are
met:

- Homebrew tap tests: require ``homebrew-tap`` tap to publish a
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
import urllib.error
import urllib.request

import pytest

from tests.public.conftest import skip_if_binary_missing

TAP_NAME = "ai-agent-assembly/tap"
BREW_FORMULA = "aasm"
# Canonical served installer (AAASM-3948 / ADR-014). The tap repo was renamed to
# homebrew-tap so Homebrew resolves it as ai-agent-assembly/tap.
CURL_INSTALLER_URL = "https://agent-assembly.com/install.sh"

_HOMEBREW_GATE = os.environ.get("AASM_HOMEBREW_GATE", "0") == "1"
_CURL_GATE = os.environ.get("AASM_CURL_INSTALLER_GATE", "0") == "1"

_HOMEBREW_SKIP_REASON = (
    "Homebrew tap formula not yet published — set AASM_HOMEBREW_GATE=1 to enable"
)
_CURL_SKIP_REASON = (
    "curl installer endpoint not yet available — set AASM_CURL_INSTALLER_GATE=1 to enable"
)

COMPONENT_BREW = "homebrew-tap"


@pytest.mark.release
@pytest.mark.skipif(not _HOMEBREW_GATE, reason=_HOMEBREW_SKIP_REASON)
def test_homebrew_tap_is_valid() -> None:
    """brew tap ai-agent-assembly/tap succeeds."""
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
    assert version_result.stdout.strip(), f"[{COMPONENT_BREW}] aasm --version produced empty output"

    # AAASM-4448: the formula must provide the FULL binary set a fresh install is
    # supposed to ship, not just `aasm`. Assert `aa-gateway` is present and
    # runnable so a formula that omits it (the AAASM-4448 defect) fails here
    # instead of passing on the `aasm`-only check. This assertion is dormant
    # until AASM_HOMEBREW_GATE=1 opts the file in; once the AAASM-4455 formula fix
    # ships it must stay green in lockstep.
    gateway_result = subprocess.run(
        ["aa-gateway", "--help"],
        capture_output=True,
        text=True,
    )
    assert gateway_result.returncode == 0, (
        f"[{COMPONENT_BREW}] aa-gateway not installed/runnable after brew install "
        f"(exit {gateway_result.returncode}) — formula is incomplete (AAASM-4448)\n"
        f"stderr: {gateway_result.stderr.strip()}"
    )


@pytest.mark.release
@pytest.mark.skipif(not _HOMEBREW_GATE, reason=_HOMEBREW_SKIP_REASON)
def test_homebrew_installs_aa_api_server() -> None:
    """The formula must also install ``aa-api-server`` (AAASM-4447/4449).

    The full binary set a fresh Homebrew install should provide includes
    ``aa-api-server`` (the SDK's REST front door). AAASM-4449 (the release
    publishing the binary) and AAASM-4455 (the formula installing it) are both
    Done, so this now asserts for real instead of quarantining behind
    ``rc_pending``.
    """
    skip_if_binary_missing("brew")
    result = subprocess.run(
        ["aa-api-server", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT_BREW}] aa-api-server not installed/runnable after brew "
        f"install (exit {result.returncode}) — binary not published (AAASM-4449)\n"
        f"stderr: {result.stderr.strip()}"
    )


@pytest.mark.release
@pytest.mark.skipif(not _HOMEBREW_GATE, reason=_HOMEBREW_SKIP_REASON)
def test_homebrew_tap_then_short_install() -> None:
    """`brew tap ai-agent-assembly/tap && brew install aasm` works (AAASM-3950)."""
    skip_if_binary_missing("brew")
    tap = subprocess.run(["brew", "tap", TAP_NAME], capture_output=True, text=True)
    assert tap.returncode == 0, (
        f"[{COMPONENT_BREW}] brew tap {TAP_NAME!r} failed (exit {tap.returncode})\n"
        f"stderr: {tap.stderr.strip()}"
    )
    inst = subprocess.run(["brew", "install", BREW_FORMULA], capture_output=True, text=True)
    assert inst.returncode == 0, (
        f"[{COMPONENT_BREW}] brew install {BREW_FORMULA!r} (short name, after tap) failed "
        f"(exit {inst.returncode})\nstderr: {inst.stderr.strip()}"
    )


COMPONENT_CURL = "curl-installer"


@pytest.mark.release
@pytest.mark.skipif(not _CURL_GATE, reason=_CURL_SKIP_REASON)
def test_curl_installer_endpoint_reachable() -> None:
    """Public curl install script URL responds with HTTP 200."""
    try:
        req = urllib.request.Request(CURL_INSTALLER_URL, method="HEAD")
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
        assert status == 200, (
            f"[{COMPONENT_CURL}] install script URL returned HTTP {status} — "
            "classification: known_prerequisite (endpoint not yet available)"
        )
    except urllib.error.HTTPError as exc:
        pytest.fail(
            f"[{COMPONENT_CURL}] install script URL returned HTTP {exc.code} — "
            "classification: known_prerequisite"
        )
    except urllib.error.URLError as exc:
        pytest.fail(
            f"[{COMPONENT_CURL}] install script URL unreachable: {exc.reason} — "
            "classification: external_flake"
        )


@pytest.mark.release
@pytest.mark.skipif(not _CURL_GATE, reason=_CURL_SKIP_REASON)
def test_curl_installer_runs(tmp_path: Path) -> None:  # noqa: F821 — Path imported lazily
    """curl-piped installer script exits 0 and places aasm in PATH or a known directory."""
    from pathlib import Path

    skip_if_binary_missing("curl")
    skip_if_binary_missing("bash")

    install_dir = tmp_path / "aasm-install"
    install_dir.mkdir()
    script_path = tmp_path / "install.sh"

    with urllib.request.urlopen(CURL_INSTALLER_URL, timeout=30) as resp:
        script_path.write_bytes(resp.read())

    result = subprocess.run(
        ["bash", str(script_path), "--install-dir", str(install_dir)],
        capture_output=True,
        text=True,
        env={**os.environ, "AASM_INSTALL_DIR": str(install_dir)},
    )
    assert result.returncode == 0, (
        f"[{COMPONENT_CURL}] installer script failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    binary = next(
        (p for p in Path(install_dir).rglob("aasm") if p.is_file()),
        None,
    )
    assert binary is not None, (
        f"[{COMPONENT_CURL}] No 'aasm' binary found in {install_dir} after install"
    )
    version_result = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
    )
    assert version_result.returncode == 0, (
        f"[{COMPONENT_CURL}] aasm --version failed (exit {version_result.returncode})\n"
        f"stderr: {version_result.stderr.strip()}"
    )
