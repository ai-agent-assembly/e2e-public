"""Live framework smoke: a real **Google ADK** agent through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests). Unlike LangChain /
LangGraph (which route a tool call through a callback handler), the SDK's Google
ADK adapter monkey-patches the framework's async tool-execution hook
(``BaseTool.run_async`` and every concrete tool class that overrides it, e.g.
``FunctionTool``) so a governed tool consults ``check_tool_start`` before its body
runs. This test applies the real ``GoogleADKPatch`` and drives a genuine ADK
``FunctionTool`` through its patched ``run_async`` against a live ``aa-runtime`` —
the production ``Google ADK → SDK adapter → aa-ffi → aa-runtime`` governance path.

Only the LLM is absent: the patched hook is exactly the one ADK itself awaits
when a model-chosen tool call executes, so invoking ``run_async`` directly drives
the same governed path a real agent run takes, without a model or network. The
test owns its own event loop via :func:`asyncio.run` because the patched hook is a
coroutine and this harness ships no ``pytest-asyncio`` plugin.

Highlight functions exercised (per the AAASM-3525 plan):

* **Pre-execution allow enforcement** — the patched ``run_async`` asks the live
  runtime ``query_policy`` (via the interceptor's ``check_tool_start``) whether
  the tool may run; an ``allow`` lets the real tool body execute, asserted by its
  observable side effect + output.
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport.

The **deny path** (a denied tool actually blocked end-to-end) is a ``strict=True``
xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) — see
:data:`tests.live.framework_live.DENY_XFAIL_REASON`.

Layers, by what they need:

* **offline** — the SDK adapter + patch install and honour a deny decision with
  no toolchain (``test_google_adk_governance_path_is_wired``).
* **allow path (live)** — needs ``cargo``/``protoc`` (to build ``aa-runtime``),
  the SDK's compiled ``_core``, and ``google-adk``; skips cleanly otherwise.
* **deny path (live, strict-xfail)** — same prerequisites, pinned xfail.
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
from tests.live.runtime_client import import_native_core, make_audit_entry_payload

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: Google ADK's importable module path. The SDK adapter's framework name is
#: ``google_adk`` but the package imports as ``google.adk`` — the parent
#: ``google`` namespace package must be present, which ``require_framework``
#: checks via ``find_spec``.
FRAMEWORK_IMPORT = "google.adk"
FRAMEWORK_PACKAGE = "google-adk"

#: The process agent id the patch stamps onto a tool call when the ADK
#: invocation context carries none (the direct-``run_async`` drive here).
PROCESS_AGENT_ID = "aaitest-google-adk"


def _build_weather_tool():  # noqa: ANN202 — returns a google.adk FunctionTool
    """Return a real ADK ``FunctionTool`` whose execution we can observe.

    The wrapped function appends to a list it closes over, so a test can assert
    the tool actually *ran* (the allow decision let it through) versus was
    blocked. The function takes no ``ToolContext`` parameter, so ADK's
    ``run_async`` never dereferences the (``None``) context we pass — keeping the
    drive minimal while still exercising the genuine framework execution path.
    """
    from google.adk.tools import FunctionTool

    calls: list[str] = []

    def lookup_weather(city: str) -> str:
        """Look up the weather for a city."""
        calls.append(city)
        return f"weather in {city}"

    return FunctionTool(lookup_weather), calls


def test_google_adk_governance_path_is_wired() -> None:
    """Offline: the SDK's Google ADK patch installs and honours a deny decision.

    The floor under the live path: the real ``GoogleADKPatch`` wraps a concrete
    ADK tool's ``run_async`` so it routes through an interceptor's
    ``check_tool_start`` and *raises* on a ``deny`` before the tool body runs. A
    stub interceptor proves the patch honours the decision contract with no
    toolchain, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.google_adk.patch import GoogleADKPatch
    from agent_assembly.exceptions import PolicyViolationError

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    tool, calls = _build_weather_tool()
    patch = GoogleADKPatch(callback_handler=_DenyInterceptor(), process_agent_id=PROCESS_AGENT_ID)
    assert patch.apply() is True, "Google ADK tool hook did not install"
    try:
        with pytest.raises(PolicyViolationError):
            asyncio.run(tool.run_async(args={"city": "paris"}, tool_context=None))
        assert calls == [], "deny decision let the tool body execute"
    finally:
        patch.revert()


def test_google_adk_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real ADK tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, applies
    the real ``GoogleADKPatch`` so an ADK ``FunctionTool``'s ``run_async`` routes
    through ``check_tool_start`` → live runtime ``query_policy``, then awaits that
    patched hook directly — the real ``Google ADK → SDK adapter → aa-ffi →
    aa-runtime`` path a model-chosen tool call takes. The live runtime answers
    ``allow`` (the fixture runtime runs policy-disabled), so the tool executes: we
    assert its observable side effect (the tool ran) and its output, proving
    enforcement let an allowed call through rather than the call merely not being
    intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.google_adk.patch import GoogleADKPatch

    interceptor = live_runtime_interceptor(live_runtime)
    tool, calls = _build_weather_tool()
    patch = GoogleADKPatch(callback_handler=interceptor, process_agent_id=PROCESS_AGENT_ID)
    assert patch.apply() is True, "Google ADK tool hook did not install"
    try:
        output = asyncio.run(tool.run_async(args={"city": "paris"}, tool_context=None))
        assert calls == ["paris"], "allowed Google ADK tool did not execute under live governance"
        assert output == "weather in paris"
    finally:
        patch.revert()


def test_google_adk_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
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
# resolved), drop this strict xfail and assert the denied tool is blocked.
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)
def test_google_adk_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied ADK tool is blocked end-to-end (strict-xfail).

    The load-bearing enforcement assertion for Google ADK: with a policy that
    denies the tool, awaiting the patched ``run_async`` against the live runtime
    must raise ``PolicyViolationError`` before the tool body runs. It cannot pass
    today — the fixture runtime runs policy-disabled and the SDK's full deny wiring
    is unshipped (AAASM-3021), so the runtime answers ``allow`` and the tool runs.
    Pinned ``strict=True`` so the day enforcement works it XPASSes and the strict
    marker fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.google_adk.patch import GoogleADKPatch
    from agent_assembly.exceptions import PolicyViolationError

    interceptor = live_runtime_interceptor(live_runtime)
    tool, calls = _build_weather_tool()
    patch = GoogleADKPatch(callback_handler=interceptor, process_agent_id=PROCESS_AGENT_ID)
    assert patch.apply() is True, "Google ADK tool hook did not install"
    try:
        with pytest.raises(PolicyViolationError):
            asyncio.run(tool.run_async(args={"city": "secret"}, tool_context=None))
        assert calls == [], "deny path let the tool body execute"
    finally:
        patch.revert()
