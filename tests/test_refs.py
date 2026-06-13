"""Unit tests for aasm_verify.refs.resolve_refs."""

from __future__ import annotations

import pytest

from aasm_verify.refs import resolve_refs


def test_latest_mode_no_refs() -> None:
    """latest mode with no refs resolves all repos to master."""
    refs = resolve_refs("latest")
    assert refs.mode == "latest"
    assert refs.agent_assembly == "master"
    assert refs.python_sdk == "master"


def test_latest_mode_tolerates_explicit_master_refs() -> None:
    """latest mode accepts refs explicitly set to 'master' (CI passes them as defaults)."""
    refs = resolve_refs(
        "latest",
        agent_assembly_ref="master",
        python_sdk_ref="master",
        node_sdk_ref="master",
        go_sdk_ref="master",
        examples_ref="master",
    )
    assert refs.mode == "latest"
    assert refs.agent_assembly == "master"


def test_latest_mode_rejects_non_master_ref() -> None:
    """latest mode still rejects a genuinely non-master ref."""
    with pytest.raises(ValueError, match="non-master per-repo refs"):
        resolve_refs("latest", agent_assembly_ref="feat/x")


def test_latest_mode_rejects_version() -> None:
    """latest mode rejects --version."""
    with pytest.raises(ValueError, match="latest"):
        resolve_refs("latest", version="0.0.1")
