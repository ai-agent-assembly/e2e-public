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

import contextlib
import os
import socket
import subprocess
import tempfile
import time
import uuid
from pathlib import Path


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


class LiveRuntime:
    """A spawned ``aa-runtime`` sidecar listening on its own UDS.

    Construct with the built binary path; call :meth:`start` to launch and
    :meth:`await_ready` to wait for the Unix socket, :meth:`stop` to terminate
    and clean up. Usable as a context manager. Policy enforcement is disabled
    (``AA_POLICY_PATH=""``) so the runtime starts without an on-disk policy —
    this fixture verifies the SDK→runtime transport, not policy decisions.
    """

    def __init__(self, binary: Path, *, agent_id: str | None = None) -> None:
        self._binary = Path(binary)
        self._agent_id = agent_id or unique_agent_id()
        self._socket_path = Path(f"/tmp/aa-runtime-{self._agent_id}.sock")
        self._metrics_port = free_metrics_port()
        self._proc: subprocess.Popen[bytes] | None = None
        self._home: tempfile.TemporaryDirectory[str] | None = None

    @property
    def agent_id(self) -> str:
        """The agent id this runtime was launched with."""
        return self._agent_id

    @property
    def socket_path(self) -> Path:
        """The UDS path the runtime binds (``/tmp/aa-runtime-<agent_id>.sock``)."""
        return self._socket_path

    def start(self) -> LiveRuntime:
        """Launch the runtime with an isolated HOME and a unique UDS; return self.

        ``aa-runtime`` is configured purely via environment: ``AA_AGENT_ID``
        names the socket, ``AA_POLICY_PATH=""`` disables policy, and
        ``AA_METRICS_ADDR`` is pinned to a free loopback port so concurrent
        runtimes do not collide on the default ``:8080``.
        """
        self._home = tempfile.TemporaryDirectory(prefix="live-runtime-home-")
        env = {
            "HOME": self._home.name,
            "PATH": os.environ.get("PATH", ""),
            "AA_AGENT_ID": self._agent_id,
            "AA_POLICY_PATH": "",
            "AA_METRICS_ADDR": f"127.0.0.1:{self._metrics_port}",
        }
        self._proc = subprocess.Popen(
            [str(self._binary)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    def await_ready(self, timeout: float = 30.0) -> None:
        """Block until the runtime's UDS accepts a connection.

        Polls an ``AF_UNIX`` connect to :attr:`socket_path` until it succeeds
        or *timeout* seconds elapse. Raises ``RuntimeError`` if the process
        exits early or the socket never becomes connectable.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(
                    f"aa-runtime exited early (code {self._proc.returncode}) "
                    f"before binding {self._socket_path}"
                )
            if self._socket_path.exists():
                try:
                    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                        sock.settimeout(0.2)
                        sock.connect(str(self._socket_path))
                    return
                except OSError:
                    pass
            time.sleep(0.1)
        raise RuntimeError(
            f"aa-runtime did not start accepting connections on "
            f"{self._socket_path} within {timeout:.0f}s"
        )

    def stop(self) -> None:
        """Terminate the runtime, unlink its socket, and remove the temp HOME.

        Sends ``terminate`` (SIGTERM), waits briefly, then ``kill`` if needed.
        The runtime removes its own socket on a clean shutdown; the explicit
        unlink is a safety net for a killed process. Idempotent.
        """
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        # The runtime unlinks its own socket on a clean exit; this is a safety
        # net for a killed process that never got to clean up.
        with contextlib.suppress(OSError):
            self._socket_path.unlink()
        if self._home is not None:
            self._home.cleanup()
            self._home = None

    def __enter__(self) -> LiveRuntime:
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
