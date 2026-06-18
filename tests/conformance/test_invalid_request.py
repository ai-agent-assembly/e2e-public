"""Invalid-request conformance (AC2): stable error on malformed check requests.

A conformant policy-check endpoint must reject a structurally-invalid request
with a deterministic error rather than attempting to evaluate it (an evaluation
of a malformed request can resolve fail-open). This module drives a reference
request validator over ``tests/fixtures/conformance/invalid-requests.json`` and
asserts each malformed request is rejected for its declared stable reason.
"""

from __future__ import annotations

import json
import os

import pytest

COMPONENT = "invalid-request"

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "conformance", "invalid-requests.json"
)


class RequestRejected(Exception):
    """Raised by the reference request validator with a stable ``code``."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _validate_request(request: object) -> None:
    """Validate a check request against the public request contract.

    Raises :class:`RequestRejected` with a stable code on the first violation;
    returns ``None`` for a well-formed request.
    """
    if not isinstance(request, dict):
        raise RequestRejected("request-not-a-mapping")
    if "action" not in request:
        raise RequestRejected("missing-action")
    if "resource" not in request:
        raise RequestRejected("missing-resource")
    if not isinstance(request["action"], str):
        raise RequestRejected("action-not-string")
    if not isinstance(request["resource"], str):
        raise RequestRejected("resource-not-string")
    if request["action"] == "":
        raise RequestRejected("empty-action")


def _load_cases() -> list[dict]:
    with open(_FIXTURE) as f:
        return json.load(f)["cases"]


_CASES = _load_cases()


@pytest.mark.conformance
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_invalid_request_rejected(case: dict) -> None:
    """Each malformed request is rejected with its declared stable reason."""
    with pytest.raises(RequestRejected) as exc_info:
        _validate_request(case["request"])
    assert exc_info.value.code == case["reason"], (
        f"[{COMPONENT}] case {case['id']!r} ({case['description']}): "
        f"rejected with reason {exc_info.value.code!r}, expected {case['reason']!r}"
    )


@pytest.mark.conformance
def test_well_formed_request_accepted() -> None:
    """A well-formed request passes the validator (accept/reject contract is two-sided)."""
    _validate_request({"action": "tool.read_file", "resource": "/etc/hosts"})
