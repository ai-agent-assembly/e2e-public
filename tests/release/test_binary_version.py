"""AC2: the runtime binary's reported version matches the requested release.

It is not enough that *a* binary runs — the artifact published under tag
``vX.Y.Z`` must actually be that version, or installers silently ship a stale
build. This downloads the current platform's release tarball, extracts the
``aasm`` binary, runs ``aasm --version`` and asserts the requested version string
appears in its output.

Fully skip-guarded: needs ``AASM_RELEASE_VERSION``, network, and a runnable
binary for the host platform. Download/extract failure or a binary built for a
foreign platform skips; a *present, runnable* binary whose version disagrees with
the requested release is a hard failure.
"""

from __future__ import annotations

import stat
import subprocess
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.public.conftest import platform_asset_suffix
from tests.release.conftest import fetch_release_metadata, release_tag, require_release_version

COMPONENT = "agent-assembly"


def _bare_version(version: str) -> str:
    """Strip a leading 'v' so the comparison ignores tag-vs-bare formatting."""
    return version[1:] if version.startswith("v") else version


@pytest.mark.release
def test_runtime_binary_version_matches_release(tmp_path: Path) -> None:
    """Downloaded aasm binary reports a version matching the requested release."""
    version = require_release_version()
    tag = release_tag(version)
    suffix = platform_asset_suffix()
    data = fetch_release_metadata(tag)

    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    asset_name = next((n for n in assets if n.endswith(suffix)), None)
    if asset_name is None:
        pytest.skip(
            f"[{COMPONENT}] no asset for this platform ({suffix!r}) in {tag!r} — "
            "binary for the host platform not available (AASM_RELEASE_VERSION)"
        )

    asset_path = tmp_path / asset_name
    try:
        with urllib.request.urlopen(assets[asset_name], timeout=60) as resp:  # noqa: S310
            asset_path.write_bytes(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        pytest.skip(
            f"[{COMPONENT}] could not download {asset_name!r} ({exc}) — offline "
            "environment (classification: external_flake)"
        )

    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    with tarfile.open(asset_path) as tf:
        tf.extractall(extract_dir)  # noqa: S202 — controlled test artifact

    binary = next((p for p in extract_dir.rglob("aasm") if p.is_file()), None)
    if binary is None:
        pytest.fail(
            f"[{COMPONENT}] no 'aasm' binary in {asset_name!r} — "
            "classification: release_blocker"
        )

    binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    try:
        result = subprocess.run(  # noqa: S603
            [str(binary), "--version"], capture_output=True, text=True, timeout=30
        )
    except OSError as exc:
        # A binary built for a different OS/arch cannot execute on this host.
        pytest.skip(
            f"[{COMPONENT}] {binary.name} not runnable on this host ({exc}) — "
            "binary built for a foreign platform (AASM_RELEASE_VERSION)"
        )

    assert result.returncode == 0, (
        f"[{COMPONENT}] {binary.name} --version exited {result.returncode}\n"
        f"stderr: {result.stderr.strip()} — classification: release_blocker"
    )
    output = result.stdout.strip()
    assert _bare_version(version) in output, (
        f"[{COMPONENT}] {binary.name} --version reported {output!r}, "
        f"expected to contain requested version {_bare_version(version)!r} — "
        "classification: release_blocker"
    )
