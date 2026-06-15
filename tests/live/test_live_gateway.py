"""Verify the ``live_gateway`` fixture starts a real gateway and tears down.

These tests build ``aa-gateway`` from the core monorepo source and run
it as an out-of-process gRPC listener. They skip cleanly when the build
toolchain (``cargo`` / ``protoc``) is unavailable.
"""

from __future__ import annotations

import socket

import pytest

from tests.live.gateway import LiveGateway

pytestmark = pytest.mark.live


def test_live_gateway_is_ready(live_gateway: LiveGateway) -> None:
    """The fixture yields a gateway accepting TCP connections."""
    assert live_gateway.endpoint == f"127.0.0.1:{live_gateway.port}"
    with socket.create_connection(("127.0.0.1", live_gateway.port), timeout=2):
        pass  # a successful connect proves the gRPC listener is up


def test_live_gateway_tears_down_cleanly(core_gateway_binary) -> None:  # noqa: ANN001
    """After stop(), the port is released and the process is reaped."""
    gateway = LiveGateway(core_gateway_binary)
    gateway.start()
    gateway.await_ready()
    port = gateway.port

    gateway.stop()

    # The listener is gone: a fresh bind on the same port now succeeds.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))

    # stop() is idempotent.
    gateway.stop()
