"""Live smoke: register an agent with the Python SDK against ``aa-gateway``.

This builds and runs ``aa-gateway`` from core source (via the
``live_gateway`` fixture) and drives the *real* installed Python SDK
(``agent_assembly``) at it. It skips cleanly when the SDK or the build
toolchain is unavailable.

The registration step is wired honestly against the transport gap
recorded in
``verification-reports/AAASM-2985-sdk-transport-investigation.md``: the
SDK speaks HTTP/REST, but the running gateway serves gRPC (the
fixture's ``legacy-grpc`` mode) or an HTTP surface that does not mount
the SDK's REST routes — and those routes live in ``aa-api``, a
library-only crate with no binary. Until a REST front door exists,
``register_agent()`` cannot succeed, so that test is marked ``xfail``
(``strict=False``): it never produces a false green, and it will surface
as ``XPASS`` the day the gap is closed — the signal to harden it.
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
        assert client.gateway_url == f"http://{live_gateway.endpoint}"
        with socket.create_connection(("127.0.0.1", live_gateway.port), timeout=2):
            pass  # a successful connect proves the listener is up
    finally:
        client.close()


@pytest.mark.xfail(
    reason=(
        "Transport gap (AAASM-2985): the SDK speaks HTTP/REST but the running "
        "aa-gateway serves gRPC / an HTTP surface without the SDK's REST routes; "
        "those routes live in aa-api which has no binary. See "
        "verification-reports/AAASM-2985-sdk-transport-investigation.md."
    ),
    strict=False,
    raises=Exception,
)
def test_sdk_registers_agent_against_live_gateway(live_gateway: LiveGateway) -> None:
    """Drive the real SDK ``register_agent()`` against the live gateway.

    Expected to fail until an HTTP/REST front door for the SDK exists
    (see the investigation note). ``xfail(strict=False)`` keeps this an
    honest signal: never a fabricated pass, and an ``XPASS`` flag the day
    the gap closes — the cue to drop the marker and assert hard.
    """
    _require_sdk()

    client = make_sdk_client(live_gateway, agent_id="live-smoke-agent")
    try:
        result = asyncio.run(client.register_agent())
        assert isinstance(result, dict)
    finally:
        client.close()
