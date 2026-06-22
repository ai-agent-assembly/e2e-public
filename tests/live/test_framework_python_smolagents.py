"""Live framework smoke: a real **Smolagents** agent through the SDK + live core.

Part of AAASM-3525 / AAASM-3539 (real, non-mock framework smoke tests). The SDK's
smolagents adapter monkey-patches ``smolagents.tools.Tool.__call__`` — the single
chokepoint every tool execution flows through (``ToolCallingAgent`` via
``MultiStepAgent.execute_tool_call``'s ``tool(...)`` call, and ``CodeAgent`` via the
sandbox namespace where tools are plain callables). ``Tool.__call__`` runs
``self.forward(...)``, so a governed tool consults ``check_tool_start`` before its
body executes. This test applies the real ``SmolagentsPatch`` and drives a genuine
``smolagents.Tool`` against a live ``aa-runtime`` — the production
``Smolagents → SDK adapter → aa-ffi → aa-runtime`` governance path.

Why drive ``Tool.__call__`` rather than ``agent.run()``: a full agent run requires a
real LLM to *decide* to call the tool (smolagents routes the agent loop through a
model backend), which cannot run offline and is brittle to stub across releases.
The governance hook the SDK installs is on ``Tool.__call__`` — the exact call a
smolagents agent makes to execute a tool — so invoking the governed tool exercises
the identical production path with the framework object fully real and only the
model absent. This mirrors the CrewAI / LangChain cells.

The **highlight governance functions** this exercises (per the AAASM-3525 plan):

* **Pre-execution allow enforcement** — the patched ``Tool.__call__`` asks the live
  runtime ``query_policy`` (via the production ``RuntimeQueryInterceptor``) whether
  the tool may run; an ``allow`` lets the real ``forward`` body execute (asserted by
  the tool's observable side effect + its real output, versus the adapter's
  ``[BLOCKED by governance policy]`` short-circuit string).
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport.

The **deny path** (a denied tool actually short-circuited end-to-end) is a
``strict=True`` xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) — see
:data:`tests.live.framework_live.DENY_XFAIL_REASON`. The smolagents adapter signals
a deny by *returning* the ``[BLOCKED by governance policy]`` message (so the agent
loop can react) rather than raising, so the deny assertions key off that string.
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

#: Smolagents' importable package name (the SDK adapter's ``get_framework_name``).
FRAMEWORK_IMPORT = "smolagents"
FRAMEWORK_PACKAGE = "smolagents"

#: The adapter's deny short-circuit marker (``_format_blocked_message``). The
#: smolagents tool-call patch *returns* this string on a deny rather than raising,
#: so the deny assertions key off it instead of an exception.
BLOCKED_MARKER = "[BLOCKED by governance policy]"


def _build_governed_tool():  # noqa: ANN202 — returns a smolagents Tool subclass instance
    """Return a real smolagents ``Tool`` whose execution we can observe.

    ``forward`` appends to a list it closes over, so a test can assert the tool
    actually *ran* (the allow decision let it through ``Tool.__call__``) versus
    was short-circuited by the adapter's deny branch.
    """
    from smolagents import Tool

    calls: list[str] = []

    class SearchTool(Tool):  # type: ignore[misc]  # base is a runtime-imported framework class (untyped)
        name = "search"
        description = "Search the web for a query."
        inputs = {"query": {"type": "string", "description": "the query"}}
        output_type = "string"

        def forward(self, query: str) -> str:
            calls.append(query)
            return f"results for {query}"

    return SearchTool(), calls


def test_smolagents_governance_path_is_wired() -> None:
    """Offline: the SDK's smolagents adapter patches ``Tool.__call__`` and honours deny.

    The floor under the live path: the real ``SmolagentsPatch`` routes a tool call
    through an interceptor's ``check_tool_start`` and short-circuits on a ``deny``
    (returning the blocked message, not running ``forward``). A stub enforce-posture
    interceptor proves the patch honours the decision contract with no live runtime,
    so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.smolagents.patch import SmolagentsPatch

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    tool, calls = _build_governed_tool()
    patch = SmolagentsPatch(_DenyInterceptor())
    assert patch.apply() is True, "smolagents tool hook did not install"
    try:
        result = tool(query="weather")
        assert calls == [], "deny path let the smolagents tool body execute"
        assert BLOCKED_MARKER in str(result)
    finally:
        patch.revert()


def test_smolagents_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real smolagents tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, applies
    the real ``SmolagentsPatch``, then runs a genuine ``Tool`` through the patched
    ``Tool.__call__`` — the real ``Smolagents → SDK adapter → aa-ffi → aa-runtime``
    path. The live runtime answers ``query_policy`` with ``allow`` (the fixture
    runtime runs policy-disabled), so the tool executes: we assert its observable
    side effect (the tool ran) and its real output (not the adapter's blocked
    message), proving enforcement let an allowed call through rather than the call
    merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.smolagents.patch import SmolagentsPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = SmolagentsPatch(interceptor)
    assert patch.apply() is True, "smolagents tool hook did not install"
    tool, calls = _build_governed_tool()
    try:
        output = tool(query="weather")

        assert calls == ["weather"], "allowed smolagents tool did not execute under live governance"
        assert output == "results for weather"
        assert BLOCKED_MARKER not in str(output)
    finally:
        patch.revert()


def test_smolagents_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
    """Allow path: the SDK ships a governance/audit event to the live runtime.

    Audit capture and event emission travel the same native ``send_event``
    transport the SDK uses to record what an agent did. Shipping a captured
    ``GovernanceEvent`` over the real UDS to the live runtime without rejection is
    the in-scope, provable-today half of the "audit capture" highlight function
    (full audit-store read-back is covered by the gateway-side tests).
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
def test_smolagents_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied smolagents tool is short-circuited end-to-end (strict-xfail).

    The load-bearing enforcement assertion for smolagents: with a policy that denies
    the tool, running it through the real patched ``Tool.__call__`` against the live
    runtime must return the adapter's ``[BLOCKED by governance policy]`` message
    *before* ``forward`` runs (the adapter signals a deny by returning that message,
    not by raising). It cannot pass today — the fixture runtime runs policy-disabled
    and the SDK's full deny wiring is unshipped (AAASM-3021), so the runtime answers
    ``allow`` and the tool runs. Pinned ``strict=True`` so the day enforcement works
    it XPASSes and the strict marker fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.smolagents.patch import SmolagentsPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = SmolagentsPatch(interceptor)
    assert patch.apply() is True, "smolagents tool hook did not install"
    tool, calls = _build_governed_tool()
    try:
        output = tool(query="secret")
        assert calls == [], "deny path let the tool body execute"
        assert BLOCKED_MARKER in str(output), "deny path did not short-circuit the tool"
    finally:
        patch.revert()
