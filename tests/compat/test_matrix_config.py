"""Matrix-config existence + schema validation (AAASM-3157, AC1).

These tests run fully offline. They prove the compatibility matrix exists,
parses, and that every declared row is schema-valid — the data foundation the
rest of the harness parametrizes over.
"""

from __future__ import annotations

import pytest

from tests.compat import matrix
from tests.compat.matrix import CompatEntry, MatrixError, load_matrix

COMPONENT = "compat-matrix"

_ENTRIES = load_matrix()


@pytest.mark.compat
def test_matrix_loads_non_empty() -> None:
    """The matrix config exists, parses, and declares at least one combination (AC1)."""
    assert _ENTRIES, f"[{COMPONENT}] compatibility matrix is empty"
    assert all(isinstance(e, CompatEntry) for e in _ENTRIES)


@pytest.mark.compat
@pytest.mark.parametrize("entry", _ENTRIES, ids=[e.id for e in _ENTRIES])
def test_entry_schema_valid(entry: CompatEntry) -> None:
    """Every matrix row carries a complete, well-typed schema (AC1)."""
    assert entry.runtime_channel in matrix.RUNTIME_CHANNELS, (
        f"[{COMPONENT}] entry {entry.id!r} has unknown runtime_channel "
        f"{entry.runtime_channel!r}"
    )
    assert entry.sdk in matrix.SDK_LANGUAGES, (
        f"[{COMPONENT}] entry {entry.id!r} has unknown sdk {entry.sdk!r}"
    )
    assert isinstance(entry.supported, bool)
    assert entry.runtime_version.strip(), (
        f"[{COMPONENT}] entry {entry.id!r} has empty runtime_version"
    )
    assert entry.sdk_version.strip(), (
        f"[{COMPONENT}] entry {entry.id!r} has empty sdk_version"
    )
    assert entry.reason.strip(), (
        f"[{COMPONENT}] entry {entry.id!r} has empty reason"
    )


@pytest.mark.compat
def test_entry_ids_unique() -> None:
    """Entry ids are unique so parametrization and reporting stay unambiguous."""
    ids = [e.id for e in _ENTRIES]
    assert len(ids) == len(set(ids)), (
        f"[{COMPONENT}] duplicate entry ids present: {sorted(ids)}"
    )


@pytest.mark.compat
def test_invalid_row_is_rejected_naming_offender() -> None:
    """A malformed row is rejected with a MatrixError naming the offending entry."""
    bad = {
        "id": "broken-row",
        "runtime_channel": "not-a-channel",
        "runtime_version": "master",
        "sdk": "python",
        "sdk_version": "master",
        "supported": True,
        "reason": "x",
    }
    with pytest.raises(MatrixError) as exc_info:
        matrix._validate_entry(bad, 0)
    message = str(exc_info.value)
    assert "broken-row" in message, (
        f"[{COMPONENT}] rejection must name the offending row; got {message!r}"
    )
    assert "not-a-channel" in message
