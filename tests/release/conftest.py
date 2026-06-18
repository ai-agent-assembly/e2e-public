"""Fixtures and skip-guard helpers for release artifact integrity tests (AAASM-3161).

The suite is offline-first: the manifest, the asset-list validation logic, the
checksum-record parsing, and the evidence-table writer all run against the
checked-in ``tests/fixtures/release/`` sample with no network. The *live*
assertions (a real release exists, its binary runs, its SDK metadata matches)
require ``AASM_RELEASE_VERSION`` plus network/tooling and skip cleanly with a
justified reason (env requirement or AAASM-NNN) per ``aasm_verify.skip_audit``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.public.conftest import release_version

GH_ORG = "ai-agent-assembly"
GH_REPO = "agent-assembly"

# Where the offline release-assets snapshot lives.
_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "release"
_SAMPLE_ASSETS = _FIXTURE_DIR / "sample_release_assets.json"


def require_release_version() -> str:
    """Return ``AASM_RELEASE_VERSION`` or skip with a justified reason.

    Live release assertions cannot run without a requested version; the absence
    of the env var is a legitimate, justified skip (names the env requirement).
    """
    v = release_version()
    if v is None:
        pytest.skip(
            "AASM_RELEASE_VERSION not set — set AASM_RELEASE_VERSION to run "
            "live release integrity checks"
        )
    return v


def release_tag(version: str) -> str:
    """Normalize a bare version to its GitHub Release tag (``vX.Y.Z``)."""
    return version if version.startswith("v") else f"v{version}"


def github_release_url(tag: str) -> str:
    """Return the GitHub Releases API URL for a release tag."""
    return f"https://api.github.com/repos/{GH_ORG}/{GH_REPO}/releases/tags/{tag}"


def fetch_release_metadata(tag: str) -> dict:
    """Fetch a release's API metadata, or skip with a justified reason.

    A missing release or any network/API error is a justified skip: the input
    the test needs is not available offline. A *present* release that fails an
    integrity assertion is a hard failure raised by the test itself, not here.
    """
    url = github_release_url(tag)
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json"})
        with urllib.request.urlopen(req, timeout=20) as resp:  # noqa: S310 — fixed GitHub host
            return json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            pytest.skip(
                f"GitHub Release {tag!r} not published — release input not available "
                "(classification: known_prerequisite, AASM_RELEASE_VERSION)"
            )
        pytest.skip(
            f"GitHub API returned HTTP {exc.code} for {tag!r} — release metadata not "
            "available (classification: external_flake, network environment)"
        )
    except urllib.error.URLError as exc:
        pytest.skip(
            f"Could not reach GitHub API ({exc.reason}) — offline environment "
            "(classification: external_flake)"
        )


@pytest.fixture
def sample_release_data() -> dict:
    """Parsed offline release-assets snapshot from ``tests/fixtures/release/``.

    Drives the offline asset-list, integrity, and evidence-table tests so they
    exercise real validation logic without a network round-trip.
    """
    return json.loads(_SAMPLE_ASSETS.read_text())


@pytest.fixture
def sample_asset_names(sample_release_data: dict) -> list[str]:
    """The asset names from the offline snapshot."""
    return [a["name"] for a in sample_release_data["assets"]]
