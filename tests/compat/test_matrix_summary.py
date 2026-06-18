"""Matrix-summary artifact emission (AAASM-3157, AC3).

The report must clearly identify the tested versions and the unsupported
combinations. This writes a test-local summary (Markdown + JSON) under
``tmp_path`` — the shared ``aasm_verify.reports`` generator is read-only here
(PR #75 / AAASM-3179) — and asserts the artifact names both halves.
"""

from __future__ import annotations

import json

import pytest

from tests.compat.matrix import load_matrix, unsupported_entries
from tests.compat.summary import build_summary, render_markdown, write_summary

COMPONENT = "compat-matrix"

_ENTRIES = load_matrix()


@pytest.mark.compat
def test_summary_splits_supported_and_unsupported() -> None:
    """The machine-readable summary splits supported from unsupported, with counts (AC3)."""
    summary = build_summary(_ENTRIES)
    assert summary["total"] == len(_ENTRIES)
    assert summary["supported_count"] + summary["unsupported_count"] == summary["total"]
    assert summary["unsupported_count"] >= 1, (
        f"[{COMPONENT}] summary must surface >=1 unsupported combination (AC3)"
    )
    for row in summary["unsupported"]:
        assert row["reason"].strip(), (
            f"[{COMPONENT}] unsupported row {row['id']!r} in summary has no reason"
        )


@pytest.mark.compat
def test_markdown_summary_lists_every_pair() -> None:
    """The Markdown table names every tested runtime/SDK version pair (AC3)."""
    md = render_markdown(_ENTRIES)
    for entry in _ENTRIES:
        assert entry.runtime_version in md
        assert entry.sdk_version in md
    # Unsupported rows are visibly flagged, not silently mixed in.
    if unsupported_entries(_ENTRIES):
        assert "unsupported" in md.lower()


@pytest.mark.compat
def test_summary_written_under_tmp_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """write_summary emits both artifacts under tmp_path and they round-trip (AC3)."""
    paths = write_summary(_ENTRIES, tmp_path / "compat-report")
    assert paths["markdown"].exists()
    assert paths["json"].exists()

    loaded = json.loads(paths["json"].read_text(encoding="utf-8"))
    assert loaded["ticket"] == "AAASM-3157"
    assert loaded["total"] == len(_ENTRIES)

    md_text = paths["markdown"].read_text(encoding="utf-8")
    assert "compatibility matrix" in md_text.lower()
