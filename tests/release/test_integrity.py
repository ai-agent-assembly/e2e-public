"""AC4: checksums are validated, and the signature-verification gap is reported.

Three layers:

* **Offline (always runs):** parse the sample ``SHA256SUMS`` and assert it covers
  every expected platform binary with a well-formed digest — the checksum logic.
* **Live (skip-guarded):** download the platform tarball *and* the release's
  ``SHA256SUMS``, recompute the digest, and assert it matches the published one.
* **Gap report (AC4 "OR explicit gap"):** the release publishes a cosign signature
  (``SHA256SUMS.cosign.bundle``), but this harness cannot *verify* it — that needs
  the ``cosign`` tool plus a Sigstore trust root and network. Rather than silently
  pass, an ``xfail`` records the gap so it is visible in the report, not hidden.

Finding (2026-06): the agent-assembly release pipeline publishes ``SHA256SUMS``
on every release and, from ``v0.0.1-alpha.9`` onward, a ``SHA256SUMS.cosign.bundle``
signature. Checksum integrity is therefore fully verifiable here; signature
*verification* is the documented, reported gap.
"""

from __future__ import annotations

import hashlib
import re
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from tests.public.conftest import platform_asset_suffix
from tests.release import manifest
from tests.release.checksums import parse_sha256sums
from tests.release.conftest import fetch_release_metadata, release_tag, require_release_version

COMPONENT = "agent-assembly"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "release"
_FIXTURE_SUMS = _FIXTURE_DIR / "sample_SHA256SUMS"


@pytest.mark.release
def test_sample_checksums_cover_every_expected_binary() -> None:
    """The offline SHA256SUMS lists a digest for every expected platform binary."""
    records = parse_sha256sums(_FIXTURE_SUMS.read_text())
    for asset in manifest.expected_platform_assets():
        assert asset.asset_name in records, (
            f"{asset.asset_name!r} ({asset.platform}) absent from SHA256SUMS"
        )


@pytest.mark.release
def test_sample_checksum_digests_are_well_formed() -> None:
    """Every digest in the offline SHA256SUMS is a 64-char lowercase hex string."""
    records = parse_sha256sums(_FIXTURE_SUMS.read_text())
    for name, digest in records.items():
        assert _SHA256_RE.match(digest), f"malformed sha256 for {name!r}: {digest!r}"


@pytest.mark.release
def test_live_asset_checksum_matches_published(tmp_path: Path) -> None:
    """Downloaded platform tarball matches its published SHA256SUMS digest.

    Skip-guarded: needs AASM_RELEASE_VERSION + network + a SHA256SUMS file in the
    release. A *present* asset whose recomputed digest disagrees is a hard failure.
    """
    version = require_release_version()
    tag = release_tag(version)
    suffix = platform_asset_suffix()
    data = fetch_release_metadata(tag)

    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    asset_name = next((n for n in assets if n.endswith(suffix)), None)
    if asset_name is None:
        pytest.skip(
            f"[{COMPONENT}] no platform asset ({suffix!r}) in {tag!r} — binary for "
            "the host not available (AASM_RELEASE_VERSION)"
        )
    if manifest.checksums_asset_name() not in assets:
        pytest.skip(
            f"[{COMPONENT}] no SHA256SUMS in {tag!r} — checksum file not published "
            "(classification: known_prerequisite, AASM_RELEASE_VERSION)"
        )

    try:
        with urllib.request.urlopen(assets[asset_name], timeout=60) as resp:  # noqa: S310
            asset_bytes = resp.read()
        with urllib.request.urlopen(  # noqa: S310
            assets[manifest.checksums_asset_name()], timeout=30
        ) as resp:
            sums_text = resp.read().decode("utf-8", "replace")
    except urllib.error.URLError as exc:
        pytest.skip(
            f"[{COMPONENT}] could not download asset/checksums ({exc}) — offline "
            "environment (classification: external_flake)"
        )

    records = parse_sha256sums(sums_text)
    expected = records.get(asset_name)
    if expected is None:
        pytest.fail(
            f"[{COMPONENT}] {asset_name!r} not listed in published SHA256SUMS — "
            "classification: release_blocker"
        )

    actual = hashlib.sha256(asset_bytes).hexdigest()
    assert actual == expected, (
        f"[{COMPONENT}] SHA256 mismatch for {asset_name!r}: expected {expected!r}, "
        f"got {actual!r} — classification: release_blocker"
    )


@pytest.mark.release
@pytest.mark.xfail(
    reason=(
        "AAASM-3161 gap: release publishes SHA256SUMS.cosign.bundle but this harness "
        "cannot verify the cosign signature — needs the cosign tool + a Sigstore trust "
        "root + network. Tracked as a known gap, not silently passed."
    ),
    strict=False,
    raises=AssertionError,
)
def test_signature_verification_gap_is_reported() -> None:
    """Document the signature-verification gap explicitly (AC4 'OR explicit gap').

    The release ships a cosign signature bundle over SHA256SUMS, but signature
    *verification* is unimplemented here. This xfail makes the gap a first-class,
    reported outcome — flipping to a real cosign verification removes the xfail.
    """
    signature_is_verified = False
    assert signature_is_verified, (
        "cosign signature verification of SHA256SUMS.cosign.bundle is not yet "
        "implemented in this harness (AAASM-3161 documented gap)"
    )
