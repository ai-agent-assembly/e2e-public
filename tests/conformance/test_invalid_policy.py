"""Invalid-policy conformance (AC2): fail-closed rejection with a stable reason.

A conformant policy loader must *reject* a structurally-invalid policy with a
deterministic, machine-checkable reason rather than silently accepting it
(a fail-open bug) or crashing. This module drives a reference structural
validator over ``tests/fixtures/conformance/invalid-policies.json`` and asserts
every malformed document is rejected for its declared violation code. It also
asserts the repo's known-good policy fixtures pass the same validator, so the
contract is two-sided (good policies accepted, bad policies rejected).
"""

from __future__ import annotations

import json
import os

import pytest

COMPONENT = "invalid-policy"

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "conformance", "invalid-policies.json"
)


class PolicyRejected(Exception):
    """Raised by the reference validator with a stable violation ``code``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


_VALID_EFFECTS = frozenset({"allow", "deny"})


def _validate_policy(policy: object) -> None:
    """Validate a policy against the public structural contract.

    Raises :class:`PolicyRejected` with a stable code on the first violation;
    returns ``None`` for a well-formed policy. The codes mirror the fixture's
    ``reason`` field so the conformance vectors stay machine-checkable.
    """
    if not isinstance(policy, dict):
        raise PolicyRejected("not-a-mapping")
    if "version" not in policy:
        raise PolicyRejected("missing-version")
    if "name" not in policy:
        raise PolicyRejected("missing-name")
    if "rules" not in policy:
        raise PolicyRejected("missing-rules")
    if not isinstance(policy["rules"], list):
        raise PolicyRejected("rules-not-a-list")
    for rule in policy["rules"]:
        if "effect" not in rule:
            raise PolicyRejected("rule-missing-effect")
        if rule["effect"] not in _VALID_EFFECTS:
            raise PolicyRejected("rule-invalid-effect")
        if "match" not in rule:
            raise PolicyRejected("rule-missing-match")
        if "action" not in rule["match"]:
            raise PolicyRejected("rule-match-missing-action")


def _load_cases() -> list[dict]:
    with open(_FIXTURE) as f:
        return json.load(f)["cases"]


_CASES = _load_cases()


@pytest.mark.conformance
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_invalid_policy_rejected(case: dict) -> None:
    """Each malformed policy is rejected with its declared stable reason."""
    with pytest.raises(PolicyRejected) as exc_info:
        _validate_policy(case["policy"])
    assert exc_info.value.code == case["reason"], (
        f"[{COMPONENT}] case {case['id']!r} ({case['description']}): "
        f"rejected with reason {exc_info.value.code!r}, expected {case['reason']!r}"
    )


@pytest.mark.conformance
def test_valid_repo_policy_fixtures_accepted() -> None:
    """The reference validator accepts every JSON-equivalent of the repo's good fixtures.

    These mirror the known-good YAML policies under ``fixtures/policies/`` so the
    accept/reject contract is two-sided — a validator that rejected these would
    be fail-closed to the point of uselessness.
    """
    good_policies = [
        {"version": "1", "name": "allow-all-test",
         "rules": [{"id": "allow-all", "effect": "allow", "priority": 0,
                    "match": {"action": "*", "resource": "*"}}]},
        {"version": "1", "name": "deny-network-test",
         "rules": [{"id": "deny-network", "effect": "deny", "priority": 10,
                    "match": {"action": "network.*", "resource": "*"}},
                   {"id": "allow-rest", "effect": "allow", "priority": 0,
                    "match": {"action": "*", "resource": "*"}}]},
    ]
    for policy in good_policies:
        # Must not raise.
        _validate_policy(policy)
