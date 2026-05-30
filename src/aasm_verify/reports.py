"""Report generation for verification runs."""

from __future__ import annotations


def write_summary_json(path: str, results: dict) -> None:
    """Write machine-readable summary.json."""
    raise NotImplementedError


def write_report_md(path: str, results: dict) -> None:
    """Write human-readable report.md."""
    raise NotImplementedError
