"""Unit tests for aasm_verify.refs.resolve_refs."""

from __future__ import annotations

import pytest

from aasm_verify.refs import resolve_refs


def test_latest_mode_no_refs() -> None:
    """latest mode with no refs resolves all repos to the default branch (main)."""
    refs = resolve_refs("latest")
    assert refs.mode == "latest"
    assert refs.agent_assembly == "main"
    assert refs.python_sdk == "main"


def test_latest_mode_tolerates_explicit_main_refs() -> None:
    """latest mode accepts refs explicitly set to 'main' (CI passes them as defaults)."""
    refs = resolve_refs(
        "latest",
        agent_assembly_ref="main",
        python_sdk_ref="main",
        node_sdk_ref="main",
        go_sdk_ref="main",
        examples_ref="main",
    )
    assert refs.mode == "latest"
    assert refs.agent_assembly == "main"


def test_latest_mode_rejects_non_default_ref() -> None:
    """latest mode still rejects a genuinely non-default ref."""
    with pytest.raises(ValueError, match="non-default per-repo refs"):
        resolve_refs("latest", agent_assembly_ref="feat/x")


def test_latest_mode_rejects_version() -> None:
    """latest mode rejects --version."""
    with pytest.raises(ValueError, match="latest"):
        resolve_refs("latest", version="0.0.1")
