"""Cross-version runtime x SDK compatibility matrix loader and schema (AAASM-3157).

This module is the data half of the compatibility-matrix harness. It loads the
declarative matrix from ``tests/fixtures/compat/compatibility-matrix.json`` and
exposes it as validated :class:`CompatEntry` rows so the parametrized tests in
``tests/compat/`` can:

* assert the matrix parses and every row is schema-valid (AC1),
* enumerate the tested runtime x SDK versions and the explicitly *unsupported*
  combinations, each with a reason (AC3),
* assert at least one previous-release combination is present and validated
  (AC4), and
* render a failure label that names the offending runtime/SDK pair (AC5).

Everything here is stdlib-only and runs fully offline: it never builds or runs
a runtime/SDK combination — that live work is opt-in and skip-guarded.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

# Recognised runtime channels. ``previous-release`` is the prior supported
# release kept under compatibility validation (AC4).
RUNTIME_CHANNELS: tuple[str, ...] = (
    "latest-branch",
    "latest-release",
    "previous-release",
)

# SDK languages tracked by the matrix — one column per public SDK repo.
SDK_LANGUAGES: tuple[str, ...] = ("python", "node", "go")

_MATRIX_PATH = os.path.join(
    os.path.dirname(__file__),
    "..",
    "fixtures",
    "compat",
    "compatibility-matrix.json",
)


class MatrixError(ValueError):
    """A compatibility-matrix row or document failed schema validation."""


@dataclass(frozen=True)
class CompatEntry:
    """One runtime-version x SDK-version compatibility cell.

    A cell records whether the pair is a supported integration target and why.
    Unsupported cells must explain why the combination is not validated.
    """

    id: str
    runtime_channel: str
    runtime_version: str
    sdk: str
    sdk_version: str
    supported: bool
    reason: str

    @property
    def pair_label(self) -> str:
        """Return a stable ``runtime@<v> x <sdk>-sdk@<v>`` label for messages (AC5)."""
        return (
            f"runtime@{self.runtime_version} x {self.sdk}-sdk@{self.sdk_version}"
        )


def _validate_entry(raw: dict, index: int) -> CompatEntry:
    """Validate a single raw matrix row and return a typed :class:`CompatEntry`.

    Raises :class:`MatrixError` naming the offending row on any schema problem.
    """
    where = raw.get("id") or f"entry[{index}]"
    required = (
        "id",
        "runtime_channel",
        "runtime_version",
        "sdk",
        "sdk_version",
        "supported",
        "reason",
    )
    missing = [key for key in required if key not in raw]
    if missing:
        raise MatrixError(f"{where}: missing required field(s) {missing}")

    if raw["runtime_channel"] not in RUNTIME_CHANNELS:
        raise MatrixError(
            f"{where}: runtime_channel {raw['runtime_channel']!r} not in {RUNTIME_CHANNELS}"
        )
    if raw["sdk"] not in SDK_LANGUAGES:
        raise MatrixError(f"{where}: sdk {raw['sdk']!r} not in {SDK_LANGUAGES}")
    if not isinstance(raw["supported"], bool):
        got = type(raw["supported"]).__name__
        raise MatrixError(f"{where}: 'supported' must be a bool, got {got}")
    reason = raw["reason"]
    if not isinstance(reason, str) or not reason.strip():
        raise MatrixError(f"{where}: 'reason' must be a non-empty string")
    for ver_field in ("runtime_version", "sdk_version"):
        if not isinstance(raw[ver_field], str) or not raw[ver_field].strip():
            raise MatrixError(f"{where}: {ver_field!r} must be a non-empty string")

    return CompatEntry(
        id=str(raw["id"]),
        runtime_channel=str(raw["runtime_channel"]),
        runtime_version=str(raw["runtime_version"]),
        sdk=str(raw["sdk"]),
        sdk_version=str(raw["sdk_version"]),
        supported=bool(raw["supported"]),
        reason=str(reason),
    )


def load_matrix() -> list[CompatEntry]:
    """Load and validate every row of the compatibility matrix.

    Rows are returned in file order so test parametrization is deterministic.
    Raises :class:`MatrixError` if the document or any row is malformed, or
    if two rows share an ``id``.
    """
    with open(_MATRIX_PATH) as f:
        doc = json.load(f)
    raw_entries = doc.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        raise MatrixError("matrix document has no non-empty 'entries' list")

    entries = [_validate_entry(raw, i) for i, raw in enumerate(raw_entries)]

    seen: set[str] = set()
    for entry in entries:
        if entry.id in seen:
            raise MatrixError(f"duplicate entry id {entry.id!r}")
        seen.add(entry.id)
    return entries


def supported_entries(entries: list[CompatEntry]) -> list[CompatEntry]:
    """Return only the supported (validated) combinations."""
    return [e for e in entries if e.supported]


def unsupported_entries(entries: list[CompatEntry]) -> list[CompatEntry]:
    """Return only the explicitly-unsupported combinations (each with a reason)."""
    return [e for e in entries if not e.supported]
