"""Verdict-resolution conformance: parametrized allow/deny decision table.

This goes beyond the basic "one allow + one deny exists" smoke test by
asserting the *observable resolution contract* of the Agent Assembly policy
model across priority ordering, glob matching, resource scoping, fail-closed
default-deny, and tie-breaking. The reference resolver below encodes only the
public contract documented in ``tests/fixtures/conformance/verdict-cases.json``
— it is a contract oracle for the integration suite, not a copy of any
product-internal policy engine.
"""

from __future__ import annotations

import json
import os

import pytest

COMPONENT = "verdict-table"

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "conformance", "verdict-cases.json"
)


def _glob_match(pattern: str, value: str) -> bool:
    """Match a policy glob against a request token.

    Contract: ``*`` matches any value; a ``prefix.*`` / ``prefix/*`` glob matches
    any value sharing that prefix; otherwise the match is literal equality.
    """
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return value.startswith(pattern[:-1])
    return pattern == value


def _resolve(policy: dict, request: dict) -> str:
    """Resolve a request against a policy per the public conformance contract.

    Rules are sorted highest-priority-first (stable for equal priorities); the
    first rule whose action and resource globs both match decides. No match
    means fail-closed deny.
    """
    rules = sorted(
        enumerate(policy.get("rules", [])),
        key=lambda pair: (-int(pair[1].get("priority", 0)), pair[0]),
    )
    for _, rule in rules:
        match = rule.get("match", {})
        if _glob_match(match.get("action", ""), request["action"]) and _glob_match(
            match.get("resource", ""), request["resource"]
        ):
            return rule["effect"]
    return "deny"


def _load_cases() -> list[dict]:
    with open(_FIXTURE) as f:
        return json.load(f)["cases"]


_CASES = _load_cases()


@pytest.mark.conformance
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_verdict_resolution(case: dict) -> None:
    """Each fixture request resolves to its expected allow/deny verdict."""
    actual = _resolve(case["policy"], case["request"])
    assert actual == case["expected"], (
        f"[{COMPONENT}] case {case['id']!r} ({case['description']}): "
        f"policy {case['policy']['name']!r} on request {case['request']!r} "
        f"resolved to {actual!r}, expected {case['expected']!r}"
    )


@pytest.mark.conformance
def test_verdict_table_covers_both_effects() -> None:
    """The decision table exercises both allow and deny outcomes (not a one-sided smoke)."""
    outcomes = {c["expected"] for c in _CASES}
    assert {"allow", "deny"} <= outcomes, (
        f"[{COMPONENT}] verdict table must cover both allow and deny; got {sorted(outcomes)}"
    )
    assert len(_CASES) >= 5, (
        f"[{COMPONENT}] expected a deepened table (>=5 cases), got {len(_CASES)}"
    )
