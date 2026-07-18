"""Live runtime x SDK combination validation (AAASM-3157, AC2).

Each *supported* matrix row maps to a parametrized live test that would build
the runtime at its version and exercise the language SDK at its version against
it. Actually running a combination needs ``cargo`` + ``protoc`` plus the per-SDK
toolchains, which CI/offline sandboxes lack, so every combination is
**skip-guarded** with a justified reason:

* the combination must be opted in via ``AASM_COMPAT_MATRIX`` (AC2 selection),
  and
* the required build toolchains (``cargo``, ``protoc``) must be on ``PATH``.

CI selection (AC2): no ``.github/workflows`` edit is needed — combinations are
selected by the ``compat`` marker plus the ``AASM_COMPAT_MATRIX`` env var:

    AASM_COMPAT_MATRIX=full uv run pytest tests/compat -m compat   # all supported pairs
    AASM_COMPAT_MATRIX=smoke uv run pytest tests/compat -m compat  # latest-* pairs only
    uv run pytest tests/compat -m compat                           # offline: live skipped

The data-level assertions (AC1/AC3/AC4/AC5) run unconditionally and offline;
only the live build/run below is gated.
"""

from __future__ import annotations

import os
import shutil

import pytest

from tests.compat.matrix import CompatEntry, load_matrix, supported_entries
from tests.compat.test_failure_labelling import compat_failure_message

COMPONENT = "compat-matrix"

# Toolchains required to build the runtime for a live combination.
_REQUIRED_BINARIES: tuple[str, ...] = ("cargo", "protoc")

# AASM_COMPAT_MATRIX selection profiles. 'smoke' restricts to the latest-* rows.
_SMOKE_CHANNELS: frozenset[str] = frozenset({"latest-branch", "latest-release"})

_SUPPORTED = supported_entries(load_matrix())


def _matrix_profile() -> str:
    """Return the selected matrix profile from AASM_COMPAT_MATRIX (default: off)."""
    return os.environ.get("AASM_COMPAT_MATRIX", "").strip().lower()


def _entry_selected(entry: CompatEntry, profile: str) -> bool:
    """Return whether *entry* is opted in by the active selection profile."""
    if profile == "full":
        return True
    if profile == "smoke":
        return entry.runtime_channel in _SMOKE_CHANNELS
    return False


@pytest.mark.compat
@pytest.mark.parametrize("entry", _SUPPORTED, ids=[e.id for e in _SUPPORTED])
def test_supported_combination_live(entry: CompatEntry) -> None:
    """Build the runtime + exercise the SDK for a supported pair (skip-guarded).

    Skips with a justified reason when the combination is not opted in via
    ``AASM_COMPAT_MATRIX`` or when the build toolchains are absent — so a green
    offline run never implies live cross-version coverage.
    """
    profile = _matrix_profile()
    if not _entry_selected(entry, profile):
        pytest.skip(
            f"combination {entry.pair_label} not opted in — "
            "set AASM_COMPAT_MATRIX=full|smoke to run live combinations"
        )

    missing = [b for b in _REQUIRED_BINARIES if shutil.which(b) is None]
    if missing:
        pytest.skip(
            f"build toolchain not found in PATH: {', '.join(missing)} — "
            f"install {', '.join(_REQUIRED_BINARIES)} to build {entry.pair_label}"
        )

    # Reaching here means an operator opted in AND the toolchains exist. The
    # actual cross-version build/run wiring lands with the live harness; until
    # then, surface a clear, pair-named failure rather than a false pass so the
    # gap is unmistakable and points at the affected pair (AC5).
    pytest.fail(
        compat_failure_message(
            entry,
            "live cross-version build/run is not yet wired in this harness; "
            "remove the opt-in or extend tests/live to drive this pair",
        )
    )
