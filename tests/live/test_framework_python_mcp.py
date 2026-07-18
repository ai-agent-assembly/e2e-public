"""Live framework smoke: a real **MCP** client through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests). Unlike the callback /
patch adapters that wrap an agent framework, the SDK's MCP adapter governs the
**Model Context Protocol** tool-call path: it monkey-patches
``mcp.ClientSession.call_tool`` (see ``agent_assembly.adapters.mcp.patch``) so a
governed ``call_tool`` consults ``check_tool_start`` before the request reaches
the server. This test stands up a **real in-process MCP server** (a ``FastMCP``
exposing one tool) connected to a **real ``ClientSession``** over MCP's in-memory
transport, applies the genuine ``MCPClientPatch``, and drives an actual governed
``call_tool`` against a live ``aa-runtime`` — the production
``MCP client → SDK adapter → aa-ffi → aa-runtime`` governance path. Nothing here
is mocked: a real client speaks the MCP protocol to a real server, and the
governance decision comes from a live runtime, not a stub.

The **highlight governance functions** this exercises (per the AAASM-3525 plan):

* **Pre-execution allow enforcement** — the patched ``call_tool`` asks the live
  runtime ``query_policy`` (via the interceptor's ``check_tool_start``) whether
  the tool may run; an ``allow`` lets the real server tool execute (asserted by
  the tool's observable side effect + the MCP result content).
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport, the path
  the SDK uses to record audit events.

The MCP ``call_tool`` path is ``async`` (the patch installs an async wrapper), so
each cell drives it with ``asyncio.run`` rather than a pytest-asyncio fixture —
this repo's live suite carries no asyncio plugin, and a self-contained
``asyncio.run`` keeps the cell honest without adding a dependency.

The **deny path** (a denied tool actually blocked end-to-end) is a ``strict=True``
xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) — see
:data:`tests.live.framework_live.DENY_XFAIL_REASON`.

Layers, by what they need:

* **offline** — the SDK adapter patch + a real MCP client/server wire up and
  honour a stub decision with no toolchain (``test_mcp_governance_path_is_wired``).
* **allow path (live)** — needs ``cargo``/``protoc`` (to build ``aa-runtime``),
  the SDK's compiled ``_core``, and ``mcp``; skips cleanly otherwise.
* **deny path (live, strict-xfail)** — same prerequisites, pinned xfail.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import pytest

from tests.live.framework_live import (
    DENY_XFAIL_REASON,
    live_runtime_interceptor,
    require_framework,
    require_native_core,
)
from tests.live.runtime import LiveRuntime
from tests.live.runtime_client import import_native_core, make_audit_entry_payload

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: MCP's importable package name (the SDK adapter's ``get_framework_name`` ↔ "mcp").
FRAMEWORK_IMPORT = "mcp"
FRAMEWORK_PACKAGE = "mcp (the Model Context Protocol Python SDK)"

#: The single tool name the in-process MCP server exposes.
TOOL_NAME = "echo"


def _build_mcp_server():  # noqa: ANN202 — returns a FastMCP server
    """Return a real ``FastMCP`` server exposing one observable tool.

    The ``echo`` tool appends to a list it closes over, so a test can assert it
    actually *ran* (the allow decision let the ``call_tool`` request through) as
    opposed to being blocked before the server saw it. This is a genuine MCP
    server — the same low-level ``Server`` a stdio/SSE deployment would run — not
    a stand-in.
    """
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("aaitest-mcp-smoke")
    calls: list[str] = []

    @server.tool()
    def echo(text: str) -> str:
        """Echo back the supplied text."""
        calls.append(text)
        return f"echoed: {text}"

    return server, calls


@asynccontextmanager
async def _connected_session(server: Any) -> AsyncIterator[Any]:
    """Yield a real, initialized ``ClientSession`` connected to *server*.

    Uses ``mcp``'s in-memory transport helper, which wires a real client session
    to a real server over connected memory streams — a genuine MCP protocol
    handshake (``initialize`` + ``call_tool``) with no network, exactly what the
    SDK patch intercepts in a deployed MCP client.
    """
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(server) as session:
        await session.initialize()
        yield session


def test_mcp_governance_path_is_wired() -> None:
    """Offline: the SDK's MCP patch governs a real ``call_tool`` and honours deny.

    The floor under the live path: the real ``MCPClientPatch`` wraps the genuine
    ``ClientSession.call_tool`` so a ``deny`` decision raises
    ``MCPToolBlockedError`` *before* the server tool runs. A stub interceptor
    proves the patch honours the decision contract against a real client/server
    with no toolchain, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.mcp.patch import MCPClientPatch
    from agent_assembly.exceptions import MCPToolBlockedError

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    async def _drive() -> None:
        server, calls = _build_mcp_server()
        patch = MCPClientPatch(callback_handler=_DenyInterceptor(), process_agent_id="aaitest-mcp")
        assert patch.apply() is True, "MCP ClientSession.call_tool hook did not install"
        try:
            async with _connected_session(server) as session:
                with pytest.raises(MCPToolBlockedError):
                    await session.call_tool(TOOL_NAME, {"text": "hi"})
            assert calls == [], "deny path let the MCP server tool execute"
        finally:
            patch.revert()

    asyncio.run(_drive())


