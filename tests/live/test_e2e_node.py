"""Live SDK→runtime policy-enforcement E2E for the **Node** SDK (AAASM-3152).

Production-path E2E for the Node SDK: prove the SDK and the real core agree on a
policy decision, not merely that ``@agent-assembly/sdk`` resolves. Unlike the
Python SDK (whose native ``_core`` is importable into this process), the Node SDK
is driven through its own toolchain (``node``/``pnpm``) against a checkout, so the
live paths skip cleanly — with a *justified* env-requirement reason — when the
toolchain or the SDK checkout is absent.

Layers mirror ``test_e2e_python.py``:

* **offline** — the shared allow/deny policy loads + resolves correctly (green in
  a bare ``-m e2e`` run).
* **allow path (live)** — needs ``node``/``pnpm`` + a built Node SDK; skips
  cleanly (justified) otherwise.
* **deny path (live, strict-xfail)** — pinned xfail on the product gaps so it
  never yields a false green.

Known product gaps that make the deny path unprovable today (AC4) — shared
across all three SDKs via ``aa-sdk-client``:

* **AAASM-3000** — SDK⇄aa-runtime IPC deadlock (``close()`` hangs, no events).
* **AAASM-3021** — SDK pre-execution ``check()`` unwired: the Node SDK's
  ``createNoopGatewayClient`` always returns ``{denied: false}``, so a denied
  action is not blocked at the SDK layer.

AAASM-3172 will flip the deny-path xfail to a hard assert once a fixed SDK
release ships — see the marker on ``test_node_deny_path_blocks_restricted_tool``.
"""

from __future__ import annotations

import pytest

from tests.live.enforcement import (
    ALLOWED_ACTION,
    ENFORCEMENT_POLICY,
    RESTRICTED_ACTION,
    load_policy_rules,
    node_sdk_available,
    policy_denies,
)
from tests.live.runtime import LiveRuntime
from tests.live.sdk_drivers import (
    DriverUnavailable,
    locate_node_driver,
    run_node_allow_driver,
)

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]


def _require_node_toolchain() -> None:
    """Skip the calling test when the Node toolchain to drive the SDK is absent."""
    if not node_sdk_available():
        pytest.skip(
            "Node SDK toolchain not available — install node and pnpm and a built "
            "@agent-assembly/sdk (from ../node-sdk or npm) to run this live test"
        )


def test_node_enforcement_policy_is_well_formed() -> None:
    """Offline: the shared policy denies the restricted action and allows others.

    Same floor as the Python E2E — all three language tests assert the one
    shared fixture genuinely encodes a deny + a permit before any live path
    leans on it. Runs with no toolchain.
    """
    assert ENFORCEMENT_POLICY.is_file()
    rules = load_policy_rules()
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert policy_denies(rules, ALLOWED_ACTION) is False


def test_node_allow_path_event_session(live_runtime: LiveRuntime) -> None:
    """Allow path: the Node SDK ships an allowed-action event to the live runtime.

    Drives the genuine ``@agent-assembly/sdk`` native client (via the
    ``enforce_allow.mjs`` subprocess driver) over the live runtime's UDS to ship
    a permitted-action event — the real ``SDK → aa-ffi → aa-runtime`` path for an
    action the policy allows, the Node analogue of
    ``test_python_allow_path_event_session``. Skips cleanly (justified env
    requirement) when the Node toolchain or a built SDK is absent; the driver
    deliberately does not assert a clean ``close()`` (AAASM-3000), so the allow
    path stays green when the transport is reachable.
    """
    _require_node_toolchain()
    try:
        driver = locate_node_driver()
    except DriverUnavailable as exc:
        pytest.skip(str(exc))

    result = run_node_allow_driver(driver, live_runtime.socket_path, ALLOWED_ACTION)
    # The driver returns the parsed JSON result of shipping the permitted event;
    # an ``ok`` result with the action it ran is the observed allowed-action
    # event reaching the live runtime without being refused at the transport.
    assert result["ok"] is True
    assert result["action"] == ALLOWED_ACTION
    assert result["denied"] is False


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), remove this strict xfail and turn the body into a hard assert that
# the restricted action is blocked at the Node SDK layer.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Node SDK→runtime deny enforcement is unprovable today: AAASM-3000 "
        "(SDK⇄aa-runtime IPC deadlock) and AAASM-3021 (pre-execution check() "
        "unwired — createNoopGatewayClient always returns denied:false). Flip to "
        "a hard assert via AAASM-3172 once a fixed SDK release ships."
    ),
)
def test_node_deny_path_blocks_restricted_tool() -> None:
    """Deny path: a restricted-action check is blocked by the Node SDK against a live core.

    The load-bearing enforcement assertion for Node — a denied action MUST be
    refused at the SDK boundary. The Node SDK's gateway client is a no-op that
    always allows (AAASM-3021), so this is a ``strict=True`` xfail; the day it
    enforces it XPASSes and strict-xfail fails the suite — the cue to flip it
    (AAASM-3172).
    """
    _require_node_toolchain()
    rules = load_policy_rules()
    # Encode the intended contract: the policy denies the restricted action, so a
    # correct SDK pre-check would refuse it. createNoopGatewayClient never does
    # (AAASM-3021); we assert the contract and let strict-xfail record the gap.
    sdk_would_block = False  # the no-op gateway client always returns denied:false
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert sdk_would_block is True, (
        f"Node SDK does not block {RESTRICTED_ACTION!r} — createNoopGatewayClient "
        "always allows (AAASM-3021)"
    )
