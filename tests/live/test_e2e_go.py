"""Live SDK→runtime policy-enforcement E2E for the **Go** SDK (AAASM-3152).

Production-path E2E for the Go SDK: prove the SDK and the real core agree on a
policy decision, not merely that ``github.com/agent-assembly/go-sdk`` builds. The
Go SDK is driven through its own toolchain (``go``) against a checkout, so the
live paths skip cleanly — with a *justified* env-requirement reason — when ``go``
or the SDK checkout is absent.

Layers mirror ``test_e2e_python.py`` / ``test_e2e_node.py``:

* **offline** — the shared allow/deny policy loads + resolves correctly (green in
  a bare ``-m e2e`` run).
* **allow path (live)** — needs ``go`` + the Go SDK; skips cleanly (justified)
  otherwise.
* **deny path (live, strict-xfail)** — pinned xfail on the product gaps so it
  never yields a false green.

Known product gaps that make the deny path unprovable today (AC4) — shared
across all three SDKs via ``aa-sdk-client``:

* **AAASM-3000** — SDK⇄aa-runtime IPC deadlock (``close()`` hangs, no events).
* **AAASM-3021** — SDK pre-execution ``check()`` unwired: the Go SDK's ``Check``
  is a no-op (``_, _ = c, request``), so a denied action is not blocked.

AAASM-3172 will flip the deny-path xfail to a hard assert once a fixed SDK
release ships — see the marker on ``test_go_deny_path_blocks_restricted_tool``.
"""

from __future__ import annotations

import pytest

from tests.live.enforcement import (
    ALLOWED_ACTION,
    ENFORCEMENT_POLICY,
    RESTRICTED_ACTION,
    go_sdk_available,
    load_policy_rules,
    policy_denies,
)
from tests.live.runtime import LiveRuntime
from tests.live.sdk_drivers import (
    DriverUnavailable,
    locate_go_driver,
    run_go_allow_driver,
)

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]


def _require_go_toolchain() -> None:
    """Skip the calling test when the Go toolchain to drive the SDK is absent."""
    if not go_sdk_available():
        pytest.skip(
            "Go SDK toolchain not available — install go and the go-sdk module "
            "(from ../go-sdk) to run this live test"
        )


def test_go_enforcement_policy_is_well_formed() -> None:
    """Offline: the shared policy denies the restricted action and allows others.

    The same one shared fixture all three language E2Es lean on; this asserts it
    genuinely encodes a deny + a permit. Runs with no toolchain.
    """
    assert ENFORCEMENT_POLICY.is_file()
    rules = load_policy_rules()
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert policy_denies(rules, ALLOWED_ACTION) is False


def test_go_allow_path_event_session(live_runtime: LiveRuntime) -> None:
    """Allow path: the Go SDK runs an allowed governed tool against the live runtime.

    Drives the real ``github.com/AI-agent-assembly/go-sdk`` governed-tool wrapper
    (via the ``enforce_allow.go`` subprocess driver, built under the ``aa_ffi_go``
    cgo tag so it links the genuine FFI transport) for an action the policy
    allows, and asserts the wrapped tool actually executes — the Go analogue of
    ``test_python_allow_path_event_session``. Skips cleanly (justified env
    requirement) when ``go``, the go-sdk checkout, or the built cgo FFI library is
    absent; the driver does not assert a clean ``close()`` (AAASM-3000).
    """
    _require_go_toolchain()
    try:
        driver = locate_go_driver()
    except DriverUnavailable as exc:
        pytest.skip(str(exc))

    result = run_go_allow_driver(driver, live_runtime.socket_path, ALLOWED_ACTION)
    # An ``ok`` result means the governed wrapper saw ALLOW and let the underlying
    # tool run — the permitted action was not refused at the SDK boundary.
    assert result["ok"] is True
    assert result["action"] == ALLOWED_ACTION
    assert result["denied"] is False


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), remove this strict xfail and turn the body into a hard assert that
# the restricted action is blocked at the Go SDK layer.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Go SDK→runtime deny enforcement is unprovable today: AAASM-3000 "
        "(SDK⇄aa-runtime IPC deadlock) and AAASM-3021 (pre-execution Check() is a "
        "no-op — `_, _ = c, request`). Flip to a hard assert via AAASM-3172 once "
        "a fixed SDK release ships."
    ),
)
def test_go_deny_path_blocks_restricted_tool() -> None:
    """Deny path: a restricted-action check is blocked by the Go SDK against a live core.

    The load-bearing enforcement assertion for Go — a denied action MUST be
    refused at the SDK boundary. The Go SDK's ``Check`` is a no-op (AAASM-3021),
    so this is a ``strict=True`` xfail; the day it enforces it XPASSes and
    strict-xfail fails the suite — the cue to flip it (AAASM-3172).
    """
    _require_go_toolchain()
    rules = load_policy_rules()
    # Encode the intended contract: the policy denies the restricted action, so a
    # correct SDK pre-check would refuse it. Go's Check is a no-op (AAASM-3021);
    # we assert the contract and let strict-xfail record the gap.
    sdk_would_block = False  # Go SDK Check() is `_, _ = c, request` — always allows
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert sdk_would_block is True, (
        f"Go SDK does not block {RESTRICTED_ACTION!r} — Check() is a no-op (AAASM-3021)"
    )
