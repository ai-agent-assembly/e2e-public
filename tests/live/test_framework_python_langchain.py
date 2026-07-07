"""Live framework smoke: a real **LangChain** agent through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests). This drives a genuine
LangChain tool through the SDK's real ``AssemblyCallbackHandler`` against a live
``aa-runtime`` — the production ``LangChain → SDK adapter → aa-ffi → aa-runtime``
governance path. Nothing here is mocked except the LLM, which the test does not
need: it invokes a real ``@tool`` with the governance callback attached, exactly
as LangChain itself routes a model-chosen tool call.

The **highlight governance functions** this exercises (per the AAASM-3525 plan):

* **Pre-execution allow enforcement** — the callback's ``on_tool_start`` asks the
  live runtime ``query_policy`` whether the tool may run; an ``allow`` lets the
  real tool execute (asserted by the tool's observable side effect + output).
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport, the path
  the SDK uses to record audit events.

The **deny path** (a denied tool actually blocked end-to-end) is a ``strict=True``
xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) — see
:data:`tests.live.framework_live.DENY_XFAIL_REASON`.

Layers, by what they need:

* **offline** — the SDK adapter + callback handler import and wire up with no
  toolchain (``test_langchain_governance_path_is_wired``).
* **allow path (live)** — needs ``cargo``/``protoc`` (to build ``aa-runtime``),
  the SDK's compiled ``_core``, and ``langchain``; skips cleanly otherwise.
* **deny path (live, strict-xfail)** — same prerequisites, pinned xfail.
"""

from __future__ import annotations

from uuid import uuid4

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

#: LangChain's importable package name (the SDK adapter's ``get_framework_name``).
FRAMEWORK_IMPORT = "langchain_core"
FRAMEWORK_PACKAGE = "langchain (langchain-core)"


def _build_search_tool():  # noqa: ANN202 — returns a langchain StructuredTool
    """Return a real LangChain ``@tool`` whose execution we can observe.

    The tool appends to a list it closes over, so a test can assert it actually
    *ran* (the allow decision let it through) versus was blocked.
    """
    from langchain_core.tools import tool

    calls: list[str] = []

    @tool
    def search(query: str) -> str:
        """Search the web for a query."""
        calls.append(query)
        return f"results for {query}"

    return search, calls


def test_langchain_governance_path_is_wired() -> None:
    """Offline: the SDK's LangChain adapter + callback handler wire up cleanly.

    The floor under the live path: the real ``AssemblyCallbackHandler`` routes a
    tool start through an interceptor's ``check_tool_start`` and *blocks* on a
    ``deny``. A stub interceptor proves the handler honours the decision contract
    with no toolchain, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.langchain.callback_handler import (
        AssemblyCallbackHandler,
    )
    from agent_assembly.exceptions import ToolExecutionBlockedError

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    handler = AssemblyCallbackHandler(_DenyInterceptor())
    run_id = uuid4()  # Extract to avoid multiple potentially-throwing calls in pytest.raises
    with pytest.raises(ToolExecutionBlockedError):
        handler.on_tool_start({"name": "search"}, "hi", run_id=run_id, tool_name="search")


def test_langchain_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real LangChain tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, hands
    it to the real ``AssemblyCallbackHandler``, then invokes a genuine LangChain
    ``@tool`` with that handler as a callback — the real
    ``LangChain → SDK adapter → aa-ffi → aa-runtime`` path. The live runtime
    answers ``query_policy`` with ``allow`` (the fixture runtime runs
    policy-disabled), so the tool executes: we assert its observable side effect
    (the tool ran) and its output, proving enforcement let an allowed call
    through rather than the call merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.langchain.callback_handler import (
        AssemblyCallbackHandler,
    )

    interceptor = live_runtime_interceptor(live_runtime)
    handler = AssemblyCallbackHandler(interceptor)
    search, calls = _build_search_tool()

    output = search.invoke({"query": "weather"}, config={"callbacks": [handler]})

    assert calls == ["weather"], "allowed LangChain tool did not execute under live governance"
    assert output == "results for weather"


def test_langchain_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
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
# resolved), drop this strict xfail and assert the denied tool is blocked.
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)
def test_langchain_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied LangChain tool is blocked end-to-end (strict-xfail).

    The load-bearing enforcement assertion for LangChain: with a policy that
    denies the tool, invoking it through the real callback against the live
    runtime must raise ``ToolExecutionBlockedError`` before the tool body runs.
    It cannot pass today — the fixture runtime runs policy-disabled and the SDK's
    full deny wiring is unshipped (AAASM-3021), so the runtime answers ``allow``
    and the tool runs. Pinned ``strict=True`` so the day enforcement works it
    XPASSes and the strict marker fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.langchain.callback_handler import (
        AssemblyCallbackHandler,
    )
    from agent_assembly.exceptions import ToolExecutionBlockedError

    interceptor = live_runtime_interceptor(live_runtime)
    handler = AssemblyCallbackHandler(interceptor)
    search, calls = _build_search_tool()

    with pytest.raises(ToolExecutionBlockedError):
        search.invoke({"query": "secret"}, config={"callbacks": [handler]})
    assert calls == [], "deny path let the tool body execute"
