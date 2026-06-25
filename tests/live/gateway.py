"""Spawn and supervise a live ``aa-gateway`` subprocess.

``LiveGateway`` launches the built gateway binary on a free TCP port
with an isolated ``$HOME`` and audit directory, waits for the gRPC
listener to accept connections, and terminates the process on
``stop()`` / context-manager exit.

This mirrors the Rust reference fixture in the monorepo
(``aa-integration-tests/tests/common/live_gateway.rs``).
"""

from __future__ import annotations

import os
import socket
import subprocess
import tempfile
import time
from pathlib import Path

#: Default minimal policy shipped alongside this module.
MINIMAL_POLICY = Path(__file__).parent / "fixtures" / "policies" / "minimal.yaml"

#: Env var that overrides the gateway TCP-readiness timeout (seconds).
#: A larger default than the historical hard-coded 30s absorbs slow cold
#: starts on busy machines (a gateway still warming after a fresh cargo
#: build); operators tune it without touching code.
READY_TIMEOUT_ENV = "AASM_GATEWAY_READY_TIMEOUT"

#: Default readiness timeout in seconds when the env var is unset/invalid.
DEFAULT_READY_TIMEOUT = 90.0

#: Trailing log lines surfaced in a readiness-timeout error so the failure
#: is diagnosable instead of a context-free "never became ready".
_LOG_TAIL_LINES = 50


def _resolve_ready_timeout() -> float:
    """Return the readiness timeout from the env var, falling back safely.

    Reads :data:`READY_TIMEOUT_ENV`; a missing, unparseable, or non-positive
    value yields :data:`DEFAULT_READY_TIMEOUT` rather than raising, so a typo
    in CI never turns a flaky-timeout fix into a hard usage error.
    """
    raw = os.environ.get(READY_TIMEOUT_ENV)
    if raw is None:
        return DEFAULT_READY_TIMEOUT
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_READY_TIMEOUT
    return value if value > 0 else DEFAULT_READY_TIMEOUT


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
        #: Captured stdout+stderr of the spawned gateway; lives inside the
        #: isolated HOME (so it is auto-removed on success) but its tail is
        #: copied into the readiness-timeout error before that cleanup runs.
        self._log_path: Path | None = None

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

        # Capture stdout+stderr to a file (not DEVNULL) so a readiness
        # timeout can surface the gateway's own diagnostics. It lives in the
        # isolated HOME, so stop()'s cleanup removes it on the success path.
        self._log_path = home_path / "gateway.log"
        log_handle = self._log_path.open("wb")

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
            stdout=log_handle,
            stderr=subprocess.STDOUT,
        )
        # Popen dups the fd; close our copy so only the child holds it open.
        log_handle.close()
        return self

    def await_ready(self, timeout: float | None = None) -> None:
        """Block until the gateway accepts a TCP connection on its port.

        Polls ``connect`` to ``127.0.0.1:<port>`` until it succeeds or
        *timeout* seconds elapse. When *timeout* is ``None`` it is resolved
        from :data:`READY_TIMEOUT_ENV` (default :data:`DEFAULT_READY_TIMEOUT`)
        so the wait is configurable for slow/cold-start machines. On early
        process exit or timeout it raises ``RuntimeError`` carrying the
        endpoint, elapsed time, and the tail of the gateway's captured log so
        the failure is diagnosable.
        """
        if timeout is None:
            timeout = _resolve_ready_timeout()
        start = time.monotonic()
        deadline = start + timeout
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                elapsed = time.monotonic() - start
                raise RuntimeError(
                    f"aa-gateway exited early (code {self._proc.returncode}) "
                    f"before listening on {self.endpoint} "
                    f"after {elapsed:.1f}s{self._log_tail_suffix()}"
                )
            try:
                with socket.create_connection(("127.0.0.1", self._port), timeout=0.2):
                    return
            except OSError:
                time.sleep(0.1)
        elapsed = time.monotonic() - start
        raise RuntimeError(
            f"aa-gateway did not start accepting connections on "
            f"{self.endpoint} within {timeout:.0f}s (waited {elapsed:.1f}s)"
            f"{self._log_tail_suffix()}"
        )

    def _log_tail_suffix(self) -> str:
        """Return the last :data:`_LOG_TAIL_LINES` of the captured log.

        Formatted as a trailing block for inclusion in a readiness-failure
        message. Best-effort: if the log is missing/unreadable it returns a
        short note rather than masking the original error.
        """
        if self._log_path is None:
            return "\n--- no gateway log captured ---"
        try:
            text = self._log_path.read_text(errors="replace")
        except OSError as exc:
            return f"\n--- gateway log unreadable: {exc} ---"
        lines = text.splitlines()
        if not lines:
            return f"\n--- gateway log empty ({self._log_path}) ---"
        tail = "\n".join(lines[-_LOG_TAIL_LINES:])
        return (
            f"\n--- last {min(len(lines), _LOG_TAIL_LINES)} log line(s) "
            f"from {self._log_path} ---\n{tail}"
        )

    def stop(self) -> None:
        """Terminate the gateway and remove its temp HOME directory.

        Sends ``terminate`` (SIGTERM), waits briefly, then ``kill`` if it
        has not exited. Idempotent — safe to call more than once.
        """
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait()
            self._proc = None
        if self._home is not None:
            # Removes the isolated HOME including the captured gateway.log.
            self._home.cleanup()
            self._home = None
        self._log_path = None

    def __enter__(self) -> LiveGateway:
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()


def _inherited_path() -> str:
    """Return the current ``PATH`` so the spawned gateway can find libs."""
    return os.environ.get("PATH", "")
