"""Regression tests for the path-traversal guard (AAASM-3179 / S8707)."""

from __future__ import annotations

from pathlib import Path

import pytest

from aasm_verify.pathsafe import PathTraversalError, safe_path


def test_relative_path_within_base_is_allowed(tmp_path) -> None:
    resolved = safe_path("summary.json", base=tmp_path)
    assert resolved == (tmp_path / "summary.json").resolve()


def test_relative_subdir_path_within_base_is_allowed(tmp_path) -> None:
    resolved = safe_path("out/report.md", base=tmp_path)
    assert resolved == (tmp_path / "out" / "report.md").resolve()


def test_relative_traversal_escape_is_rejected(tmp_path) -> None:
    with pytest.raises(PathTraversalError):
        safe_path("../../etc/passwd", base=tmp_path)


def test_relative_deep_traversal_escape_is_rejected(tmp_path) -> None:
    with pytest.raises(PathTraversalError):
        safe_path("reports/../../../secret", base=tmp_path)


def test_absolute_path_is_allowed_and_resolved(tmp_path) -> None:
    # An absolute path is the operator's explicit choice (e.g. a CI artifact
    # dir); it is permitted but still normalized.
    target = tmp_path / "x" / ".." / "summary.json"
    resolved = safe_path(str(target), base=tmp_path)
    assert resolved == (tmp_path / "summary.json").resolve()
    assert ".." not in resolved.parts


def test_default_base_is_cwd(monkeypatch, tmp_path) -> None:
    monkeypatch.chdir(tmp_path)
    assert safe_path("summary.json") == (tmp_path / "summary.json").resolve()
    with pytest.raises(PathTraversalError):
        safe_path("../escape")


def test_error_names_the_offending_path(tmp_path) -> None:
    with pytest.raises(PathTraversalError, match="escape"):
        safe_path("../escape", base=tmp_path)


def test_returns_path_instance(tmp_path) -> None:
    assert isinstance(safe_path("a.json", base=tmp_path), Path)
