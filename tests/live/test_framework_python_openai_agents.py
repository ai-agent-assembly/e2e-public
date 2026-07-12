"""Live framework smoke: a real **OpenAI Agents** tool through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests). Unlike LangChain /
LangGraph (callback handler) or Pydantic AI (tool-hook patch), the SDK's OpenAI
Agents adapter wraps ``agents.FunctionTool.__init__`` so that every tool's
per-instance ``on_invoke_tool`` coroutine — the exact callable the runner invokes
to execute a model-chosen tool — is governed by a pre-execution
``check_tool_start`` decision. This test applies the real ``OpenAIAgentsPatch``,
then builds a genuine ``@function_tool`` (constructed *after* the patch so its
``__init__`` is the patched one) and drives its real ``on_invoke_tool`` against a
live ``aa-runtime`` — the production
``OpenAI Agents → SDK adapter → aa-ffi → aa-runtime`` governance path.

REQUIRES THE AAASM-3528 FIX (python-sdk PR #158). Before that fix the adapter
patched ``openai.agents`` / ``FunctionTool.__call__`` — neither of which exists in
the shipped ``openai-agents`` distribution — so the patch silently never applied
and every tool ran ungoverned (fail-open). With the OLD adapter the allow-path
assertions below would still see the tool *run* but with **no** governance edge
(``check_tool_start`` never consulted), so the allow test asserts the live-runtime
decision was actually taken, not merely that the tool produced output. Install the
SDK from the PR #158 worktree (with the compiled native ``_core``) to run this.

The LLM is stubbed (the tool's ``on_invoke_tool`` is invoked directly, exactly as
the runner would call it for a model-chosen tool); the framework and the
governance path are real. The offline floor (``test_openai_agents_governance_path_is_wired``)
needs only the ``agents`` package; the allow path additionally needs ``cargo`` /
``protoc`` (to build ``aa-runtime``) and the SDK's compiled ``_core``; it skips
cleanly otherwise.

The **deny path** (a denied tool actually blocked end-to-end) is a ``strict=True``
xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) — see
:data:`tests.live.framework_live.DENY_XFAIL_REASON`.
"""

from __future__ import annotations

import asyncio
from typing import Any

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

#: OpenAI Agents' importable package name. The shipped ``openai-agents``
#: distribution exposes a *top-level* ``agents`` package (NOT ``openai.agents``,
#: which does not exist) — this distinction is the heart of the AAASM-3528 fix.
FRAMEWORK_IMPORT = "agents"
FRAMEWORK_PACKAGE = "openai-agents"


# Returns a (FunctionTool, calls) tuple; the composite return type is left
# unannotated (ANN202) because the framework's FunctionTool is imported lazily.
def _build_governed_function_tool(governance_calls: list[str]):  # noqa: ANN202
    """Return a real ``@function_tool`` whose execution we can observe.

    Must be called *after* the patch is applied: the adapter wraps
    ``FunctionTool.__init__``, and the ``@function_tool`` decorator constructs the
    ``FunctionTool`` eagerly at decoration time, so a tool defined before the patch
    would carry an unwrapped ``on_invoke_tool``. The tool appends to *calls* it
    closes over, so a test can assert it actually *ran* (allow let it through) or
    did not (deny blocked it).
    """
    from agents import function_tool

    @function_tool
    def lookup(city: str) -> str:
        """Look up the weather for a city."""
        governance_calls.append(city)
        return f"weather in {city}"

    return lookup


def _make_tool_context(tool_input: str) -> Any:
    """Return a real framework ``ToolContext`` for invoking ``on_invoke_tool``.

    A real ``ToolContext`` (not a bare stand-in) is required: the framework's own
    ``on_invoke_tool`` wrapper reads ``ctx.run_config`` / ``ctx.tool_name`` on its
    error path, so a minimal namespace breaks the framework rather than the
    governance layer. The adapter resolves the acting agent id from
    ``ctx.agent_id`` / ``ctx.agent`` (neither set here) and falls back to the
    patch's ``process_agent_id`` — the realistic path for a direct tool invocation
    with the LLM stubbed.
    """
    from agents.tool_context import ToolContext
    from agents.usage import Usage

    return ToolContext(
        context=None,
        usage=Usage(),
        tool_name="lookup",
        tool_call_id="aaitest-call-1",
        tool_arguments=tool_input,
    )


