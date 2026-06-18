"""Live SDK→runtime policy-enforcement E2E for the **Python** SDK (AAASM-3152).

This is the production-path E2E for the Python SDK: it proves the SDK and the
real core agree on a *policy decision*, not merely that the SDK package imports.
The allow path drives the genuine ``SDK → aa-ffi → aa-runtime`` UDS transport
(reusing the ``live_runtime`` fixture + the native ``_core`` extension, exactly
as ``test_sdk_runtime.py`` does). The deny path asserts a denied action is
*blocked* — which currently CANNOT pass and is therefore a ``strict=True`` xfail
linked to the two open product gaps below.

Layers, by how much they need:

* **offline** — the policy fixture loads + resolves allow/deny correctly. Runs
  with no toolchain, so it is green in a bare ``-m e2e`` run.
* **allow path (live)** — needs ``cargo``/``protoc`` (to build ``aa-runtime``)
  and the SDK's compiled ``_core``; skips cleanly (justified) otherwise.
* **deny path (live, strict-xfail)** — same prerequisites, but pinned xfail on
  the product gaps so it never yields a false green.

Known product gaps that make the deny path unprovable today (AC4):

* **AAASM-3000** — SDK⇄aa-runtime IPC deadlock: ``aa-sdk-client`` blocks on an
  Ack the runtime never sends, so ``close()`` hangs and no events are delivered.
* **AAASM-3021** — SDK pre-execution ``check()`` is unwired/stubbed: a denied
  action is not blocked at the SDK layer even with a reachable core.

AAASM-3172 will flip the deny-path xfail to a hard assert once a fixed SDK
release ships — see the marker on ``test_python_deny_path_blocks_restricted_tool``.
"""

from __future__ import annotations

import pytest

from tests.live.enforcement import (
    ALLOWED_ACTION,
    ENFORCEMENT_POLICY,
    RESTRICTED_ACTION,
    load_policy_rules,
    policy_denies,
)
from tests.live.runtime import LiveRuntime
from tests.live.runtime_client import (
    connect_runtime_client,
    import_native_core,
    make_audit_entry_payload,
    native_core_available,
)

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]


def _require_native_core() -> None:
    """Skip the calling test when the SDK's native ``_core`` ext is absent."""
    if not native_core_available():
        pytest.skip(
            "agent_assembly._core native extension is not built — install the SDK "
            "wheel (with the compiled _core) from ../python-sdk or PyPI to run this"
        )


def test_python_enforcement_policy_is_well_formed() -> None:
    """Offline: the shared policy denies the restricted action and allows others.

    The floor under the live paths: if the fixture did not actually encode a
    deny + a permit, the live allow/deny assertions would be meaningless. Runs
    with no toolchain so it is green in a bare ``-m e2e`` run.
    """
    assert ENFORCEMENT_POLICY.is_file()
    rules = load_policy_rules()
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert policy_denies(rules, ALLOWED_ACTION) is False


def test_python_allow_path_event_session(live_runtime: LiveRuntime) -> None:
    """Allow path: the Python SDK ships an allowed-action event to the live runtime.

    Opens a real native ``RuntimeClient`` over the runtime's UDS and ships a
    permitted-action ``GovernanceEvent`` — the genuine SDK→aa-ffi→aa-runtime
    path for an action the policy allows. The runtime accepts the connection and
    event without rejecting it; full clean-close is covered (and xfail-pinned to
    AAASM-3000) by ``test_sdk_runtime.py`` and is intentionally not re-asserted
    here so the allow path stays green when the transport is reachable.
    """
    _require_native_core()
    core = import_native_core()

    client = connect_runtime_client(live_runtime.socket_path)
    assert client.socket_path == str(live_runtime.socket_path)
    # Ship a permitted-action event; a raise here would mean the allow path is
    # broken at the transport, which is what this test guards.
    client.send_event(core.GovernanceEvent(make_audit_entry_payload(0)))


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), remove this strict xfail and turn the body into a hard assert that
# the restricted action is blocked at the SDK layer.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "SDK→runtime deny enforcement is unprovable today: AAASM-3000 "
        "(SDK⇄aa-runtime IPC deadlock — close() hangs, no events delivered) and "
        "AAASM-3021 (SDK pre-execution check() is unwired/stubbed, so a denied "
        "action is not blocked at the SDK layer). Flip to a hard assert via "
        "AAASM-3172 once a fixed SDK release ships."
    ),
)
def test_python_deny_path_blocks_restricted_tool(live_runtime: LiveRuntime) -> None:
    """Deny path: a restricted-action check is blocked by the SDK against a live core.

    This is the load-bearing enforcement assertion — a denied action MUST be
    refused at the SDK boundary. It currently fails (the SDK never calls a
    working ``check()``; AAASM-3021) so it is a ``strict=True`` xfail; the day
    the SDK enforces, it XPASSes and the strict marker fails the suite — the cue
    to flip it (AAASM-3172).
    """
    _require_native_core()
    core = import_native_core()

    client = connect_runtime_client(live_runtime.socket_path)
    # A working SDK would consult the core and refuse the restricted action
    # before it runs. The SDK exposes no enforcing pre-check today (AAASM-3021),
    # so we assert the *intended* contract and let strict-xfail record the gap.
    decision = getattr(client, "check_action", None)
    assert decision is not None, (
        f"SDK exposes no enforcing pre-check for {RESTRICTED_ACTION!r} "
        "(AAASM-3021): check() is unwired"
    )
    assert decision(RESTRICTED_ACTION).denied is True
    # Reference the unused symbol so the imported core stays load-bearing.
    assert core is not None
