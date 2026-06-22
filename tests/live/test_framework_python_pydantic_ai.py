"""Live framework smoke: a real **Pydantic AI** agent through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests). Unlike LangChain /
LangGraph (which route through a callback handler), the SDK's Pydantic AI adapter
monkey-patches the framework's tool-execution hook (``Tool._run`` on <0.3.0,
``AbstractToolset.call_tool`` / ``FunctionToolset`` on >=0.3.0) so a governed
tool consults ``check_tool_start`` before running. This test applies the real
``PydanticAIPatch`` and runs a genuine ``Agent`` driven by Pydantic AI's offline
``TestModel`` (no real LLM, no network) that calls a real function tool, against
a live ``aa-runtime`` — the production
``Pydantic AI → SDK adapter → aa-ffi → aa-runtime`` governance path.

Highlight functions exercised: **pre-execution allow enforcement** (the live
runtime ``query_policy`` decision gates the patched tool) inside a real agent
run. The **deny path** is a ``strict=True`` xfail pinned on AAASM-3000 +
AAASM-3021 (flip via AAASM-3172).
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

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: Pydantic AI's importable package name (the SDK adapter's framework name).
FRAMEWORK_IMPORT = "pydantic_ai"
FRAMEWORK_PACKAGE = "pydantic-ai (or pydantic-ai-slim)"


def _build_test_agent(interceptor):  # noqa: ANN001, ANN202 — returns (Agent, calls, patch)
    """Return a real Pydantic AI ``Agent`` (offline ``TestModel``) with a governed tool.

    Applies the real ``PydanticAIPatch`` against *interceptor* so the agent's
    function tool consults the live-runtime governance decision when it runs. The
    returned ``calls`` list records each tool execution; the returned patch must
    be reverted by the caller to leave the framework classes unpatched.
    """
    from agent_assembly.adapters.pydantic_ai.patch import PydanticAIPatch
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel

    patch = PydanticAIPatch(callback_handler=interceptor, process_agent_id="aaitest-pyd")
    assert patch.apply() is True, "Pydantic AI tool hook did not install"

    agent = Agent(TestModel())
    calls: list[str] = []

    @agent.tool_plain
    def lookup(city: str) -> str:
        """Look up the weather for a city."""
        calls.append(city)
        return f"weather in {city}"

    return agent, calls, patch


def test_pydantic_ai_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real Pydantic AI agent runs a governed tool via the live runtime.

    Drives a genuine ``Agent`` with the offline ``TestModel`` (which deterministically
    calls the registered tool) while the real ``PydanticAIPatch`` routes that tool
    call through ``check_tool_start`` → live runtime ``query_policy``. The runtime
    answers ``allow``, so the tool executes inside the agent run — asserted via the
    recorded call, proving enforcement let the framework's tool through.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)

    interceptor = live_runtime_interceptor(live_runtime)
    agent, calls, patch = _build_test_agent(interceptor)
    try:
        result = agent.run_sync("look up a city")
        assert calls, "allowed Pydantic AI tool did not execute under live governance"
        assert "weather in" in str(result.output)
    finally:
        patch.revert()


# AAASM-3172 FLIP SITE: see the LangChain deny test.
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)
def test_pydantic_ai_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied Pydantic AI tool is blocked end-to-end (strict-xfail).

    With a policy that denies the tool, the patched tool execution must raise
    (``PolicyViolationError``) before the tool body runs. Cannot pass today
    (policy-disabled fixture runtime + unshipped SDK deny wiring, AAASM-3021), so
    it is pinned ``strict=True`` and flips via AAASM-3172.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.exceptions import PolicyViolationError

    interceptor = live_runtime_interceptor(live_runtime)
    agent, calls, patch = _build_test_agent(interceptor)
    try:
        with pytest.raises(PolicyViolationError):
            agent.run_sync("look up a city")
        assert calls == [], "deny path let the tool body execute"
    finally:
        patch.revert()
