"""Spawn and supervise a live ``aa-gateway`` subprocess.

``LiveGateway`` launches the built gateway binary on a free TCP port
with an isolated ``$HOME`` and audit directory, waits for the gRPC
listener to accept connections, and terminates the process on
``stop()`` / context-manager exit.

This mirrors the Rust reference fixture in the monorepo
(``aa-integration-tests/tests/common/live_gateway.rs``).
"""

from __future__ import annotations

import socket
import subprocess
import tempfile
from pathlib import Path

#: Default minimal policy shipped alongside this module.
MINIMAL_POLICY = Path(__file__).parent / "fixtures" / "policies" / "minimal.yaml"


def free_port() -> int:
    """Return a currently-free TCP port on the loopback interface.

    Binds ``127.0.0.1:0`` and reads back the kernel-assigned port. There
    is an inherent race between releasing the probe socket and the
    gateway binding it, but it is small enough for test use.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class LiveGateway:
    """A spawned ``aa-gateway`` process bound to a free loopback port.

    Construct with the built binary path and (optionally) a policy file;
    call :meth:`start` to launch and wait for readiness, :meth:`stop` to
    terminate and clean up. Usable as a context manager.
    """

    def __init__(self, binary: Path, *, policy: Path = MINIMAL_POLICY) -> None:
        self._binary = Path(binary)
        self._policy = Path(policy)
        self._port = free_port()
        self._proc: subprocess.Popen[bytes] | None = None
        self._home: tempfile.TemporaryDirectory[str] | None = None

    @property
    def port(self) -> int:
        """The TCP port the gateway listens on."""
        return self._port

    @property
    def endpoint(self) -> str:
        """The gRPC endpoint as ``"127.0.0.1:<port>"``."""
        return f"127.0.0.1:{self._port}"

    def start(self) -> LiveGateway:
        """Launch the gateway with an isolated HOME/audit dir; return self.

        HOME isolation keeps the spawned gateway's SQLite store, audit
        JSONL, and budget cache inside a temp directory rather than the
        engineer's real ``~/.aa`` / ``~/.aasm``.
        """
        self._home = tempfile.TemporaryDirectory(prefix="live-gateway-home-")
        home_path = Path(self._home.name)
        audit_dir = home_path / "audit"
        audit_dir.mkdir(parents=True, exist_ok=True)

        self._proc = subprocess.Popen(
            [
                str(self._binary),
                "--policy",
                str(self._policy),
                "--listen",
                self.endpoint,
                "--audit-dir",
                str(audit_dir),
            ],
            env={"HOME": str(home_path), "PATH": _inherited_path()},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self


def _inherited_path() -> str:
    """Return the current ``PATH`` so the spawned gateway can find libs."""
    import os

    return os.environ.get("PATH", "")
