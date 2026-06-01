"""Release artifact verification: GitHub Release binary download, checksum, and execute.

All tests in this module require ``AASM_RELEASE_VERSION`` to be set in the
environment.  When the variable is absent the tests are skipped.  Failures are
classified as one of:

- ``release_blocker``  — the GitHub Release is missing or the binary is broken.
- ``known_prerequisite`` — the release has not been published yet.
- ``external_flake``     — transient network or GitHub API issue.
"""

from __future__ import annotations

import hashlib
import json
import stat
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from tests.public.conftest import platform_asset_suffix, release_version

COMPONENT = "agent-assembly"
GH_ORG = "ai-agent-assembly"
GH_REPO = "agent-assembly"


def _require_version() -> str:
    """Return the release version or skip the test when unset."""
    v = release_version()
    if v is None:
        pytest.skip("AASM_RELEASE_VERSION not set — skipping release artifact tests")
    return v


def _github_release_url(tag: str) -> str:
    return f"https://api.github.com/repos/{GH_ORG}/{GH_REPO}/releases/tags/{tag}"


@pytest.mark.release
def test_github_release_exists() -> None:
    """GitHub Release for the configured version exists and is published."""
    version = _require_version()
    tag = f"v{version}" if not version.startswith("v") else version
    url = _github_release_url(tag)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        assert data.get("tag_name") == tag, (
            f"[{COMPONENT}] Release tag mismatch: expected {tag!r}, got {data.get('tag_name')!r}"
        )
        assert not data.get("draft", True), (
            f"[{COMPONENT}] Release {tag!r} exists but is still a draft — "
            "classification: known_prerequisite"
        )
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            pytest.fail(
                f"[{COMPONENT}] GitHub Release {tag!r} not found — "
                "classification: known_prerequisite (release not yet published)"
            )
        pytest.fail(
            f"[{COMPONENT}] GitHub API returned HTTP {exc.code} for {url} — "
            "classification: external_flake"
        )
    except urllib.error.URLError as exc:
        pytest.fail(
            f"[{COMPONENT}] Could not reach GitHub API: {exc.reason} — "
            "classification: external_flake"
        )


@pytest.mark.release
def test_github_release_has_platform_asset() -> None:
    """GitHub Release has a binary asset matching the current platform."""
    version = _require_version()
    tag = f"v{version}" if not version.startswith("v") else version
    suffix = platform_asset_suffix()
    url = _github_release_url(tag)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
        assets = [a["name"] for a in data.get("assets", [])]
        matching = [a for a in assets if a.endswith(suffix)]
        assert matching, (
            f"[{COMPONENT}] No asset matching suffix {suffix!r} in release {tag!r}. "
            f"Available assets: {assets!r} — "
            "classification: release_blocker"
        )
    except urllib.error.HTTPError as exc:
        pytest.skip(
            f"[{COMPONENT}] GitHub Release {tag!r} returned HTTP {exc.code} — "
            "classification: known_prerequisite (release not yet published)"
        )
    except urllib.error.URLError as exc:
        pytest.skip(
            f"[{COMPONENT}] Could not reach GitHub API: {exc.reason} — "
            "classification: external_flake"
        )


@pytest.mark.release
def test_github_release_asset_checksum(tmp_path: Path) -> None:
    """Downloaded GitHub Release asset matches its published SHA256 checksum."""
    version = _require_version()
    tag = f"v{version}" if not version.startswith("v") else version
    suffix = platform_asset_suffix()

    try:
        req = urllib.request.Request(
            _github_release_url(tag), headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        pytest.skip(
            f"[{COMPONENT}] Cannot fetch release metadata: {exc} — "
            "classification: known_prerequisite"
        )

    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    asset_name = next((n for n in assets if n.endswith(suffix)), None)
    checksums_name = next((n for n in assets if "checksums" in n.lower()), None)

    if asset_name is None:
        pytest.skip(
            f"[{COMPONENT}] No platform asset ({suffix!r}) in release {tag!r} — "
            "classification: known_prerequisite"
        )
    if checksums_name is None:
        pytest.skip(
            f"[{COMPONENT}] No checksums file in release {tag!r} — "
            "classification: known_prerequisite"
        )

    asset_path = tmp_path / asset_name
    checksums_path = tmp_path / checksums_name
    for url, dest in ((assets[asset_name], asset_path), (assets[checksums_name], checksums_path)):
        with urllib.request.urlopen(url, timeout=60) as resp:
            dest.write_bytes(resp.read())

    checksums_text = checksums_path.read_text()
    expected_sha = next(
        (line.split()[0] for line in checksums_text.splitlines() if asset_name in line),
        None,
    )
    if expected_sha is None:
        pytest.skip(
            f"[{COMPONENT}] {asset_name!r} not listed in checksums file — "
            "classification: known_prerequisite"
        )

    actual_sha = hashlib.sha256(asset_path.read_bytes()).hexdigest()
    assert actual_sha == expected_sha, (
        f"[{COMPONENT}] SHA256 mismatch for {asset_name!r}: "
        f"expected {expected_sha!r}, got {actual_sha!r} — "
        "classification: release_blocker"
    )


@pytest.mark.release
def test_github_release_binary_executes(tmp_path: Path) -> None:
    """Downloaded aasm binary from GitHub Release runs and exits 0 on --version."""
    version = _require_version()
    tag = f"v{version}" if not version.startswith("v") else version
    suffix = platform_asset_suffix()

    try:
        req = urllib.request.Request(
            _github_release_url(tag), headers={"Accept": "application/vnd.github+json"}
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        pytest.skip(
            f"[{COMPONENT}] Cannot fetch release metadata: {exc} — "
            "classification: known_prerequisite"
        )

    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    asset_name = next((n for n in assets if n.endswith(suffix)), None)
    if asset_name is None:
        pytest.skip(
            f"[{COMPONENT}] No platform asset ({suffix!r}) in release {tag!r} — "
            "classification: known_prerequisite"
        )

    asset_path = tmp_path / asset_name
    with urllib.request.urlopen(assets[asset_name], timeout=60) as resp:
        asset_path.write_bytes(resp.read())

    extract_dir = tmp_path / "extracted"
    extract_dir.mkdir()
    if asset_name.endswith(".tar.gz"):
        import tarfile

        with tarfile.open(asset_path) as tf:
            tf.extractall(extract_dir)  # noqa: S202 — controlled test artifact
    else:
        import shutil

        shutil.copy(asset_path, extract_dir / "aasm")

    binary = next(
        (p for p in extract_dir.rglob("aasm") if p.is_file()),
        None,
    )
    if binary is None:
        pytest.fail(
            f"[{COMPONENT}] No 'aasm' binary found in extracted {asset_name!r} — "
            "classification: release_blocker"
        )

    binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    result = subprocess.run([str(binary), "--version"], capture_output=True, text=True)  # noqa: S603
    assert result.returncode == 0, (
        f"[{COMPONENT}] {binary.name} --version exited {result.returncode}\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()} — "
        "classification: release_blocker"
    )
    assert result.stdout.strip(), (
        f"[{COMPONENT}] {binary.name} --version produced empty output — "
        "classification: release_blocker"
    )
