"""Live framework smoke: a real **Haystack** agent through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests) — added for AAASM-3540.
The SDK's Haystack adapter monkey-patches ``haystack.tools.Tool.invoke`` so a
governed tool consults ``check_tool_start`` before its body executes — the single
execution chokepoint in Haystack 2.x. Both a bare ``Tool.invoke()`` and the agentic
``Agent`` → ``ToolInvoker`` tool-call loop end up calling ``tool.invoke(**args)``
(via ``ToolInvoker._make_context_bound_invoke``), so patching ``Tool.invoke``
governs the whole tool-call path.

This test applies the real ``HaystackPatch`` and drives the governed tool through a
**real** ``haystack.components.tools.ToolInvoker`` — the exact component a Haystack
``Agent`` uses to execute a model-chosen tool call — against a live ``aa-runtime``:
the production ``Haystack → SDK adapter → aa-ffi → aa-runtime`` governance path.

Why drive ``ToolInvoker.run`` rather than a full ``Agent.run``: a full agent run
requires a real LLM to *decide* to call the tool, which cannot run offline and is
brittle to stub across chat-generator backends. ``ToolInvoker`` is the agent's
real tool-dispatch component and calls ``Tool.invoke`` exactly as the agent loop
does, so feeding it a hand-built ``ToolCall`` exercises the identical production
path with the framework objects fully real and only the model absent — mirroring
the CrewAI / LangChain cells, which invoke the real governed tool without a live LLM.

The **highlight governance functions** this exercises (per the AAASM-3525 plan):

* **Pre-execution allow enforcement** — the patched ``Tool.invoke`` asks the live
  runtime ``query_policy`` (via the production ``RuntimeQueryInterceptor``) whether
  the tool may run; an ``allow`` lets the real tool body execute (asserted by the
  tool's observable side effect + its real output, versus the adapter's
  ``[BLOCKED by governance policy]`` short-circuit string).
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport.

The **deny path** (a denied tool actually short-circuited end-to-end) is a
``strict=True`` xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) — see
:data:`tests.live.framework_live.DENY_XFAIL_REASON`. Like CrewAI, the Haystack
adapter expresses a deny by *returning* the ``[BLOCKED by governance policy]``
message (so the agent can react) rather than raising, so the deny assertion checks
the tool body did not run and the blocked message was returned.
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

#: Haystack's importable package name (the SDK adapter's ``get_framework_name``).
FRAMEWORK_IMPORT = "haystack"
FRAMEWORK_PACKAGE = "haystack-ai (haystack)"

#: The adapter's deny short-circuit marker (``_format_blocked_message``). The
#: Haystack tool-invoke patch *returns* this string on a deny rather than raising,
#: so the agent loop can react — the deny assertions key off it instead of an
#: exception.
BLOCKED_MARKER = "[BLOCKED by governance policy]"

#: A JSON-schema for the governed tool's single ``query`` parameter. Haystack's
#: ``Tool`` requires an explicit parameters schema.
_TOOL_SCHEMA = {
    "type": "object",
    "properties": {"query": {"type": "string"}},
    "required": ["query"],
}


def _build_governed_tool():  # noqa: ANN202
    """Return a real Haystack ``Tool`` whose execution we can observe.

    The tool's function appends to a list it closes over, so a test can assert it
    actually *ran* (the allow decision let it through ``Tool.invoke``) versus was
    short-circuited by the adapter's deny branch.
    """
    from haystack.tools import Tool

    calls: list[str] = []

    def search(query: str) -> str:
        calls.append(query)
        return f"results for {query}"

    tool = Tool(
        name="search",
        description="Search the web for a query.",
        parameters=_TOOL_SCHEMA,
        function=search,
    )
    return tool, calls


def _invoke_through_tool_invoker(tool, query: str) -> str:  # noqa: ANN001 — tool is a haystack Tool
    """Run *tool* via a real ``ToolInvoker`` with a hand-built ``ToolCall``.

    Drives the genuine Haystack agent tool-dispatch component (``ToolInvoker``,
    the thing an ``Agent`` uses to execute a model-chosen tool call) so the
    governed ``Tool.invoke`` is exercised on the real agent path, not in isolation.
    Returns the tool-call result string the invoker produced (the tool's output on
    allow, or the adapter's blocked message on deny).
    """
    from haystack.components.tools import ToolInvoker
    from haystack.dataclasses import ChatMessage, ToolCall

    invoker = ToolInvoker(tools=[tool])
    invoker.warm_up()
    message = ChatMessage.from_assistant(
        tool_calls=[ToolCall(tool_name=tool.name, arguments={"query": query})]
    )
    output = invoker.run(messages=[message])
    return str(output["tool_messages"][0].tool_call_results[0].result)


def test_haystack_governance_path_is_wired() -> None:
    """Offline: the SDK's Haystack adapter patches ``Tool.invoke`` and honours deny.

    The floor under the live path: the real ``HaystackPatch`` routes a tool
    invocation through an interceptor's ``check_tool_start`` and short-circuits on
    a ``deny`` (returning the blocked message, not running the body). A stub
    enforce-posture interceptor proves the patch honours the decision contract with
    no live runtime, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.haystack.patch import HaystackPatch

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    tool, calls = _build_governed_tool()
    patch = HaystackPatch(_DenyInterceptor())
    assert patch.apply() is True, "Haystack tool hook did not install"
    try:
        result = tool.invoke(query="weather")
        assert calls == [], "deny path let the Haystack tool body execute"
        assert BLOCKED_MARKER in str(result)
    finally:
        patch.revert()


def test_haystack_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real Haystack tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, applies
    the real ``HaystackPatch``, then runs the governed tool through a genuine
    ``ToolInvoker`` (the agent's tool-dispatch component) — the real
    ``Haystack → SDK adapter → aa-ffi → aa-runtime`` path. The live runtime answers
    ``query_policy`` with ``allow`` (the fixture runtime runs policy-disabled), so
    the tool executes: we assert its observable side effect (the tool ran) and its
    real output (not the adapter's blocked message), proving enforcement let an
    allowed call through rather than the call merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.haystack.patch import HaystackPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = HaystackPatch(interceptor)
    assert patch.apply() is True, "Haystack tool hook did not install"
    tool, calls = _build_governed_tool()
    try:
        output = _invoke_through_tool_invoker(tool, "weather")

        assert calls == ["weather"], "allowed Haystack tool did not execute under live governance"
        assert output == "results for weather"
        assert BLOCKED_MARKER not in output
    finally:
        patch.revert()


def test_haystack_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
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
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)  # AAASM-3172
def test_haystack_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied Haystack tool is short-circuited end-to-end (strict-xfail).

    The load-bearing enforcement assertion for Haystack: with a policy that denies
    the tool, running it through the real patched ``Tool.invoke`` (via a genuine
    ``ToolInvoker``) against the live runtime must return the adapter's
    ``[BLOCKED by governance policy]`` message *before* the tool body runs (the
    Haystack adapter signals a deny by returning that message, not by raising). It
    cannot pass today — the fixture runtime runs policy-disabled and the SDK's full
    deny wiring is unshipped (AAASM-3021), so the runtime answers ``allow`` and the
    tool runs. Pinned ``strict=True`` so the day enforcement works it XPASSes and
    the strict marker fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.haystack.patch import HaystackPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = HaystackPatch(interceptor)
    assert patch.apply() is True, "Haystack tool hook did not install"
    tool, calls = _build_governed_tool()
    try:
        output = _invoke_through_tool_invoker(tool, "secret")
        assert calls == [], "deny path let the tool body execute"
        assert BLOCKED_MARKER in output, "deny path did not short-circuit the tool"
    finally:
        patch.revert()