def test_openai_agents_governance_path_is_wired() -> None:
    """Offline: the SDK's OpenAI Agents patch wraps a real tool's ``on_invoke_tool``.

    The floor under the live path, provable with no toolchain: applying the real
    ``OpenAIAgentsPatch`` against a deny interceptor makes a genuine
    ``@function_tool``'s ``on_invoke_tool`` consult ``check_tool_start`` and honour
    a ``deny`` by returning the governance error string (the framework's contract:
    a denied tool returns an error to the model rather than raising). This proves
    the AAASM-3528 interception point is actually installed — with the OLD adapter
    the patch never applied and the tool body would run regardless of the decision.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.openai_agents.patch import OpenAIAgentsPatch

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    calls: list[str] = []
    patch = OpenAIAgentsPatch(callback_handler=_DenyInterceptor(), process_agent_id="aaitest-oai")
    assert patch.apply() is True, "OpenAI Agents FunctionTool patch did not install"
    try:
        tool = _build_governed_function_tool(calls)
        result = asyncio.run(
            tool.on_invoke_tool(_make_tool_context('{"city": "paris"}'), '{"city": "paris"}')
        )
        assert calls == [], "deny decision did not block the tool body"
        assert "blocked by governance policy" in str(result)
    finally:
        patch.revert()


def test_openai_agents_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real OpenAI Agents tool runs governed by a live runtime decision.

    Applies the real ``OpenAIAgentsPatch`` wired to the production interceptor
    against the live runtime, then builds a genuine ``@function_tool`` and invokes
    its real ``on_invoke_tool`` — the runner's exact tool-execution call — over the
    real ``OpenAI Agents → SDK adapter → aa-ffi → aa-runtime`` path. The live
    runtime answers ``query_policy`` with ``allow`` (the fixture runtime runs
    policy-disabled), so the tool executes: we assert its observable side effect
    and output.

    This only passes with the AAASM-3528 fix: with the OLD adapter the patch never
    installed, so ``on_invoke_tool`` would not be wrapped and the live-runtime
    decision would never be consulted. To make the governance edge load-bearing
    (not just "the tool ran"), a sentinel interceptor wraps the production one and
    records each ``check_tool_start``; the assertion that the live decision was
    actually taken is what the OLD adapter fails.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.openai_agents.patch import OpenAIAgentsPatch

    interceptor = live_runtime_interceptor(live_runtime)

    # Wrap the production interceptor so a test can prove the patched tool actually
    # consulted the live-runtime decision — the edge the OLD (unapplied) adapter
    # silently skipped. The sentinel delegates the real decision to the live
    # interceptor; it only records that the check happened.
    checked: list[str] = []

    class _RecordingInterceptor:
        _enforce = True

        def check_tool_start(self, **kwargs: object) -> object:
            checked.append(str(kwargs.get("tool_name")))
            return interceptor.check_tool_start(**kwargs)

        def __getattr__(self, name: str) -> Any:
            # The adapter probes ``_interceptor`` to unwrap a nested governance
            # target (``_resolve_governance_target``); the real interceptor's own
            # ``__getattr__`` delegates *that* to its inert client and returns a
            # no-op, which would silently make the adapter govern through the
            # unwrapped target and skip this recorder. Refusing the private probe
            # keeps the recorder as the resolved target so the edge is observable.
            if name.startswith("_"):
                raise AttributeError(name)
            return getattr(interceptor, name)

    calls: list[str] = []
    patch = OpenAIAgentsPatch(
        callback_handler=_RecordingInterceptor(), process_agent_id="aaitest-oai"
    )
    assert patch.apply() is True, "OpenAI Agents FunctionTool patch did not install"
    try:
        tool = _build_governed_function_tool(calls)
        result = asyncio.run(
            tool.on_invoke_tool(_make_tool_context('{"city": "berlin"}'), '{"city": "berlin"}')
        )

        assert checked == ["lookup"], (
            "governed tool did not consult the live-runtime decision — the AAASM-3528 "
            "fix (PR #158) is required; the OLD adapter never installs the patch"
        )
        assert calls == ["berlin"], (
            "allowed OpenAI Agents tool did not execute under live governance"
        )
        assert "weather in berlin" in str(result)
    finally:
        patch.revert()


def test_openai_agents_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
    """Allow path: the SDK ships a governance/audit event to the live runtime.

    Audit capture and event emission travel the same native ``send_event``
    transport the SDK uses to record what an agent did. Shipping a captured
    ``GovernanceEvent`` over the real UDS to the live runtime without rejection is
    the in-scope, provable-today half of the "audit capture" highlight function
    (full audit-store read-back is covered by the gateway-side tests). Mirrors the
    sibling framework cells so OpenAI Agents has the same audit-edge coverage.
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
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)  # AAASM-3172
def test_openai_agents_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied OpenAI Agents tool is blocked end-to-end (strict-xfail).

    The load-bearing enforcement assertion for OpenAI Agents: with a policy that
    denies the tool, invoking its real ``on_invoke_tool`` through the patched path
    against the live runtime must block the tool body (the adapter returns the
    governance error string instead of running it). It cannot pass today — the
    fixture runtime runs policy-disabled and the SDK's full deny wiring is unshipped
    (AAASM-3021), so the runtime answers ``allow`` and the tool runs. Pinned
    ``strict=True`` so the day enforcement works it XPASSes and the strict marker
    fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.openai_agents.patch import OpenAIAgentsPatch

    interceptor = live_runtime_interceptor(live_runtime)
    calls: list[str] = []
    patch = OpenAIAgentsPatch(callback_handler=interceptor, process_agent_id="aaitest-oai")
    assert patch.apply() is True, "OpenAI Agents FunctionTool patch did not install"
    try:
        result = asyncio.run(
            _build_governed_function_tool(calls).on_invoke_tool(
                _make_tool_context('{"city": "secret"}'), '{"city": "secret"}'
            )
        )
        assert calls == [], "deny path let the tool body execute"
        assert "blocked by governance policy" in str(result)
    finally:
        patch.revert()
