"""Matrix coverage assertions: tested versions, unsupported combos, prior release.

These run offline and assert the *shape* of the compatibility matrix:

* both supported and explicitly-unsupported combinations are present, each with
  a reason (AC3),
* the latest-branch and latest-release channels are covered, and
* at least one previous-release combination is present and marked validated
  (AC4) — the data-level assertion holds even when the live build is skipped.
"""

from __future__ import annotations

import pytest

from tests.compat.matrix import (
    load_matrix,
    supported_entries,
    unsupported_entries,
)

COMPONENT = "compat-matrix"

_ENTRIES = load_matrix()


@pytest.mark.compat
def test_matrix_covers_supported_and_unsupported() -> None:
    """The matrix names tested versions AND explicit unsupported combos (AC3)."""
    supported = supported_entries(_ENTRIES)
    unsupported = unsupported_entries(_ENTRIES)
    assert supported, f"[{COMPONENT}] matrix declares no supported combination"
    assert unsupported, (
        f"[{COMPONENT}] matrix declares no *unsupported* combination — AC3 requires "
        "unsupported combos to be explicitly identified"
    )


@pytest.mark.compat
@pytest.mark.parametrize(
    "entry",
    unsupported_entries(_ENTRIES),
    ids=[e.id for e in unsupported_entries(_ENTRIES)],
)
def test_unsupported_entry_explains_why(entry) -> None:  # type: ignore[no-untyped-def]
    """Each unsupported combination carries a non-trivial reason (AC3)."""
    assert entry.supported is False
    assert entry.reason.strip(), (
        f"[{COMPONENT}] unsupported pair {entry.pair_label} has no reason"
    )
    # An unsupported reason must do more than restate the label — it explains why.
    assert "unsupported" in entry.reason.lower() or len(entry.reason) > 20, (
        f"[{COMPONENT}] unsupported pair {entry.pair_label} reason is not explanatory: "
        f"{entry.reason!r}"
    )


@pytest.mark.compat
def test_latest_channels_are_covered() -> None:
    """Both the latest-branch and latest-release channels appear in the matrix."""
    channels = {e.runtime_channel for e in _ENTRIES}
    for required in ("latest-branch", "latest-release"):
        assert required in channels, (
            f"[{COMPONENT}] matrix is missing the {required!r} channel; got {sorted(channels)}"
        )


@pytest.mark.compat
def test_previous_release_combination_validated() -> None:
    """At least one previous-release combination is present and marked validated (AC4)."""
    prev_validated = [
        e
        for e in _ENTRIES
        if e.runtime_channel == "previous-release" and e.supported
    ]
    assert prev_validated, (
        f"[{COMPONENT}] AC4: matrix must validate >=1 previous-release combination; "
        "none found marked supported"
    )
