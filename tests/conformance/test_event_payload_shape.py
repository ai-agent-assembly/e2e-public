"""Audit / governance event payload-shape conformance (AC3).

The public audit contract emits a governance event per agent action with a
stable required-field set, declared field types, and a closed decision enum.
This module checks the observable payload *shape* against
``tests/fixtures/conformance/event-payload-shapes.json``: valid samples must
satisfy the contract, and each invalid sample must be rejected for its declared
reason. It asserts the wire-shape contract only — not any product serializer.
"""

from __future__ import annotations

import json
import os

import pytest

COMPONENT = "event-payload-shape"

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "conformance", "event-payload-shapes.json"
)

_PY_TYPES = {"str": str, "int": int, "bool": bool}


def _load() -> dict:
    with open(_FIXTURE) as f:
        return json.load(f)


_DATA = _load()
_REQUIRED = _DATA["required_fields"]
_DECISIONS = frozenset(_DATA["decision_enum"])


def _shape_violation(payload: dict) -> str | None:
    """Return a stable violation code for a non-conformant payload, else None.

    Checks, in order: required-field presence, required-field type, and the
    decision enum. Extra fields are permitted (forward-compatible wire shape).
    """
    for field, type_name in _REQUIRED.items():
        if field not in payload:
            return f"missing-required-field:{field}"
        if not isinstance(payload[field], _PY_TYPES[type_name]):
            return f"wrong-type:{field}"
    if payload["decision"] not in _DECISIONS:
        return f"decision-not-in-enum:{payload['decision']}"
    return None


@pytest.mark.conformance
@pytest.mark.parametrize(
    "sample", _DATA["valid_samples"], ids=[s["id"] for s in _DATA["valid_samples"]]
)
def test_valid_event_payload_conforms(sample: dict) -> None:
    """Each valid sample satisfies the required-field / type / enum contract."""
    violation = _shape_violation(sample["payload"])
    assert violation is None, (
        f"[{COMPONENT}] valid sample {sample['id']!r} unexpectedly violated the "
        f"payload contract: {violation}"
    )


@pytest.mark.conformance
@pytest.mark.parametrize(
    "sample", _DATA["invalid_samples"], ids=[s["id"] for s in _DATA["invalid_samples"]]
)
def test_invalid_event_payload_rejected(sample: dict) -> None:
    """Each invalid sample is rejected with its declared stable reason."""
    violation = _shape_violation(sample["payload"])
    assert violation == sample["reason"], (
        f"[{COMPONENT}] invalid sample {sample['id']!r}: payload violated with "
        f"{violation!r}, expected {sample['reason']!r}"
    )


@pytest.mark.conformance
def test_decision_enum_covers_all_modes() -> None:
    """The decision enum covers the three enforcement outcomes (allow/deny/observe)."""
    assert _DECISIONS == {"allow", "deny", "observe"}, (
        f"[{COMPONENT}] decision enum drifted from the contract: {sorted(_DECISIONS)}"
    )
