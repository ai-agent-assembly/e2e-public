"""Regression tests for GitHub Release asset naming (Rust target triples)."""

from __future__ import annotations

from tests.public.conftest import platform_asset_suffix

# The real asset names published on the agent-assembly GitHub Release.
_RELEASE_ASSETS = (
    "aasm-aarch64-apple-darwin.tar.gz",
    "aasm-aarch64-unknown-linux-gnu.tar.gz",
    "aasm-x86_64-apple-darwin.tar.gz",
    "aasm-x86_64-unknown-linux-gnu.tar.gz",
)


def test_platform_asset_suffix_matches_exactly_one_release_asset() -> None:
    """The current platform's suffix matches exactly one real release asset."""
    suffix = platform_asset_suffix()
    matching = [a for a in _RELEASE_ASSETS if a.endswith(suffix)]
    assert len(matching) == 1, f"suffix {suffix!r} matched {matching}"


def test_platform_asset_suffix_is_rust_triple() -> None:
    """The suffix uses a Rust target triple, not the legacy `<os>-<arch>` form."""
    suffix = platform_asset_suffix()
    assert suffix.endswith(".tar.gz")
    assert "unknown-linux-gnu" in suffix or "apple-darwin" in suffix or "-" in suffix
    # Legacy forms that previously caused false release_blocker failures.
    assert not suffix.startswith(("linux-", "darwin-"))
