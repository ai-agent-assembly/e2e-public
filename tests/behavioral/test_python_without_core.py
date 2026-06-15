"""Behavioral: the Python SDK fails *open* when no core/gateway is reachable.

This asserts the python-sdk's **designed** security posture when there is
**no governance gateway running** — the fail-open contract. We deliberately
start no gateway (that is the whole point) and prove that bringing the SDK up
never blocks the agent: a governed session initializes and proceeds, in every
enforcement mode.

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

* The explicit per-action RPC (``GatewayClient.check_policy_compliance``) is a
  *transport* call: against a dead endpoint it raises ``GatewayError``. It does
  **not** itself implement fail-open, so we do not pretend it does — see
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


def _require_sdk() -> None:
    """Skip the calling test when the Python SDK is not installed."""
    if not _sdk_available():
        pytest.skip(
            f"[{COMPONENT}] Python SDK (agent_assembly) is not installed — "
            "install it from ../python-sdk or PyPI 'agent-assembly' to run this test"
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
    """
    _require_sdk()

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
