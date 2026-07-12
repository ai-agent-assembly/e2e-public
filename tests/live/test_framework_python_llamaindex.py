"""Live framework smoke: a real **LlamaIndex** agent tool through the SDK + live core.

Part of AAASM-3525 / AAASM-3536 (real, non-mock framework smoke tests). The
SDK's LlamaIndex adapter monkey-patches the concrete ``FunctionTool.call`` /
``acall`` execution methods so a governed tool consults ``check_tool_start``
before its body runs — the exact methods a LlamaIndex agent
(``FunctionAgent`` / ``ReActAgent`` via ``AgentWorkflow``) invokes to execute a
tool. This test applies the real ``LlamaIndexPatch`` and drives a genuine
``FunctionTool`` against a live ``aa-runtime`` — the production
``LlamaIndex → SDK adapter → aa-ffi → aa-runtime`` governance path.

Why drive ``FunctionTool.call`` directly rather than a full agent run: the agent
loop requires a real LLM to *decide* to call the tool, which cannot run offline.
The governance hook the SDK installs is on ``FunctionTool.call`` / ``acall`` —
the exact call the agent loop makes to execute a tool — so invoking the governed
tool exercises the identical production path with only the model absent. This
mirrors the CrewAI cell.

The **highlight governance functions** this exercises:

* **Pre-execution allow enforcement** — the patched ``FunctionTool.call`` asks
  the live runtime ``query_policy`` (via the production
  ``RuntimeQueryInterceptor``) whether the tool may run; an ``allow`` lets the
  real tool body execute (asserted by its side effect + output, versus the
  adapter's ``[BLOCKED by governance policy]`` short-circuit).
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport.

The **deny path** is a ``strict=True`` xfail pinned on AAASM-3000 + AAASM-3021
(flip via AAASM-3172). Like CrewAI, the LlamaIndex adapter expresses a deny by
*returning* a denial ``ToolOutput`` (``is_error=True`` carrying the
``[BLOCKED by governance policy]`` message) rather than raising — so the deny
assertion checks the tool body did not run and the blocked message was returned.
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

#: LlamaIndex's importable package name (the SDK adapter's ``get_framework_name``).
FRAMEWORK_IMPORT = "llama_index.core"
FRAMEWORK_PACKAGE = "llama-index-core"

#: The adapter's deny short-circuit marker (``_format_blocked_message``). The
#: LlamaIndex tool patch *returns* a ``ToolOutput`` carrying this string on a deny
#: rather than raising, so the deny assertions key off it instead of an exception.
BLOCKED_MARKER = "[BLOCKED by governance policy]"


def _build_governed_tool(interceptor):  # noqa: ANN001, ANN202
    """Return a real LlamaIndex ``FunctionTool`` governed by *interceptor*.

    Applies the real ``LlamaIndexPatch`` so the tool's ``call`` consults the
    live-runtime governance decision. The ``calls`` list records each execution;
    the returned patch must be reverted by the caller to leave ``FunctionTool``
    unpatched.
    """
    from agent_assembly.adapters.llamaindex.patch import LlamaIndexPatch
    from llama_index.core.tools import FunctionTool

    patch = LlamaIndexPatch(callback_handler=interceptor, process_agent_id="aaitest-llama")
    assert patch.apply() is True, "LlamaIndex tool hook did not install"

    calls: list[str] = []

    def search(query: str) -> str:
        """Search the web for a query."""
        calls.append(query)
        return f"results for {query}"

    tool = FunctionTool.from_defaults(fn=search, name="search")
    return tool, calls, patch


def test_llamaindex_governance_path_is_wired() -> None:
    """Offline: the SDK's LlamaIndex adapter patches ``FunctionTool.call`` and honours deny.

    The floor under the live path: the real ``LlamaIndexPatch`` routes a tool
    call through an interceptor's ``check_tool_start`` and short-circuits on a
    ``deny`` (returning a denial ``ToolOutput``, not running the body). A stub
    enforce-posture interceptor proves the patch honours the decision contract
    with no live runtime, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    tool, calls, patch = _build_governed_tool(_DenyInterceptor())
    try:
        result = tool.call(query="weather")
        assert calls == [], "deny path let the LlamaIndex tool body execute"
        assert BLOCKED_MARKER in str(getattr(result, "content", result))
    finally:
        patch.revert()


def test_llamaindex_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real LlamaIndex tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, applies
    the real ``LlamaIndexPatch``, then runs the governed tool through the patched
    ``FunctionTool.call`` — the real ``LlamaIndex → SDK adapter → aa-ffi →
    aa-runtime`` path. The live runtime answers ``query_policy`` with ``allow``
    (the fixture runtime runs policy-disabled), so the tool executes: we assert its
    observable side effect (the tool ran) and its real output (not the adapter's
    blocked message), proving enforcement let an allowed call through rather than
    the call merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)

    interceptor = live_runtime_interceptor(live_runtime)
    tool, calls, patch = _build_governed_tool(interceptor)
    try:
        output = tool.call(query="weather")

        assert calls == ["weather"], "allowed LlamaIndex tool did not execute under live governance"
        content = str(getattr(output, "content", output))
        assert "results for weather" in content
        assert BLOCKED_MARKER not in content
    finally:
        patch.revert()


def test_llamaindex_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
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
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)  # AAASM-3172
def test_llamaindex_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied LlamaIndex tool is short-circuited end-to-end (strict-xfail).

    The load-bearing enforcement assertion for LlamaIndex: with a policy that
    denies the tool, running it through the real patched ``FunctionTool.call``
    against the live runtime must return the adapter's denial ``ToolOutput``
    (carrying ``[BLOCKED by governance policy]``) *before* the tool body runs
    (the adapter signals a deny by returning that, not by raising). It cannot pass
    today — the fixture runtime runs policy-disabled and the SDK's full deny wiring
    is unshipped (AAASM-3021), so the runtime answers ``allow`` and the tool runs.
    Pinned ``strict=True`` so the day enforcement works it XPASSes and the strict
    marker fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)

    interceptor = live_runtime_interceptor(live_runtime)
    tool, calls, patch = _build_governed_tool(interceptor)
    try:
        output = tool.call(query="secret")
        assert calls == [], "deny path let the tool body execute"
        content = str(getattr(output, "content", output))
        assert BLOCKED_MARKER in content, "deny path did not short-circuit the tool"
    finally:
        patch.revert()
