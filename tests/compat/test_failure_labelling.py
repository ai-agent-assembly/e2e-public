"""Failure-message labelling (AAASM-3157, AC5).

A compatibility failure is only actionable if its message names the affected
runtime/SDK pair. These tests assert the label helper and the failure-message
format offline, so the contract holds even when no live build runs.
"""

from __future__ import annotations

import pytest

from tests.compat.matrix import CompatEntry, load_matrix

COMPONENT = "compat-matrix"


def compat_failure_message(entry: CompatEntry, detail: str) -> str:
    """Build the standard compatibility-failure message naming the pair (AC5).

    The message always leads with the runtime/SDK pair label so an operator can
    see *which* combination broke without reading the rest of the line.
    """
    return f"[{COMPONENT}] incompatible {entry.pair_label}: {detail}"


@pytest.mark.compat
def test_pair_label_names_runtime_and_sdk() -> None:
    """The pair label names both the runtime version and the SDK + its version."""
    entry = CompatEntry(
        id="x",
        runtime_channel="latest-branch",
        runtime_version="master",
        sdk="python",
        sdk_version="0.0.1",
        supported=True,
        reason="r",
    )
    label = entry.pair_label
    assert "master" in label, f"[{COMPONENT}] label must name the runtime version: {label!r}"
    assert "python" in label, f"[{COMPONENT}] label must name the sdk: {label!r}"
    assert "0.0.1" in label, f"[{COMPONENT}] label must name the sdk version: {label!r}"


@pytest.mark.compat
@pytest.mark.parametrize("entry", load_matrix(), ids=[e.id for e in load_matrix()])
def test_failure_message_points_at_pair(entry: CompatEntry) -> None:
    """A failure message for any matrix row names that row's runtime/SDK pair (AC5)."""
    message = compat_failure_message(entry, "handshake rejected")
    assert entry.runtime_version in message, (
        f"[{COMPONENT}] failure message must name the runtime version; got {message!r}"
    )
    assert entry.sdk in message and entry.sdk_version in message, (
        f"[{COMPONENT}] failure message must name the SDK + version; got {message!r}"
    )
    assert "handshake rejected" in message
