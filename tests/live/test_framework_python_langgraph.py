"""Live framework smoke: a real **LangGraph** agent through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests). LangGraph builds on
``langchain-core`` and its tool execution routes through the same SDK
``AssemblyCallbackHandler`` the LangChain adapter uses (the
``LangGraphAdapter`` patches LangGraph's tool nodes onto that handler). This test
drives a genuine compiled ``StateGraph`` whose node invokes a real tool with the
governance callback against a live ``aa-runtime`` — the production
``LangGraph → SDK adapter → aa-ffi → aa-runtime`` path. Only the LLM is absent;
the graph, the node, and the governance path are real.

Highlight functions exercised: **pre-execution allow enforcement** (the live
runtime ``query_policy`` decision gates the tool inside a real graph node) and
**event emission / audit capture** (native ``send_event`` over the real UDS).
The **deny path** is a ``strict=True`` xfail pinned on AAASM-3000 + AAASM-3021
(flip via AAASM-3172).
"""

from __future__ import annotations

from typing import TypedDict

import pytest

from tests.live.framework_live import (
    DENY_XFAIL_REASON,
    live_runtime_interceptor,
    require_framework,
    require_native_core,
)
from tests.live.runtime import LiveRuntime

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: LangGraph's importable package name.
FRAMEWORK_IMPORT = "langgraph"
FRAMEWORK_PACKAGE = "langgraph"


class _GraphState(TypedDict):
    """Minimal graph state: a running total the tool node mutates."""

    total: int


def _build_adder_tool():  # noqa: ANN202 — returns a langchain StructuredTool
    """Return a real LangChain ``@tool`` (LangGraph nodes execute langchain tools).

    Records each call so a test can assert the tool actually ran under the live
    governance decision rather than being silently skipped.
    """
    from langchain_core.tools import tool

    calls: list[dict[str, int]] = []

    @tool
    def adder(a: int, b: int) -> int:
        """Add two integers."""
        calls.append({"a": a, "b": b})
        return a + b

    return adder, calls


def _compile_graph(node):  # noqa: ANN001, ANN202 — node is a graph callable
    """Compile a real one-node ``StateGraph`` routing START → *node* → END."""
    from langgraph.graph import END, START, StateGraph

    graph = StateGraph(_GraphState)
    graph.add_node("call_tool", node)
    graph.add_edge(START, "call_tool")
    graph.add_edge("call_tool", END)
    return graph.compile()


def test_langgraph_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real LangGraph node runs a tool governed by the live runtime.

    Compiles a genuine ``StateGraph`` whose node invokes a real LangChain tool
    with the SDK's ``AssemblyCallbackHandler`` (wired to the live runtime) as a
    callback. The runtime answers ``query_policy`` with ``allow``, so the tool
    runs inside the graph and updates the state — asserted via the tool's
    recorded call and the resulting state, proving enforcement permitted the call
    through the real framework rather than the call merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.langchain.callback_handler import (
        AssemblyCallbackHandler,
    )

    interceptor = live_runtime_interceptor(live_runtime)
    handler = AssemblyCallbackHandler(interceptor)
    adder, calls = _build_adder_tool()

    def call_tool(state: _GraphState) -> _GraphState:
        result = adder.invoke({"a": state["total"], "b": 5}, config={"callbacks": [handler]})
        return {"total": result}

    app = _compile_graph(call_tool)
    final = app.invoke({"total": 10})

    assert calls == [{"a": 10, "b": 5}], "allowed LangGraph tool did not execute"
    assert final["total"] == 15


# AAASM-3172 FLIP SITE: see the LangChain deny test.
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)
def test_langgraph_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied tool is blocked inside a LangGraph node (strict-xfail).

    With a policy that denies the tool, the graph node's invocation must raise
    ``ToolExecutionBlockedError`` before the tool body runs. Cannot pass today
    (policy-disabled fixture runtime + unshipped SDK deny wiring, AAASM-3021), so
    it is pinned ``strict=True`` and flips via AAASM-3172.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.langchain.callback_handler import (
        AssemblyCallbackHandler,
    )
    from agent_assembly.exceptions import ToolExecutionBlockedError

    interceptor = live_runtime_interceptor(live_runtime)
    handler = AssemblyCallbackHandler(interceptor)
    adder, calls = _build_adder_tool()

    def call_tool(state: _GraphState) -> _GraphState:
        result = adder.invoke({"a": state["total"], "b": 5}, config={"callbacks": [handler]})
        return {"total": result}

    app = _compile_graph(call_tool)
    with pytest.raises(ToolExecutionBlockedError):
        app.invoke({"total": 10})
    assert calls == [], "deny path let the tool body execute"
