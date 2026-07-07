"""Behavioral: the Python SDK fails *open* when no core/gateway is reachable.

This asserts the python-sdk's **designed** security posture when there is
**no governance gateway running** — the fail-open contract. We deliberately
start no gateway (that is the whole point) and prove that bringing the SDK up
never blocks the agent: a governed session initializes and proceeds.

This contract has a precondition: **no native ``_core`` extension is present**.
With no native authority to consult there is nothing to fail closed *to*, so
``init_assembly`` fails open in every enforcement mode. When ``_core`` IS
installed (the strict / ``live``-CI posture) the SDK gains a native authority
and ``enforce`` fails *closed* by design — so the ``enforce`` fail-open
assertion skips in that environment rather than reporting a false failure
(AAASM-3697).

Why ``init_assembly`` is the assertion boundary
-----------------------------------------------
The fail-open contract is about whether the agent is *allowed to proceed*
when governance is unreachable. In the python-sdk that decision is made at
the ``init_assembly(...)`` boundary, not at the per-action RPC:

* ``init_assembly(gateway_url=<dead>, mode="sdk-only", enforcement_mode=...)``
  constructs a lazy ``GatewayClient`` (no socket opened yet) and registers
  framework adapters. It returns a usable :class:`AssemblyContext` **without
  raising** even though nothing is listening — the agent proceeds. That is
  fail-open: governance being absent does not stop the workload.

* An explicit per-action RPC on the ``GatewayClient`` (e.g.
  ``dispatch_tool``) is a *transport* call: against a dead endpoint it raises
  ``GatewayError``. It does **not** itself implement fail-open, so we do not
  pretend it does — see
  :func:`test_explicit_policy_rpc_is_transport_not_failopen`, which documents
  the boundary rather than faking an allow.

The SDK is an optional dependency of this verification repo (install it from
``../python-sdk`` or PyPI ``agent-assembly``); every test SKIPs cleanly when
``agent_assembly`` is not importable. No gateway is ever started here.
"""

from __future__ import annotations

import importlib.util
import socket
from collections.abc import Iterator

import pytest

COMPONENT = "python-sdk"


def _sdk_available() -> bool:
    """Return True when the Python SDK package can be imported."""
    return importlib.util.find_spec("agent_assembly") is not None


def _native_core_available() -> bool:
    """Return True when the native ``agent_assembly._core`` extension is present.

    The "without core" precondition of this whole module is that the native
    runtime is **absent**: with no native authority to consult, ``init_assembly``
    fails *open* in every enforcement mode. When ``_core`` IS installed (the
    strict / ``live``-CI posture) the SDK gains a native authority and
    ``enforce`` mode fails *closed* by design (``runtime_interceptor`` —
    "native present but runtime unreachable → deny under enforce"), so
    ``init_assembly(enforce)`` raises against a dead gateway. The fail-open
    assertions below are therefore only valid when this returns ``False``.
    """
    return importlib.util.find_spec("agent_assembly._core") is not None


def _require_sdk() -> None:
    """Skip the calling test when the Python SDK is not installed."""
    if not _sdk_available():
        pytest.skip(
            f"[{COMPONENT}] Python SDK (agent_assembly) is not installed — "
            "install it from ../python-sdk or PyPI 'agent-assembly' to run this test"
        )


def _require_no_native_core() -> None:
    """Skip the calling test when the native ``_core`` extension is installed.

    The fail-open assertion for ``enforce`` mode only holds when there is no
    native authority. With ``_core`` present, ``enforce`` correctly fails closed,
    so running the fail-open assertion there would be a false failure — the
    harness must be honest about its "without core" precondition rather than
    asserting fail-open in an environment where fail-closed is correct.
    """
    if _native_core_available():
        pytest.skip(
            f"[{COMPONENT}] native agent_assembly._core is installed — the "
            "fail-open-under-enforce assertion requires the native core to be "
            "absent (with native present, enforce mode fails closed by design)"
        )


def _dead_gateway_url() -> str:
    """Return an ``http://127.0.0.1:<port>`` URL where nothing listens.

    Binds an ephemeral port and immediately releases it, so the port is
    valid-but-closed: any connection attempt is refused. This makes the
    "no core / no gateway" condition deterministic rather than relying on a
    hard-coded port that might happen to be in use.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    finally:
        sock.close()
    return f"http://127.0.0.1:{port}"


@pytest.fixture
def no_gateway_env(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Yield a dead gateway URL with the SDK env resolver neutralised.

    Clears ``AAASM_GATEWAY_URL`` / ``AAASM_API_KEY`` so the resolver cannot
    discover some other endpoint, and hands back an explicit dead URL to pass
    to ``init_assembly`` — guaranteeing the "no core reachable" condition.
    """
    monkeypatch.delenv("AAASM_GATEWAY_URL", raising=False)
    monkeypatch.delenv("AAASM_API_KEY", raising=False)
    yield _dead_gateway_url()


