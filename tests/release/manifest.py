"""Expected-platform-assets manifest for release artifact integrity verification.

AAASM-3161 asks a single question that no product repo can answer alone: *does a
published GitHub Release carry exactly the platform binaries (and the integrity
sidecars) we promise downstream installers?* This module is the **data layer**
for that question (AC1): a declarative description of the platform → asset-name
mapping a well-formed release must contain, plus the pure validation logic that
diffs a real release's asset list against it.

The manifest is intentionally code-as-data rather than a JSON file: the asset
names are Rust target triples that must stay in lock-step with
``conftest.platform_asset_suffix`` (the production resolver), and expressing the
contract in one typed place lets a schema test catch drift instead of a silent
mismatch at release time. The offline ``tests/fixtures/release/`` sample exercises
the *validation logic* without a network round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass

# The binary-asset suffixes the release pipeline publishes, one per supported
# platform. These mirror the Rust target triples in ``platform_asset_suffix``;
# the schema test asserts the two never drift apart.
_PLATFORM_SUFFIXES: tuple[str, ...] = (
    "aarch64-apple-darwin.tar.gz",
    "x86_64-apple-darwin.tar.gz",
    "aarch64-unknown-linux-gnu.tar.gz",
    "x86_64-unknown-linux-gnu.tar.gz",
)

# The binary asset name template. The CLI binary is ``aasm``; assets are named
# ``aasm-<triple>.tar.gz`` (see the real release + ``tests/test_release_assets``).
_BINARY_PREFIX = "aasm-"

# Integrity sidecars expected alongside the binaries. ``SHA256SUMS`` is the
# checksum manifest (validated by AC4); ``SHA256SUMS.cosign.bundle`` is the
# cosign signature over it whose *verification* is the documented AC4 gap.
_CHECKSUMS_ASSET = "SHA256SUMS"
_SIGNATURE_ASSET = "SHA256SUMS.cosign.bundle"


@dataclass(frozen=True)
class PlatformAsset:
    """One platform's expected binary asset within a release.

    ``platform`` is the human-readable platform label (e.g.
    ``"macos-arm64"``); ``asset_name`` is the exact file name the release must
    publish for it (e.g. ``"aasm-aarch64-apple-darwin.tar.gz"``).
    """

    platform: str
    asset_name: str
    triple_suffix: str


def _platform_label(suffix: str) -> str:
    """Map a Rust target-triple suffix to a stable human-readable platform label."""
    os_label = "macos" if "apple-darwin" in suffix else "linux"
    arch_label = "arm64" if suffix.startswith("aarch64") else "x86_64"
    return f"{os_label}-{arch_label}"


def expected_platform_assets() -> tuple[PlatformAsset, ...]:
    """Return the expected per-platform binary assets a release must publish."""
    return tuple(
        PlatformAsset(
            platform=_platform_label(suffix),
            asset_name=f"{_BINARY_PREFIX}{suffix}",
            triple_suffix=suffix,
        )
        for suffix in _PLATFORM_SUFFIXES
    )


def expected_binary_asset_names() -> frozenset[str]:
    """Return the set of binary asset names a well-formed release must contain."""
    return frozenset(a.asset_name for a in expected_platform_assets())


def checksums_asset_name() -> str:
    """Return the expected checksums (SHA256SUMS) asset name."""
    return _CHECKSUMS_ASSET


def signature_asset_name() -> str:
    """Return the expected cosign signature-bundle asset name."""
    return _SIGNATURE_ASSET


def covered_platforms() -> tuple[str, ...]:
    """Return the platform labels the manifest declares coverage for."""
    return tuple(a.platform for a in expected_platform_assets())


@dataclass(frozen=True)
class AssetListValidation:
    """Outcome of diffing a real release's asset list against the manifest.

    ``missing_binaries`` are expected platform binaries absent from the release;
    ``unexpected_binaries`` are ``aasm-*`` binaries the release published that the
    manifest does not declare (i.e. a new/renamed target the contract has not
    caught up with). ``has_checksums``/``has_signature`` record sidecar presence
    so AC4 can report the signature-verification gap explicitly.
    """

    missing_binaries: tuple[str, ...]
    unexpected_binaries: tuple[str, ...]
    has_checksums: bool
    has_signature: bool

    @property
    def ok(self) -> bool:
        """True when no expected binary is missing and no extra binary appeared."""
        return not self.missing_binaries and not self.unexpected_binaries


def validate_asset_list(asset_names: list[str]) -> AssetListValidation:
    """Diff a release's published asset names against the expected manifest.

    Pure and offline: callers pass the asset-name list (from the GitHub API or
    the offline fixture) and receive the missing/unexpected binary sets plus
    sidecar-presence flags. Only ``aasm-*`` entries count as binaries, so the
    checksum/signature sidecars never register as "unexpected".
    """
    present = set(asset_names)
    expected = expected_binary_asset_names()

    missing = tuple(sorted(expected - present))
    published_binaries = {n for n in present if n.startswith(_BINARY_PREFIX)}
    unexpected = tuple(sorted(published_binaries - expected))

    return AssetListValidation(
        missing_binaries=missing,
        unexpected_binaries=unexpected,
        has_checksums=_CHECKSUMS_ASSET in present,
        has_signature=_SIGNATURE_ASSET in present,
    )
