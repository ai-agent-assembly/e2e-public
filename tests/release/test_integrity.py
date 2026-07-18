"""AC4: checksums are validated, and the release signature is verified.

Three layers:

* **Offline (always runs):** parse the sample ``SHA256SUMS`` and assert it covers
  every expected platform binary with a well-formed digest — the checksum logic.
* **Live (skip-guarded):** download the platform tarball *and* the release's
  ``SHA256SUMS``, recompute the digest, and assert it matches the published one.
* **Signature (skip-guarded):** the release publishes a keyless cosign signature
  (``SHA256SUMS.cosign.bundle``) over ``SHA256SUMS``; when the ``cosign`` tool,
  network, and a published release are all present, this *actually verifies* the
  bundle against the GitHub Actions OIDC signing identity. When that toolchain or
  release is absent it skips cleanly on the real prerequisite (env
  classification) — never a hardcoded pass/fail that reports nothing.

Finding (2026-06): the agent-assembly release pipeline publishes ``SHA256SUMS``
on every release and, from ``v0.0.1-alpha.9`` onward, a ``SHA256SUMS.cosign.bundle``
signature — so both checksum integrity *and* signature verification are exercised
here against a real release.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
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


# The keyless cosign signing identity for the agent-assembly release pipeline: any
# workflow under the release repo, issued by the GitHub Actions OIDC provider. A
# regexp on the identity pins the signer to the release repo while staying robust
# to workflow-file renames.
_COSIGN_IDENTITY_RE = r"^https://github\.com/ai-agent-assembly/agent-assembly/"
_COSIGN_OIDC_ISSUER = "https://token.actions.githubusercontent.com"


@pytest.mark.release
def test_live_signature_verifies_over_sha256sums(tmp_path: Path) -> None:
    """The published cosign bundle is a valid signature over ``SHA256SUMS``.

    AC4 ("checksums/signatures are validated"): the release ships a keyless cosign
    signature bundle over ``SHA256SUMS`` (from ``v0.0.1-alpha.9`` onward). This
    downloads both and runs ``cosign verify-blob`` against the GitHub Actions OIDC
    signing identity — a real verification, not a reported gap.

    Skip-guarded on the genuine prerequisites: a requested release
    (``AASM_RELEASE_VERSION``), network, the published sidecars, and the ``cosign``
    tool. Any absent prerequisite skips cleanly (classification:
    known_prerequisite / external_flake). A *present* bundle that fails
    verification is a hard failure (classification: release_blocker), never a skip.
    """
    version = require_release_version()
    tag = release_tag(version)
    data = fetch_release_metadata(tag)

    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    checksums_name = manifest.checksums_asset_name()
    signature_name = manifest.signature_asset_name()
    if checksums_name not in assets:
        pytest.skip(
            f"[{COMPONENT}] no {checksums_name} in {tag!r} — checksum file not "
            "published (classification: known_prerequisite, AASM_RELEASE_VERSION)"
        )
    if signature_name not in assets:
        pytest.skip(
            f"[{COMPONENT}] no {signature_name} in {tag!r} — cosign signature bundle "
            "not published (classification: known_prerequisite, AASM_RELEASE_VERSION)"
        )

    cosign = shutil.which("cosign")
    if cosign is None:
        pytest.skip(
            f"[{COMPONENT}] cosign not on PATH — signature-verification toolchain "
            "absent (classification: known_prerequisite)"
        )

    sums_path = tmp_path / checksums_name
    bundle_path = tmp_path / signature_name
    try:
        for name, dest in ((checksums_name, sums_path), (signature_name, bundle_path)):
            with urllib.request.urlopen(assets[name], timeout=30) as resp:  # noqa: S310
                dest.write_bytes(resp.read())
    except urllib.error.URLError as exc:
        pytest.skip(
            f"[{COMPONENT}] could not download {checksums_name}/{signature_name} "
            f"({exc}) — offline environment (classification: external_flake)"
        )

    result = subprocess.run(
        [
            cosign,
            "verify-blob",
            "--bundle",
            str(bundle_path),
            "--certificate-identity-regexp",
            _COSIGN_IDENTITY_RE,
            "--certificate-oidc-issuer",
            _COSIGN_OIDC_ISSUER,
            str(sums_path),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT}] cosign could not verify {signature_name!r} over "
        f"{checksums_name} (exit {result.returncode}) — classification: "
        f"release_blocker\nstderr: {result.stderr.strip()}"
    )