def _init_without_gateway(gateway_url: str, enforcement_mode: str):  # noqa: ANN202
    """Drive a governed-session init pointed at an unreachable gateway.

    Uses ``mode="sdk-only"`` so no eBPF/proxy network layer is started and the
    call stays hermetic. Returns the live ``AssemblyContext`` — the caller is
    responsible for ``shutdown()``.
    """
    from agent_assembly import init_assembly  # noqa: PLC0415 — optional dep

    return init_assembly(
        gateway_url=gateway_url,
        agent_id=f"failopen-{enforcement_mode}",
        mode="sdk-only",
        enforcement_mode=enforcement_mode,
    )


@pytest.mark.sdk
def test_enforce_mode_proceeds_without_gateway(no_gateway_env: str) -> None:
    """enforce mode, no gateway → the governed session proceeds (fail-open).

    The strongest posture must still come up when governance is unreachable:
    ``init_assembly(enforcement_mode="enforce")`` against a dead endpoint
    returns a usable context **without raising**, so the agent is not blocked.

    Precondition: this fail-open assertion only holds with **no native core**.
    When ``agent_assembly._core`` is installed the SDK has a native authority and
    ``enforce`` fails *closed* by design (init raises against a dead gateway), so
    we skip rather than assert a fail-open that is intentionally not the contract
    in that environment (AAASM-3697).
    """
    _require_sdk()
    _require_no_native_core()

    context = _init_without_gateway(no_gateway_env, "enforce")
    try:
        assert context is not None, (
            f"[{COMPONENT}] init_assembly(enforce) returned no context with no gateway"
        )
        assert not context.is_shutdown, (
            f"[{COMPONENT}] expected a live (non-shutdown) context in enforce mode"
        )
        assert context.client.enforcement_mode == "enforce", (
            f"[{COMPONENT}] enforce posture not recorded on the client: "
            f"{context.client.enforcement_mode!r}"
        )
    finally:
        context.shutdown()


@pytest.mark.sdk
def test_observe_mode_proceeds_without_gateway(no_gateway_env: str) -> None:
    """observe mode, no gateway → the governed session proceeds (fail-open).

    Dry-run posture: with no gateway to record shadow audit events, init must
    still succeed and let the action through.
    """
    _require_sdk()

    context = _init_without_gateway(no_gateway_env, "observe")
    try:
        assert context is not None, (
            f"[{COMPONENT}] init_assembly(observe) returned no context with no gateway"
        )
        assert not context.is_shutdown, (
            f"[{COMPONENT}] expected a live (non-shutdown) context in observe mode"
        )
        assert context.client.enforcement_mode == "observe", (
            f"[{COMPONENT}] observe posture not recorded on the client: "
            f"{context.client.enforcement_mode!r}"
        )
    finally:
        context.shutdown()


@pytest.mark.sdk
def test_disabled_mode_proceeds_without_gateway(no_gateway_env: str) -> None:
    """disabled mode, no gateway → the governed session proceeds (no-op).

    Policy evaluation is skipped entirely; init is a no-op governance-wise and
    must never raise just because no gateway is present.
    """
    _require_sdk()

    context = _init_without_gateway(no_gateway_env, "disabled")
    try:
        assert context is not None, (
            f"[{COMPONENT}] init_assembly(disabled) returned no context with no gateway"
        )
        assert not context.is_shutdown, (
            f"[{COMPONENT}] expected a live (non-shutdown) context in disabled mode"
        )
        assert context.client.enforcement_mode == "disabled", (
            f"[{COMPONENT}] disabled posture not recorded on the client: "
            f"{context.client.enforcement_mode!r}"
        )
    finally:
        context.shutdown()


@pytest.mark.sdk
def test_explicit_policy_rpc_is_transport_not_failopen(no_gateway_env: str) -> None:
    """Document the boundary: the per-action RPC is transport, not fail-open.

    Fail-open lives at the ``init_assembly`` boundary (the three tests above),
    **not** in the explicit per-action RPC. The current ``GatewayClient`` surface
    exposes per-action transport methods (``report_edge`` / ``dispatch_tool``);
    there is no client-side ``check``/policy method — those decisions are made
    server-side over the native gRPC path. We probe ``dispatch_tool``: against a
    dead gateway it raises ``GatewayError`` — a transport failure, not a
    governance allow. We assert that honestly rather than pretending the RPC
    returns an allow, so this file never fabricates a fail-open it cannot show.
    """
    _require_sdk()

    import asyncio  # noqa: PLC0415 — local to keep import surface minimal

    from agent_assembly.client.gateway import GatewayClient  # noqa: PLC0415 — optional dep
    from agent_assembly.exceptions import GatewayError  # noqa: PLC0415 — optional dep

    client = GatewayClient(gateway_url=no_gateway_env, agent_id="failopen-rpc-probe")
    try:
        # Extract the coroutine to ensure only the throwing call is in raises block
        coro = client.dispatch_tool("tool.call", {})  # NOSONAR — setup before raises
        with pytest.raises(GatewayError):
            asyncio.run(coro)
    finally:
        client.close()
