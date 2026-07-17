"""Spawn a companion ``aa-api-server`` process purely to source a version.

``aa-gateway`` in ``legacy-grpc`` mode — what :class:`tests.live.gateway.LiveGateway`
spawns — mounts no HTTP surface at all: its CLI takes ``--policy``/``--listen``/
``--socket``/``--audit-dir`` and nothing REST-shaped, and it exposes no gRPC
version/health RPC either. Before this module, the AAASM-4669 version-skew
preflight's ``fetch_gateway_version()`` therefore always raised
``GatewayVersionUnavailable`` against the live fixture and the calling test
skipped on *every* run — invisible to strict mode (AAASM-4792).

``aa-api-server`` (the ``aa-api`` crate's shipped REST entrypoint) does mount
``GET /api/v1/health`` unauthenticated. Because the workspace version is
unified (a single `[workspace.package] version` all crates inherit — see the
core repo's root ``CLAUDE.md``), its self-reported ``CARGO_PKG_VERSION`` is
identical to the ``aa-gateway`` binary's whenever both are built from the same
source tree. Spawning it alongside the fixture gateway — same core checkout,
separate process — gives the preflight a real, comparable version to assert
against without requiring a change to ``aa-gateway`` itself.

This is a thinner sibling of ``gateway.LiveGateway``: it exists only to serve
``/api/v1/health`` for this diagnostic, not as a general local-mode harness (it
does not drive the dashboard SPA, gRPC AgentLifecycleService, or REST auth
surface that ``aa-api-server`` also happens to serve).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from tests.live.gateway import free_port

#: Default readiness timeout in seconds. Generous relative to a bare TCP accept
#: because first boot may extract the embedded dashboard SPA before serving.
DEFAULT_READY_TIMEOUT = 30.0


class LiveApiServer:
    """A spawned ``aa-api-server`` process bound to a free loopback port.

    Construct with the built binary path; call :meth:`start` to launch,
    :meth:`await_ready` to block until ``GET /api/v1/health`` responds, and
    :meth:`stop` to terminate. Usable as a context manager.
    """

    def __init__(self, binary: Path) -> None:
        self._binary = Path(binary)
        self._port = free_port()
        self._proc: subprocess.Popen[bytes] | None = None
        self._home: tempfile.TemporaryDirectory[str] | None = None

    @property
    def health_url(self) -> str:
        """The ``http://host:port`` origin :func:`fetch_gateway_version` reads."""
        return f"http://127.0.0.1:{self._port}"

    def start(self) -> LiveApiServer:
        """Launch ``aa-api-server`` with an isolated HOME; return self.

        HOME isolation keeps the process's local SQLite-backed registry out of
        the engineer's real ``~/.aasm`` — mirroring ``LiveGateway.start()``.
        The bind address is set via ``AA_API_ADDR`` (the binary's documented
        override), not a CLI flag — ``aa-api-server`` takes none.
        """
        self._home = tempfile.TemporaryDirectory(prefix="live-api-server-home-")
        self._proc = subprocess.Popen(
            [str(self._binary)],
            env={
                "HOME": self._home.name,
                "PATH": os.environ.get("PATH", ""),
                "AA_API_ADDR": f"127.0.0.1:{self._port}",
            },
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return self

    def await_ready(self, timeout: float = DEFAULT_READY_TIMEOUT) -> None:
        """Block until ``GET /api/v1/health`` responds.

        Raises ``RuntimeError`` on early process exit or timeout.
        """
        url = self.health_url + "/api/v1/health"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                raise RuntimeError(
                    f"aa-api-server exited early (code {self._proc.returncode}) "
                    f"before serving {url}"
                )
            try:
                # http:// to a loopback test process is intentional (no remote
                # transport to encrypt); S310 is not applicable to this local
                # health probe.
                with urllib.request.urlopen(url, timeout=0.5):  # noqa: S310
                    return
            except OSError:
                time.sleep(0.1)
        raise RuntimeError(f"aa-api-server did not respond on {url} within {timeout:.0f}s")

    def stop(self) -> None:
        """Terminate the process and remove its temp HOME. Idempotent."""
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        if self._home is not None:
            self._home.cleanup()
            self._home = None

    def __enter__(self) -> LiveApiServer:
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()
