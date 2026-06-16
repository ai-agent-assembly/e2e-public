"""Behavioral: the Python SDK *enforces* a deny decision before a tool runs.

This is the positive mirror of :mod:`tests.behavioral.test_python_without_core`
(which locks in fail-*open* when no core is reachable). Here we assert the
**enforcement-decision contract**: when governance returns a synchronous
``deny``, the governed tool is blocked *before* it executes; when governance
returns ``allow`` (or a ``pending`` that is subsequently approved) the action
proceeds.

Where the decision is made
--------------------------
In the python-sdk the per-action allow/deny decision is applied in the
framework-adapter callback, not in the gateway transport call. For LangChain
that callback is
:meth:`agent_assembly.adapters.langchain.callback_handler.AssemblyCallbackHandler.on_tool_start`:

* it asks its *interceptor* for a decision via ``check_tool_start(...)``;
* a ``deny`` raises :class:`agent_assembly.exceptions.ToolExecutionBlockedError`
  (the tool never runs);
* a ``pending`` waits for approval (``wait_for_tool_approval``) and blocks
  unless the approval resolves to ``allow``;
* an ``allow`` (and a missing ``check_tool_start``) falls through and the tool
  proceeds.

``AssemblyCallbackHandler`` and ``ToolExecutionBlockedError`` are both part of
the SDK's public surface (``agent_assembly.adapters.langchain`` re-exports the
handler; ``ToolExecutionBlockedError`` is a top-level ``agent_assembly`` export),
so this test drives the real decision logic through the public API with a
plain interceptor object — it does **not** reach into private/test-only
internals to fabricate a green.

The AAASM-3021 wiring gap (honest boundary)
-------------------------------------------
In *production* this enforcement is presently dead code: ``init_assembly``
hands adapters the ``GatewayClient``, which has **no** ``check_tool_start``
method, so the callback falls through to *allow* regardless of policy. That
end-to-end gap is tracked by **AAASM-3021**. We document it faithfully with an
``xfail(strict=False)`` cell that exercises a ``GatewayClient``-shaped
interceptor (no ``check_tool_start``) and shows the deny is silently dropped —
rather than pretending it is enforced.

The true *live-core* deny (a running ``aa-core`` plus a deny-policy fixture)
is out of scope for this in-process behavioral test: it is gated on AAASM-3021
landing the wiring and on a deny-policy live fixture, and is reoriented under
**AAASM-2989**. A ``skip`` placeholder marks that future coverage.

The SDK is an optional dependency of this verification repo (install it from
``../python-sdk`` or PyPI ``agent-assembly``); every test SKIPs cleanly when
``agent_assembly`` is not importable. No gateway is ever started here.
"""

from __future__ import annotations

import importlib.util
from typing import Any
from uuid import uuid4

import pytest

COMPONENT = "python-sdk"


def _sdk_available() -> bool:
    """Return True when the Python SDK package can be imported."""
    return importlib.util.find_spec("agent_assembly") is not None


def _require_sdk() -> None:
    """Skip the calling test when the Python SDK is not installed."""
    if not _sdk_available():
        pytest.skip(
            f"[{COMPONENT}] Python SDK (agent_assembly) is not installed — "
            "install it from ../python-sdk or PyPI 'agent-assembly' to run this test"
        )


class _DecisionInterceptor:
    """Minimal governance interceptor returning a fixed ``check_tool_start`` decision.

    Mirrors the duck-typed contract ``AssemblyCallbackHandler`` expects: a
    ``check_tool_start(**kwargs)`` returning ``"allow"``/``"deny"``/``"pending"``
    or a mapping ``{"status": ..., "reason": ...}``. Optionally supplies a
    ``wait_for_tool_approval`` result for the ``pending`` path.
    """

    def __init__(self, decision: Any, approval: Any = None) -> None:
        self._decision = decision
        self._approval = approval

    def check_tool_start(self, **_kwargs: Any) -> Any:
        return self._decision

    def wait_for_tool_approval(self, **_kwargs: Any) -> Any:
        return self._approval


class _GatewayShapedInterceptor:
    """An interceptor with **no** ``check_tool_start`` — the production shape.

    ``init_assembly`` hands adapters the ``GatewayClient``, which exposes no
    ``check_tool_start``. ``AssemblyCallbackHandler`` therefore falls through to
    *allow*. This object reproduces that shape to demonstrate the AAASM-3021
    gap without depending on the heavyweight real client.
    """


def _make_handler(interceptor: Any):  # noqa: ANN202 — return type is SDK-internal
    """Construct an ``AssemblyCallbackHandler`` over ``interceptor`` (public API)."""
    from agent_assembly.adapters.langchain.callback_handler import (  # noqa: PLC0415 — optional dep
        AssemblyCallbackHandler,
    )

    return AssemblyCallbackHandler(interceptor)


