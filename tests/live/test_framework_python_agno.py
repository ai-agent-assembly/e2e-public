"""Live framework smoke: a real **Agno** agent through the SDK + live core.

Part of AAASM-3525 / AAASM-3537 (real, non-mock framework smoke tests). The SDK's
Agno adapter monkey-patches ``agno.tools.function.FunctionCall.execute`` so a
governed tool consults ``check_tool_start`` before its body executes — the single
chokepoint an Agno ``Agent`` routes every function-tool call through. This test
applies the real ``AgnoPatch`` and drives a genuine Agno ``Function`` /
``FunctionCall`` (constructed offline, no LLM call) against a live ``aa-runtime``
— the production ``Agno → SDK adapter → aa-ffi → aa-runtime`` governance path.

Why drive ``FunctionCall.execute`` rather than ``Agent.run``: a full agent run
requires a real LLM to *decide* to call the tool, which cannot run offline. The
governance hook the SDK installs is on ``FunctionCall.execute`` — the exact call
an Agno agent makes to execute a tool — so building a real ``Function`` from a
callable and executing a real ``FunctionCall`` exercises the identical production
path with the framework objects fully real and only the model absent. This
mirrors the CrewAI / LangChain cells.

The **highlight governance functions** this exercises (per the AAASM-3525 plan):

* **Pre-execution allow enforcement** — the patched ``FunctionCall.execute`` asks
  the live runtime ``query_policy`` (via the production
  ``RuntimeQueryInterceptor``) whether the tool may run; an ``allow`` lets the
  real tool body execute (asserted by the tool's observable side effect + its
  real output, versus the adapter's failure short-circuit).
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport.

The **deny path** (a denied tool actually short-circuited end-to-end) is a
``strict=True`` xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) —
see :data:`tests.live.framework_live.DENY_XFAIL_REASON`. Note the Agno adapter
expresses a deny by *returning* a ``FunctionExecutionResult(status="failure",
error="[BLOCKED by governance policy] …")`` (so the agent can react) rather than
raising, so the deny assertion checks the tool body did not run and that failure
result was returned.
"""

from __future__ import annotations

import pytest

from tests.live.framework_live import (
    DENY_XFAIL_REASON,
    live_runtime_interceptor,
    require_framework,
    require_native_core,
)
from tests.live.runtime import LiveRuntime
from tests.live.runtime_client import import_native_core, make_audit_entry_payload

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: Agno's importable package name (the SDK adapter's ``get_framework_name``).
FRAMEWORK_IMPORT = "agno"
FRAMEWORK_PACKAGE = "agno"

#: The adapter's deny short-circuit marker (``_format_blocked_message``). Agno's
#: ``FunctionCall.execute`` patch *returns* a failure result carrying this string
#: on a deny rather than raising, so the deny assertions key off it.
BLOCKED_MARKER = "[BLOCKED by governance policy]"


def _build_governed_function():  # noqa: ANN202
    """Return a real Agno ``Function`` whose execution we can observe.

    The tool appends to a list it closes over, so a test can assert it actually
    *ran* (the allow decision let it through ``FunctionCall.execute``) versus was
    short-circuited by the adapter's deny branch. Returns the ``Function`` and the
    ``FunctionCall`` class so a test can construct a call with arguments.
    """
    from agno.tools.function import Function, FunctionCall

    calls: list[str] = []

    def search(query: str) -> str:
        """Search the web for a query."""
        calls.append(query)
        return f"results for {query}"

    function = Function.from_callable(search)
    return function, FunctionCall, calls


def test_agno_governance_path_is_wired() -> None:
    """Offline: the SDK's Agno adapter patches ``FunctionCall.execute`` and honours deny.

    The floor under the live path: the real ``AgnoPatch`` routes a tool execution
    through an interceptor's ``check_tool_start`` and short-circuits on a ``deny``
    (returning a failure result, not running the body). A stub enforce-posture
    interceptor proves the patch honours the decision contract with no live
    runtime, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.agno.patch import AgnoPatch

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    function, function_call_cls, calls = _build_governed_function()
    patch = AgnoPatch(_DenyInterceptor())
    assert patch.apply() is True, "Agno tool hook did not install"
    try:
        result = function_call_cls(function=function, arguments={"query": "weather"}).execute()
        assert calls == [], "deny path let the Agno tool body execute"
        assert result.status == "failure"
        assert BLOCKED_MARKER in str(result.error)
    finally:
        patch.revert()


def test_agno_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real Agno tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, applies
    the real ``AgnoPatch``, then executes a genuine Agno ``FunctionCall`` through
    the patched ``FunctionCall.execute`` — the real
    ``Agno → SDK adapter → aa-ffi → aa-runtime`` path. The live runtime answers
    ``query_policy`` with ``allow`` (the fixture runtime runs policy-disabled), so
    the tool executes: we assert its observable side effect (the tool ran) and its
    real output (not a failure result), proving enforcement let an allowed call
    through rather than the call merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.agno.patch import AgnoPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = AgnoPatch(interceptor)
    assert patch.apply() is True, "Agno tool hook did not install"
    function, function_call_cls, calls = _build_governed_function()
    try:
        result = function_call_cls(function=function, arguments={"query": "weather"}).execute()

        assert calls == ["weather"], "allowed Agno tool did not execute under live governance"
        assert result.status == "success"
        assert result.result == "results for weather"
    finally:
        patch.revert()


def test_agno_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
    """Allow path: the SDK ships a governance/audit event to the live runtime.

    Audit capture and event emission travel the same native ``send_event``
    transport the SDK uses to record what an agent did. Shipping a captured
    ``GovernanceEvent`` over the real UDS to the live runtime without rejection
    is the in-scope, provable-today half of the "audit capture" highlight
    function (full audit-store read-back is covered by the gateway-side tests).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    core = import_native_core()

    client = core.RuntimeClient.connect(str(live_runtime.socket_path))
    # A raise here would mean event emission is broken at the transport — which is
    # exactly what this guards. close() is intentionally not asserted (AAASM-3000).
    client.send_event(core.GovernanceEvent(make_audit_entry_payload(0)))


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), drop this strict xfail and assert the denied tool is short-circuited.
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)
def test_agno_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied Agno tool is short-circuited end-to-end (strict-xfail).

    The load-bearing enforcement assertion for Agno: with a policy that denies the
    tool, executing it through the real patched ``FunctionCall.execute`` against
    the live runtime must return the adapter's failure result carrying
    ``[BLOCKED by governance policy]`` *before* the tool body runs (Agno's adapter
    signals a deny by returning that result, not by raising). It cannot pass today
    — the fixture runtime runs policy-disabled and the SDK's full deny wiring is
    unshipped (AAASM-3021), so the runtime answers ``allow`` and the tool runs.
    Pinned ``strict=True`` so the day enforcement works it XPASSes and the strict
    marker fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.agno.patch import AgnoPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = AgnoPatch(interceptor)
    assert patch.apply() is True, "Agno tool hook did not install"
    function, function_call_cls, calls = _build_governed_function()
    try:
        result = function_call_cls(function=function, arguments={"query": "secret"}).execute()
        assert calls == [], "deny path let the tool body execute"
        assert result.status == "failure"
        assert BLOCKED_MARKER in str(result.error), "deny path did not short-circuit the tool"
    finally:
        patch.revert()
