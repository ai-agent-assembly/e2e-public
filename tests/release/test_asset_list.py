"""AC1: a release's published asset list is validated against the manifest.

The offline tests drive ``validate_asset_list`` against the checked-in sample and
against deliberately mutated lists, proving the logic actually *detects* a missing
platform binary and an unexpected extra binary (not merely that the happy path
passes). The live test applies the same logic to a real published release and is
skip-guarded on ``AASM_RELEASE_VERSION`` + network.
"""

from __future__ import annotations

import pytest

from tests.release import manifest
from tests.release.conftest import fetch_release_metadata, release_tag, require_release_version


@pytest.mark.release
def test_offline_sample_asset_list_is_complete(sample_asset_names: list[str]) -> None:
    """The offline sample publishes every expected platform binary, no extras."""
    result = manifest.validate_asset_list(sample_asset_names)
    assert result.ok, (
        f"sample release missing={result.missing_binaries} "
        f"unexpected={result.unexpected_binaries}"
    )
    assert result.missing_binaries == ()
    assert result.unexpected_binaries == ()


@pytest.mark.release
def test_validation_detects_missing_platform_binary(sample_asset_names: list[str]) -> None:
    """Dropping a platform binary is reported as missing (logic actually checks)."""
    dropped = manifest.expected_platform_assets()[0].asset_name
    mutated = [n for n in sample_asset_names if n != dropped]
    result = manifest.validate_asset_list(mutated)
    assert not result.ok
    assert dropped in result.missing_binaries
    assert result.unexpected_binaries == ()


@pytest.mark.release
def test_validation_detects_unexpected_binary(sample_asset_names: list[str]) -> None:
    """An unknown aasm-* binary is reported as unexpected (catches renamed targets)."""
    extra = "aasm-riscv64gc-unknown-linux-gnu.tar.gz"
    mutated = [*sample_asset_names, extra]
    result = manifest.validate_asset_list(mutated)
    assert not result.ok
    assert extra in result.unexpected_binaries
    assert result.missing_binaries == ()


@pytest.mark.release
def test_sidecar_flags_reflect_sample(sample_asset_names: list[str]) -> None:
    """The sample carries both the checksums file and the signature bundle."""
    result = manifest.validate_asset_list(sample_asset_names)
    assert result.has_checksums is True
    assert result.has_signature is True


@pytest.mark.release
def test_live_release_asset_list_matches_manifest() -> None:
    """A published release publishes exactly the manifest's platform binaries.

    Skip-guarded: needs AASM_RELEASE_VERSION + network. A *present* release that
    is missing an expected binary or carries an unexpected one is a hard failure.
    """
    version = require_release_version()
    tag = release_tag(version)
    data = fetch_release_metadata(tag)
    asset_names = [a["name"] for a in data.get("assets", [])]

    result = manifest.validate_asset_list(asset_names)
    assert result.ok, (
        f"[agent-assembly] release {tag!r} asset list violates manifest: "
        f"missing={result.missing_binaries} unexpected={result.unexpected_binaries} "
        "— classification: release_blocker"
    )
