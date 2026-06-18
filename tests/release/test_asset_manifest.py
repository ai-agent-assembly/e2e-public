"""AC1 (data layer): the expected-platform-assets manifest exists and is schema-valid.

These tests run fully offline. They assert the manifest parses, has a well-formed
schema (non-empty, unique, correctly-named assets), and — critically — does not
drift from the production ``platform_asset_suffix`` resolver: every triple the
manifest declares must be one a real platform would request, and the current host
platform must map onto exactly one manifest entry.
"""

from __future__ import annotations

import pytest

from tests.public.conftest import platform_asset_suffix
from tests.release import manifest


@pytest.mark.release
def test_manifest_is_non_empty() -> None:
    """The manifest declares at least one expected platform asset."""
    assets = manifest.expected_platform_assets()
    assert assets, "expected-platform-assets manifest is empty"


@pytest.mark.release
def test_manifest_asset_names_are_unique() -> None:
    """No two platforms map to the same asset name."""
    names = [a.asset_name for a in manifest.expected_platform_assets()]
    assert len(names) == len(set(names)), f"duplicate asset names in manifest: {names}"


@pytest.mark.release
def test_manifest_platform_labels_are_unique() -> None:
    """Every declared platform label is distinct."""
    platforms = manifest.covered_platforms()
    assert len(platforms) == len(set(platforms)), (
        f"duplicate platform labels in manifest: {platforms}"
    )


@pytest.mark.release
@pytest.mark.parametrize("asset", manifest.expected_platform_assets(), ids=lambda a: a.platform)
def test_manifest_entry_schema(asset: manifest.PlatformAsset) -> None:
    """Each manifest entry is well-formed: aasm-* tarball whose name ends in its triple."""
    assert asset.platform, "platform label must be non-empty"
    assert asset.asset_name.startswith("aasm-"), (
        f"binary asset {asset.asset_name!r} must start with 'aasm-'"
    )
    assert asset.asset_name.endswith(".tar.gz"), (
        f"binary asset {asset.asset_name!r} must be a .tar.gz tarball"
    )
    assert asset.asset_name.endswith(asset.triple_suffix), (
        f"asset {asset.asset_name!r} must end with its triple suffix {asset.triple_suffix!r}"
    )


@pytest.mark.release
def test_manifest_declares_integrity_sidecars() -> None:
    """The manifest names the checksum and signature sidecar assets."""
    assert manifest.checksums_asset_name() == "SHA256SUMS"
    assert manifest.signature_asset_name().startswith("SHA256SUMS")


@pytest.mark.release
def test_current_platform_maps_to_exactly_one_manifest_asset() -> None:
    """The production platform_asset_suffix resolves to one manifest binary.

    This is the anti-drift guard: if the release pipeline or platform_asset_suffix
    changes a target triple, the manifest must be updated in the same change or
    this fails — preventing a silent missing-asset at release time.
    """
    suffix = platform_asset_suffix()
    matching = [a for a in manifest.expected_platform_assets() if a.asset_name.endswith(suffix)]
    assert len(matching) == 1, (
        f"platform suffix {suffix!r} matched {[a.asset_name for a in matching]} "
        "in the manifest — manifest has drifted from platform_asset_suffix"
    )