def test_mcp_allow_path_runs_tool_through_live_runtime(live_runtime: LiveRuntime) -> None:
    """Allow path: a real MCP tool runs governed by a live-runtime decision.

    Builds the production governance interceptor against the live runtime, applies
    the real ``MCPClientPatch``, then issues a genuine ``ClientSession.call_tool``
    against a real in-process MCP server — the real
    ``MCP client → SDK adapter → aa-ffi → aa-runtime`` path. The live runtime
    answers ``query_policy`` with ``allow`` (the fixture runtime runs
    policy-disabled), so the server tool executes: we assert its observable side
    effect (the tool ran) and the MCP result content, proving enforcement let an
    allowed call through rather than the call merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.mcp.patch import MCPClientPatch

    interceptor = live_runtime_interceptor(live_runtime)

    async def _drive() -> tuple[list[str], str]:
        server, calls = _build_mcp_server()
        patch = MCPClientPatch(callback_handler=interceptor, process_agent_id="aaitest-mcp")
        assert patch.apply() is True, "MCP ClientSession.call_tool hook did not install"
        try:
            async with _connected_session(server) as session:
                result = await session.call_tool(TOOL_NAME, {"text": "weather"})
            text = "".join(block.text for block in result.content if hasattr(block, "text"))
            return calls, text
        finally:
            patch.revert()

    calls, text = asyncio.run(_drive())

    assert calls == ["weather"], "allowed MCP tool did not execute under live governance"
    assert text == "echoed: weather"


def test_mcp_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
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
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)  # AAASM-3172
def test_mcp_deny_path_blocks_tool_through_live_runtime(live_runtime: LiveRuntime) -> None:
    """Deny path: a denied MCP tool is blocked end-to-end (strict-xfail).

    The load-bearing enforcement assertion for MCP: with a policy that denies the
    tool, issuing ``call_tool`` through the real patched ``ClientSession`` against
    the live runtime must raise ``MCPToolBlockedError`` before the server tool
    runs. It cannot pass today — the fixture runtime runs policy-disabled and the
    SDK's full deny wiring is unshipped (AAASM-3021), so the runtime answers
    ``allow`` and the tool runs. Pinned ``strict=True`` so the day enforcement
    works it XPASSes and the strict marker fails the suite — the cue to flip
    (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.mcp.patch import MCPClientPatch
    from agent_assembly.exceptions import MCPToolBlockedError

    interceptor = live_runtime_interceptor(live_runtime)

    async def _drive() -> list[str]:
        server, calls = _build_mcp_server()
        patch = MCPClientPatch(callback_handler=interceptor, process_agent_id="aaitest-mcp")
        assert patch.apply() is True, "MCP ClientSession.call_tool hook did not install"
        try:
            async with _connected_session(server) as session:
                with pytest.raises(MCPToolBlockedError):
                    await session.call_tool(TOOL_NAME, {"text": "secret"})
            return calls
        finally:
            patch.revert()

    calls = asyncio.run(_drive())
    assert calls == [], "deny path let the MCP server tool execute"
