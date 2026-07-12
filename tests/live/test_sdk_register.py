"""Live smoke: the Python SDK's HTTP ``GatewayClient`` against ``aa-gateway``.

SUPERSEDED (AAASM-2989): the SDK's hot-path events do *not* travel over HTTP to
the gateway — they go ``SDK → aa-ffi → aa-runtime`` over a Unix socket. That
real path is now covered by ``test_sdk_runtime.py``; this module is kept only as
a record of the deviant HTTP→gateway probe and its known transport gap, not as
the SDK→core verification.

This builds and runs ``aa-gateway`` from core source (via the ``live_gateway``
fixture) and drives the SDK's HTTP control-plane ``GatewayClient`` at it. It
skips cleanly when the SDK or the build toolchain is unavailable.

The registration step is wired honestly against the transport gap recorded in
``verification-reports/AAASM-2985-sdk-transport-investigation.md``: the SDK's
``GatewayClient`` speaks HTTP/REST, but the running gateway serves gRPC or an
HTTP surface that does not mount the SDK's REST routes (those live in ``aa-api``,
a library-only crate with no binary). So that test is marked
``xfail(strict=True)`` against blocking ticket AAASM-4447: it never produces a
false green, and the day a REST front door exists it ``XPASS``es and strict mode
fails the run — forcing the marker's removal rather than letting the fix vanish.
"""

from __future__ import annotations

import asyncio
import socket

import pytest

from tests.live.gateway import LiveGateway
from tests.live.sdk_client import make_sdk_client, sdk_available

pytestmark = pytest.mark.live


def _require_sdk() -> None:
    """Skip the calling test when the Python SDK is not importable."""
    if not sdk_available():
        pytest.skip(
            "Python SDK (agent_assembly) is not installed — "
            "install it from ../python-sdk or PyPI 'agent-assembly' to run this test"
        )


def test_sdk_can_reach_live_gateway(live_gateway: LiveGateway) -> None:
    """The SDK can be configured against the live gateway, which is reachable.

    Unconditional once the SDK is present: builds a real ``GatewayClient``
    pointed at the fixture endpoint and proves the gateway accepts a TCP
    connection on its port. This must pass — it is the reachability floor
    that the (xfail) registration test sits on top of.
    """
    _require_sdk()

    client = make_sdk_client(live_gateway, agent_id="live-smoke-agent")
    try:
        # Plain http:// is intentional: the fixture gateway listens on a
        # 127.0.0.1 loopback port for the duration of this test only, so there
        # is no remote transport to encrypt (S5332).
        assert client.gateway_url == f"http://{live_gateway.endpoint}"
        with socket.create_connection(("127.0.0.1", live_gateway.port), timeout=2):
            pass  # a successful connect proves the listener is up
    finally:
        client.close()


@pytest.mark.xfail(
    reason=(
        "Transport gap (AAASM-4447, first diagnosed as AAASM-2985): the SDK "
        "speaks HTTP/REST but the running aa-gateway serves gRPC / an HTTP "
        "surface without the SDK's REST routes; those routes live in aa-api "
        "which has no binary. See "
        "verification-reports/AAASM-2985-sdk-transport-investigation.md."
    ),
    strict=True,
    raises=Exception,
)
def test_sdk_registers_agent_against_live_gateway(live_gateway: LiveGateway) -> None:
    """Drive the real SDK ``register_agent()`` against the live gateway.

    Expected to fail until an HTTP/REST front door for the SDK exists
    (AAASM-4447; see the investigation note). ``strict=True`` is the forcing
    function the AAASM-4477 audit adds: the assertion still fails today so it
    xfails green, but the day AAASM-4447 lands the call succeeds, the test
    ``XPASS``es, and strict mode turns that unexpected pass into a **failure** —
    forcing this marker's removal instead of letting a silent fix go unnoticed
    (the exact disappearance AAASM-2985/2989/3000 suffered).
    """
    _require_sdk()

    client = make_sdk_client(live_gateway, agent_id="live-smoke-agent")
    try:
        result = asyncio.run(client.register_agent())
        assert isinstance(result, dict)
    finally:
        client.close()
