"""Spawn and supervise a live ``aa-runtime`` sidecar subprocess.

``LiveRuntime`` launches the built ``aa-runtime`` binary — the always-present
local core the SDKs reach over a Unix domain socket — with an isolated
``$HOME``, a unique agent id, and a free metrics port, waits for its UDS to
accept connections, and terminates the process on ``stop()`` /
context-manager exit.

This is the real SDK→core transport (``SDK → aa-ffi → aa-runtime`` over the
UDS at ``/tmp/aa-runtime-<agent_id>.sock``), as opposed to the deviant
SDK→gateway HTTP path. ``aa-runtime`` is configured entirely by environment
variables — there are no CLI flags.
"""

from __future__ import annotations

import socket
import uuid


def unique_agent_id(prefix: str = "aaitest") -> str:
    """Return a collision-resistant agent id for socket isolation.

    ``aa-runtime`` binds its UDS at ``/tmp/aa-runtime-<agent_id>.sock``, so a
    unique id per launched runtime keeps concurrent instances (and leftover
    sockets from crashed runs) from colliding. The short uuid suffix is ample
    for test isolation while keeping the socket path readable.
    """
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def free_metrics_port() -> int:
    """Return a currently-free TCP port for the runtime's metrics server.

    ``aa-runtime`` serves health/metrics on ``AA_METRICS_ADDR`` (default
    ``0.0.0.0:8080``); two instances would collide on the default, so each
    ``LiveRuntime`` binds a kernel-assigned loopback port instead. There is an
    inherent release-to-rebind race, but it is small enough for test use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
