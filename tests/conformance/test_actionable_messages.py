"""Actionable-message conformance (AC5).

A conformance failure is only useful if its message tells an operator what
broke and how to act: it must name the component, the offending case, and the
expected-vs-actual values. These tests deliberately drive the sibling reference
checkers into failure and assert the produced messages carry those actionable
elements — so a real regression surfaces a debuggable message, not a bare
``assert False``.
"""

from __future__ import annotations

import pytest

from tests.conformance.test_event_payload_shape import _shape_violation
from tests.conformance.test_invalid_policy import PolicyRejected, _validate_policy
from tests.conformance.test_verdict_table import _resolve

COMPONENT = "actionable-messages"


@pytest.mark.conformance
def test_verdict_mismatch_message_names_component_and_values() -> None:
    """A failed verdict assertion message names the component, the verdict, and the expected."""
    policy = {
        "version": "1",
        "name": "allow-all",
        "rules": [{"id": "a", "effect": "allow", "priority": 0,
                   "match": {"action": "*", "resource": "*"}}],
    }
    request = {"action": "tool.read_file", "resource": "/x"}
    actual = _resolve(policy, request)
    expected = "deny"  # deliberately wrong to capture the failure message

    with pytest.raises(AssertionError) as exc_info:
        assert actual == expected, (
            f"[verdict-table] policy {policy['name']!r} on request {request!r} "
            f"resolved to {actual!r}, expected {expected!r}"
        )

    message = str(exc_info.value)
    for needle in ("verdict-table", "allow-all", actual, expected):
        assert needle in message, (
            f"[{COMPONENT}] verdict failure message must contain {needle!r}; got: {message!r}"
        )


@pytest.mark.conformance
def test_policy_rejection_carries_stable_actionable_code() -> None:
    """An invalid-policy rejection carries a stable, named violation code."""
    with pytest.raises(PolicyRejected) as exc_info:
        _validate_policy({"name": "no-version", "rules": []})
    assert exc_info.value.code == "missing-version", (
        f"[{COMPONENT}] expected a stable 'missing-version' code, got "
        f"{exc_info.value.code!r}"
    )
    # The code is non-empty and human-readable (kebab-cased), not an opaque number.
    assert exc_info.value.code and "-" in exc_info.value.code, (
        f"[{COMPONENT}] rejection code {exc_info.value.code!r} is not actionable"
    )


@pytest.mark.conformance
def test_payload_violation_message_names_field() -> None:
    """A payload-shape violation names the specific offending field, not just 'invalid'."""
    violation = _shape_violation(
        {"event_type": "tool_call", "agent_id": "a", "action": "x",
         "timestamp": "2026-06-18T00:00:00Z"}
    )
    assert violation == "missing-required-field:decision", (
        f"[{COMPONENT}] expected the violation to name the 'decision' field, got {violation!r}"
    )
    # The violation string is field-qualified so an operator can act on it.
    assert violation is not None and ":" in violation, (
        f"[{COMPONENT}] payload violation {violation!r} must be field-qualified"
    )
