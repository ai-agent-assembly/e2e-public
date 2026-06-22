"""Live framework smoke: a real **Microsoft Agent Framework** tool through the SDK + live core.

Part of AAASM-3525 / AAASM-3538 (real, non-mock framework smoke tests). Microsoft's
unified Agent Framework (PyPI ``agent-framework``, importable module
``agent_framework``) executes **every** function tool through the single async
coroutine ``agent_framework.FunctionTool.invoke``. The SDK's Microsoft Agent
Framework adapter monkey-patches that coroutine so a governed tool consults
``check_tool_start`` before its body runs — the exact call an Agent Framework agent
makes to execute a tool.

This test applies the real ``MicrosoftAgentFrameworkPatch`` and drives a genuine
``@agent_framework.tool``-decorated ``FunctionTool`` (constructed offline, no LLM
call) against a live ``aa-runtime`` — the production
``Microsoft Agent Framework → SDK adapter → aa-ffi → aa-runtime`` governance path.

Why drive ``FunctionTool.invoke`` directly rather than a full agent ``run``: a full
agent run requires a real chat model to *decide* to call the tool, which cannot run
offline and is brittle to stub across providers. The governance hook the SDK installs
is on ``FunctionTool.invoke`` — the exact call an Agent Framework agent makes to
execute a tool — so invoking the governed tool exercises the identical production
path with the tool object fully real and only the model absent. This mirrors the
CrewAI cell, which drives the governed ``BaseTool.run`` without a live LLM.

Highlight functions exercised: **pre-execution allow enforcement** (the live runtime
``query_policy`` decision gates the patched tool) plus **event emission**. The **deny
path** is a ``strict=True`` xfail pinned on AAASM-3000 + AAASM-3021 (flip via
AAASM-3172). The Microsoft adapter expresses a deny by *raising*
``PolicyViolationError`` (like the Pydantic AI adapter), so the deny assertion checks
the tool body did not run and the call raised.
"""

from __future__ import annotations

import asyncio

import pytest

from tests.live.framework_live import (
    DENY_XFAIL_REASON,
    live_runtime_interceptor,
    require_framework,
    require_native_core,
)
from tests.live.runtime import LiveRuntime

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: The SDK adapter's framework name vs the importable module differ: the package
#: is ``agent-framework`` and imports as the top-level ``agent_framework``.
FRAMEWORK_IMPORT = "agent_framework"
FRAMEWORK_PACKAGE = "agent-framework"


def _build_governed_tool():  # noqa: ANN202 — returns (FunctionTool, calls)
    """Return a real Agent Framework ``FunctionTool`` whose execution we can observe.

    The tool appends to a list it closes over, so a test can assert it actually
    *ran* (the allow decision let it through ``FunctionTool.invoke``) versus was
    short-circuited by the adapter's deny branch (which raises).
    """
    import agent_framework as af

    calls: list[str] = []

    @af.tool
    def search(query: str) -> str:
        """Search the web for a query."""
        calls.append(query)
        return f"results for {query}"

    return search, calls


def test_microsoft_agent_framework_governance_path_is_wired() -> None:
    """Offline: the SDK adapter patches ``FunctionTool.invoke`` and honours deny.

    The floor under the live path: the real ``MicrosoftAgentFrameworkPatch`` routes a
    tool invocation through an interceptor's ``check_tool_start`` and short-circuits on
    a ``deny`` (raising ``PolicyViolationError``, not running the body). A stub
    enforce-posture interceptor proves the patch honours the decision contract with no
    live runtime, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.microsoft_agent_framework.patch import (
        MicrosoftAgentFrameworkPatch,
    )
    from agent_assembly.exceptions import PolicyViolationError

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    tool, calls = _build_governed_tool()
    patch = MicrosoftAgentFrameworkPatch(_DenyInterceptor())
    assert patch.apply() is True, "Microsoft Agent Framework tool hook did not install"
    try:
        with pytest.raises(PolicyViolationError):
            asyncio.run(tool.invoke(arguments={"query": "weather"}))
        assert calls == [], "deny path let the Microsoft Agent Framework tool body execute"
    finally:
        patch.revert()


def test_microsoft_agent_framework_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real Agent Framework tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, applies the
    real ``MicrosoftAgentFrameworkPatch``, then invokes the governed ``FunctionTool``
    through the patched ``invoke`` — the real
    ``Microsoft Agent Framework → SDK adapter → aa-ffi → aa-runtime`` path. The live
    runtime answers ``query_policy`` with ``allow`` (the fixture runtime runs
    policy-disabled), so the tool executes: we assert its observable side effect (the
    tool ran) and its real output, proving enforcement let an allowed call through
    rather than the call merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.microsoft_agent_framework.patch import (
        MicrosoftAgentFrameworkPatch,
    )

    interceptor = live_runtime_interceptor(live_runtime)
    patch = MicrosoftAgentFrameworkPatch(interceptor)
    assert patch.apply() is True, "Microsoft Agent Framework tool hook did not install"
    tool, calls = _build_governed_tool()
    try:
        result = asyncio.run(tool.invoke(arguments={"query": "weather"}))

        assert calls == ["weather"], (
            "allowed Microsoft Agent Framework tool did not execute under live governance"
        )
        assert "results for weather" in str(result)
    finally:
        patch.revert()


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), drop this strict xfail and assert the denied tool is short-circuited.
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)
def test_microsoft_agent_framework_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied Agent Framework tool is blocked end-to-end (strict-xfail).

    The load-bearing enforcement assertion: with a policy that denies the tool,
    invoking it through the real patched ``FunctionTool.invoke`` against the live
    runtime must raise ``PolicyViolationError`` *before* the tool body runs. It cannot
    pass today — the fixture runtime runs policy-disabled and the SDK's full deny
    wiring is unshipped (AAASM-3021), so the runtime answers ``allow`` and the tool
    runs. Pinned ``strict=True`` so the day enforcement works it XPASSes and the strict
    marker fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.microsoft_agent_framework.patch import (
        MicrosoftAgentFrameworkPatch,
    )
    from agent_assembly.exceptions import PolicyViolationError

    interceptor = live_runtime_interceptor(live_runtime)
    patch = MicrosoftAgentFrameworkPatch(interceptor)
    assert patch.apply() is True, "Microsoft Agent Framework tool hook did not install"
    tool, calls = _build_governed_tool()
    try:
        with pytest.raises(PolicyViolationError):
            asyncio.run(tool.invoke(arguments={"query": "secret"}))
        assert calls == [], "deny path let the tool body execute"
    finally:
        patch.revert()
