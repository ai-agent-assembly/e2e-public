"""Test-local compatibility-matrix summary writer (AAASM-3157, AC3).

The compatibility report must clearly identify the *tested* runtime x SDK
versions AND the combinations that are explicitly *unsupported* (with a reason).
The shared report generator in :mod:`aasm_verify.reports` is owned by another
in-flight change (PR #75 / AAASM-3179) and is read-only here, so this harness
emits its own summary artifact under the test's ``tmp_path`` rather than editing
the shared reporter.

Two renderings are produced from the same data so a human and a machine can both
consume it:

* a Markdown table (``compatibility-matrix.md``) — operator-readable, and
* a JSON document (``compatibility-matrix.json``) — machine-readable, with a
  ``supported`` / ``unsupported`` split and the per-row reasons.
"""

from __future__ import annotations

import json
from pathlib import Path

from tests.compat.matrix import CompatEntry


def _row_dict(entry: CompatEntry) -> dict:
    return {
        "id": entry.id,
        "runtime_channel": entry.runtime_channel,
        "runtime_version": entry.runtime_version,
        "sdk": entry.sdk,
        "sdk_version": entry.sdk_version,
        "supported": entry.supported,
        "reason": entry.reason,
    }


def build_summary(entries: list[CompatEntry]) -> dict:
    """Return the machine-readable summary mapping for *entries*.

    The mapping names every tested version pair and splits supported from
    unsupported combinations, each carrying its reason (AC3).
    """
    supported = [_row_dict(e) for e in entries if e.supported]
    unsupported = [_row_dict(e) for e in entries if not e.supported]
    return {
        "ticket": "AAASM-3157",
        "total": len(entries),
        "supported_count": len(supported),
        "unsupported_count": len(unsupported),
        "supported": supported,
        "unsupported": unsupported,
    }


def render_markdown(entries: list[CompatEntry]) -> str:
    """Render the matrix as a Markdown table naming tested + unsupported pairs."""
    lines = [
        "# Cross-version compatibility matrix (AAASM-3157)",
        "",
        "| Runtime channel | Runtime version | SDK | SDK version | Supported | Reason |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for e in entries:
        mark = "yes" if e.supported else "NO (unsupported)"
        lines.append(
            f"| {e.runtime_channel} | {e.runtime_version} | {e.sdk} | "
            f"{e.sdk_version} | {mark} | {e.reason} |"
        )
    return "\n".join(lines) + "\n"


def write_summary(entries: list[CompatEntry], out_dir: Path) -> dict[str, Path]:
    """Write the Markdown + JSON summary artifacts into *out_dir*.

    Intended to be called with a test ``tmp_path``. Returns the written paths
    keyed by ``"markdown"`` / ``"json"``.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / "compatibility-matrix.md"
    json_path = out_dir / "compatibility-matrix.json"
    md_path.write_text(render_markdown(entries), encoding="utf-8")
    json_path.write_text(
        json.dumps(build_summary(entries), indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    return {"markdown": md_path, "json": json_path}
