"""Verify the ``live_runtime`` fixture starts a real aa-runtime and tears down.

These tests build ``aa-runtime`` from the core monorepo source and run it as
an out-of-process sidecar listening on a Unix domain socket — the real
SDK→core endpoint. They skip cleanly when the build toolchain (``cargo`` /
``protoc``) is unavailable. This is the reachability floor the SDK-FFI test
(``test_sdk_runtime.py``) sits on top of.
"""

from __future__ import annotations

import socket

import pytest

from tests.live.runtime import LiveRuntime

pytestmark = pytest.mark.live


def test_live_runtime_binds_its_uds(live_runtime: LiveRuntime) -> None:
    """The fixture yields a runtime whose UDS accepts a connection."""
    assert live_runtime.socket_path.name == f"aa-runtime-{live_runtime.agent_id}.sock"
    assert live_runtime.socket_path.exists()
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        sock.connect(str(live_runtime.socket_path))  # connecting proves the IPC server is up


def test_live_runtime_tears_down_cleanly(core_runtime_binary) -> None:  # noqa: ANN001
    """After stop(), the socket is removed and the process is reaped."""
    runtime = LiveRuntime(core_runtime_binary)
    runtime.start()
    runtime.await_ready()
    socket_path = runtime.socket_path
    assert socket_path.exists()

    runtime.stop()

    # The runtime removes its own socket on a clean shutdown.
    assert not socket_path.exists()

    # stop() is idempotent.
    runtime.stop()
