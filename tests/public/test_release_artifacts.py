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
import os
import stat
import subprocess
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.public.conftest import platform_asset_suffix, release_version

COMPONENT = "agent-assembly"
GH_ORG = "AI-agent-assembly"
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
            f"[{COMPONENT}] Release tag mismatch: expected {tag!r}, "
            f"got {data.get('tag_name')!r}"
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