def _start_tool(handler: Any, *, tool: str = "shell", arg: str = "rm -rf /") -> None:
    """Drive ``on_tool_start`` for a governed tool call (the enforcement point)."""
    handler.on_tool_start({"name": tool}, arg, run_id=uuid4())


@pytest.mark.sdk
def test_deny_decision_blocks_tool_before_execution() -> None:
    """A synchronous ``deny`` blocks the tool before it runs (positive enforcement).

    This is the core positive-enforcement assertion: the public
    ``AssemblyCallbackHandler``, given an interceptor that denies the action,
    raises ``ToolExecutionBlockedError`` from ``on_tool_start`` — i.e. the
    governed tool is stopped *before* execution rather than allowed through.
    """
    _require_sdk()

    from agent_assembly import ToolExecutionBlockedError  # noqa: PLC0415 — optional dep

    handler = _make_handler(_DecisionInterceptor("deny"))
    with pytest.raises(ToolExecutionBlockedError):
        _start_tool(handler)


@pytest.mark.sdk
def test_deny_decision_propagates_policy_reason() -> None:
    """A ``deny`` mapping surfaces its policy ``reason`` to the caller.

    Beyond the raise, the operator-facing reason from the decision must reach
    the exception so a blocked action is explainable, not opaque.
    """
    _require_sdk()

    from agent_assembly import ToolExecutionBlockedError  # noqa: PLC0415 — optional dep

    reason = "blocked by policy: destructive_shell"
    handler = _make_handler(_DecisionInterceptor({"status": "deny", "reason": reason}))
    with pytest.raises(ToolExecutionBlockedError, match=reason):
        _start_tool(handler)


@pytest.mark.sdk
def test_allow_decision_proceeds() -> None:
    """An ``allow`` decision lets the governed tool proceed (no raise).

    The complement of the deny case: positive enforcement must *not* over-block.
    An allowed action returns from ``on_tool_start`` without raising.
    """
    _require_sdk()

    handler = _make_handler(_DecisionInterceptor("allow"))
    # Must not raise — an allowed tool proceeds.
    _start_tool(handler, tool="calculator", arg="2 + 2")


@pytest.mark.sdk
def test_pending_then_approved_proceeds() -> None:
    """A ``pending`` decision that is later approved proceeds (no raise).

    The approval path is part of the enforcement contract: when governance
    defers (``pending``) and the approval resolves to ``allow``, the tool runs.
    """
    _require_sdk()

    handler = _make_handler(_DecisionInterceptor("pending", approval="allow"))
    # Approval granted → no raise.
    _start_tool(handler, tool="calculator", arg="2 + 2")


@pytest.mark.sdk
def test_pending_without_approval_blocks() -> None:
    """A ``pending`` decision with no granted approval blocks the tool.

    Fail-closed on the deferral path: if approval never resolves to ``allow``
    (here, the approver returns ``deny``), the governed tool is blocked.
    """
    _require_sdk()

    from agent_assembly import ToolExecutionBlockedError  # noqa: PLC0415 — optional dep

    handler = _make_handler(_DecisionInterceptor("pending", approval="deny"))
    with pytest.raises(ToolExecutionBlockedError):
        _start_tool(handler)


@pytest.mark.sdk
@pytest.mark.xfail(
    strict=False,
    reason=(
        "AAASM-3021: init_assembly wires adapters with the GatewayClient, which "
        "has no check_tool_start, so on_tool_start falls through to allow and the "
        "deny is never enforced end-to-end. This cell pins the gap until the "
        "production wiring routes a real deny-capable interceptor."
    ),
)
def test_production_wiring_enforces_deny_xfail() -> None:
    """XFAIL placeholder for the production wiring gap (AAASM-3021).

    The Tier-A cells above prove the *decision logic* enforces a deny via the
    public ``AssemblyCallbackHandler``. This cell asserts the stronger property
    that the *production-shaped* interceptor (no ``check_tool_start`` — the
    ``GatewayClient`` shape ``init_assembly`` actually injects) would also block
    a tool. It currently falls through to allow, so the expected raise never
    happens and the test xfails — faithfully marking the AAASM-3021 gap rather
    than faking a pass.
    """
    _require_sdk()

    from agent_assembly import ToolExecutionBlockedError  # noqa: PLC0415 — optional dep

    handler = _make_handler(_GatewayShapedInterceptor())
    with pytest.raises(ToolExecutionBlockedError):
        _start_tool(handler)


@pytest.mark.sdk
@pytest.mark.skip(
    reason=(
        "Live-core deny is out of scope here: it requires a running aa-core with "
        "a deny-policy fixture AND the AAASM-3021 wiring to route per-action "
        "decisions through the adapter. Tracked alongside AAASM-2989 "
        "(live-at-runtime reorientation); see module docstring."
    )
)
def test_live_core_deny_blocks_governed_tool() -> None:
    """Placeholder for the end-to-end live-core deny (out of scope; see docstring)."""
    raise AssertionError("unreachable: live-core deny is a skipped placeholder")
