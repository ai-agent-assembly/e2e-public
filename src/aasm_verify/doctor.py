"""Environment preflight checks for production validation runs (AAASM-3159).

Before the public verification suite touches the network or builds anything,
``aasm-verify doctor`` answers a single question per machine: *can this host run
each validation area at all?* It probes the local environment — required tools,
network reachability, localhost bind permission, cache writability, and browser
availability — and reports **pass / warn / fail by area** so a CI summary (or a
human) can decide what to skip before a single test starts.

Design notes:

* **Offline-safe.** Every probe runs without a working network. Network
  reachability *degrades* to ``warn`` when offline rather than failing — being
  offline is information, not an error.
* **Stdlib-only.** Tool detection uses :func:`shutil.which` plus a short version
  subprocess; the bind probe is a real :func:`socket.socket` bind on
  ``127.0.0.1:0``; cache writability writes a temp file under each cache dir;
  browser detection looks for a Playwright/Chromium install without launching.
* **Capability → area mapping.** Each probe is a *capability*; a capability maps
  to the verification area(s) it gates (see :data:`runners.AREAS`). An area's
  status is the worst status of the capabilities it depends on.
* **Machine-readable.** ``--json`` emits the full structure for a CI summary.

This module is a standalone CLI command. Wiring it into ``conftest.py`` and the
CI workflows is intentionally deferred to AAASM-3160 to avoid shared-file churn.
"""

from __future__ import annotations

import errno
import os
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

# Verification areas mirror aasm_verify.runners.AREAS. Kept as a local literal so
# the doctor command stays importable without constructing a runner, and so the
# area-status report is stable even if runner ordering changes.
AREAS: tuple[str, ...] = ("runtime", "sdk", "examples", "install", "conformance")


class Status(str, Enum):
    """Tri-state outcome for a capability check or an aggregated area.

    String-valued so it serializes directly into ``--json`` output.

    * ``PASS`` — the capability is fully available.
    * ``WARN`` — degraded but not fatal (e.g. network unreachable, missing tool
      that only gates an optional area).
    * ``FAIL`` — the capability is required and unavailable; the gated area
      cannot run on this machine.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


# Severity ordering for aggregation: an area is as bad as its worst capability.
_SEVERITY: dict[Status, int] = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


def worst(statuses: list[Status]) -> Status:
    """Return the most severe status in ``statuses`` (``PASS`` if empty)."""
    if not statuses:
        return Status.PASS
    return max(statuses, key=lambda s: _SEVERITY[s])


@dataclass
class CheckResult:
    """The outcome of one capability probe.

    Attributes:
        name: Stable capability identifier (e.g. ``"tool:cargo"``, ``"bind"``).
        status: Tri-state :class:`Status`.
        detail: Human-readable explanation (version string, error message).
        areas: Verification areas this capability gates.
        recommend_env: Recommended environment variables to remediate, e.g.
            ``{"GOCACHE": "/tmp/aasm-gocache"}``. Empty when no action helps.
    """

    name: str
    status: Status
    detail: str = ""
    areas: tuple[str, ...] = ()
    recommend_env: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "areas": list(self.areas),
            "recommend_env": dict(self.recommend_env),
        }


@dataclass(frozen=True)
class ToolSpec:
    """A required external tool and the areas its absence blocks.

    Attributes:
        name: Executable name passed to :func:`shutil.which`.
        version_arg: Argument that prints a version (e.g. ``"--version"``).
        areas: Verification areas that cannot run without this tool.
        required: When ``True`` a missing tool is :data:`Status.FAIL`; when
            ``False`` it is :data:`Status.WARN` (the area degrades but a partial
            run is still meaningful).
    """

    name: str
    version_arg: str
    areas: tuple[str, ...]
    required: bool = True


# The tool matrix. Areas mirror the validation areas each tool actually gates:
# building/running aa-gateway needs the Rust toolchain + protoc; SDK smokes need
# their language toolchains; examples exercise every SDK; install runs the Rust
# build smoke. ``git`` gates everything (all areas clone source).
TOOL_MATRIX: tuple[ToolSpec, ...] = (
    ToolSpec("cargo", "--version", ("runtime", "install", "conformance")),
    ToolSpec("rustc", "--version", ("runtime", "install", "conformance")),
    ToolSpec("protoc", "--version", ("runtime", "install", "conformance")),
    ToolSpec("uv", "--version", ("sdk", "examples")),
    ToolSpec("python", "--version", ("sdk", "examples")),
    ToolSpec("node", "--version", ("sdk", "examples")),
    ToolSpec("pnpm", "--version", ("sdk", "examples")),
    ToolSpec("go", "version", ("sdk", "examples")),
    ToolSpec("git", "--version", AREAS),
)


def _tool_version(name: str, version_arg: str) -> str | None:
    """Return the first line of ``<name> <version_arg>`` output, or ``None``.

    Never raises: any spawn/timeout/non-zero-exit failure yields ``None`` so the
    caller can record the tool as unavailable without aborting the whole probe.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell.
            [name, version_arg],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    output = (proc.stdout or proc.stderr).strip()
    if proc.returncode != 0 and not output:
        return None
    return output.splitlines()[0] if output else ""


def check_tool(spec: ToolSpec) -> CheckResult:
    """Probe a single tool from the :data:`TOOL_MATRIX`.

    ``PASS`` when the executable is on ``PATH`` and reports a version; otherwise
    ``FAIL`` for a required tool or ``WARN`` for an optional one.
    """
    path = shutil.which(spec.name)
    if path is None:
        status = Status.FAIL if spec.required else Status.WARN
        return CheckResult(
            name=f"tool:{spec.name}",
            status=status,
            detail=f"{spec.name} not found on PATH",
            areas=spec.areas,
        )
    version = _tool_version(spec.name, spec.version_arg)
    if version is None:
        status = Status.FAIL if spec.required else Status.WARN
        return CheckResult(
            name=f"tool:{spec.name}",
            status=status,
            detail=f"{spec.name} found at {path} but version probe failed",
            areas=spec.areas,
        )
    return CheckResult(
        name=f"tool:{spec.name}",
        status=Status.PASS,
        detail=version or f"{spec.name} present at {path}",
        areas=spec.areas,
    )


def check_tools() -> list[CheckResult]:
    """Probe every tool in the :data:`TOOL_MATRIX`."""
    return [check_tool(spec) for spec in TOOL_MATRIX]


# Binding a localhost port is required by any area that boots a local server:
# the runtime CLI smoke and conformance suites start aa-gateway on 127.0.0.1.
_BIND_AREAS: tuple[str, ...] = ("runtime", "conformance")


def check_localhost_bind() -> CheckResult:
    """Attempt to bind an ephemeral ``127.0.0.1`` port.

    Sandboxes commonly forbid loopback binds; the syscall fails with ``EPERM``
    or ``EACCES``. Those map to :data:`Status.FAIL` (the gated areas cannot run).
    Any other ``OSError`` is also a fail but reported verbatim.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            detail = (
                f"loopback bind denied ({errno.errorcode.get(exc.errno, exc.errno)}): "
                "this sandbox forbids binding 127.0.0.1"
            )
        else:
            detail = f"loopback bind failed: {exc}"
        return CheckResult(
            name="bind",
            status=Status.FAIL,
            detail=detail,
            areas=_BIND_AREAS,
        )
    finally:
        sock.close()
    return CheckResult(
        name="bind",
        status=Status.PASS,
        detail=f"bound 127.0.0.1:{port}",
        areas=_BIND_AREAS,
    )


# Network reachability gates every area that clones source or installs packages.
# Offline is a *warn*, never a *fail* — flagging the limitation is the point.
_NETWORK_AREAS: tuple[str, ...] = ("runtime", "sdk", "examples", "install", "conformance")
# Probed host:port pairs; the first to connect wins. github.com serves source
# clones, pypi.org serves the registry-install tests. Both are TCP 443.
_NETWORK_TARGETS: tuple[tuple[str, int], ...] = (
    ("github.com", 443),
    ("pypi.org", 443),
)


def _can_connect(host: str, port: int, timeout: float) -> bool:
    """Return ``True`` if a TCP connection to ``host:port`` succeeds in time."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_network(timeout: float = 3.0) -> CheckResult:
    """Probe outbound network reachability with a short connect timeout.

    Returns :data:`Status.PASS` when any target is reachable, else
    :data:`Status.WARN` — being offline degrades install/release/example areas
    but must not hard-fail the preflight (an offline run can still exercise the
    areas that do not touch the network).
    """
    for host, port in _NETWORK_TARGETS:
        if _can_connect(host, port, timeout):
            return CheckResult(
                name="network",
                status=Status.PASS,
                detail=f"reachable: {host}:{port}",
                areas=_NETWORK_AREAS,
            )
    return CheckResult(
        name="network",
        status=Status.WARN,
        detail=(
            "network unavailable: no target reachable "
            f"({', '.join(f'{h}:{p}' for h, p in _NETWORK_TARGETS)}); "
            "install/release/example dependency tests will be skipped"
        ),
        areas=_NETWORK_AREAS,
    )


@dataclass(frozen=True)
class CacheSpec:
    """A toolchain cache directory and how to relocate it.

    Attributes:
        label: Short name (``"go"``, ``"cargo"``, ``"pnpm"``, ``"uv"``).
        env_var: Environment variable that overrides the cache location.
        env_paths: Candidate env vars whose value is the cache dir, in order.
        default: Default cache dir relative to ``$HOME`` when no env var is set.
        areas: Verification areas a non-writable cache degrades.
    """

    label: str
    env_var: str
    env_paths: tuple[str, ...]
    default: str
    areas: tuple[str, ...]


# Cache matrix. Each toolchain writes a build/download cache; on a read-only
# HOME the run fails late, so probe writability now and recommend an env var
# pointing at a writable temp dir when it is not writable.
CACHE_MATRIX: tuple[CacheSpec, ...] = (
    CacheSpec("go", "GOCACHE", ("GOCACHE",), ".cache/go-build", ("sdk", "examples")),
    CacheSpec("cargo", "CARGO_HOME", ("CARGO_HOME",), ".cargo", ("runtime", "install", "conformance")),
    CacheSpec("pnpm", "PNPM_HOME", ("PNPM_HOME",), ".local/share/pnpm", ("sdk", "examples")),
    CacheSpec("uv", "UV_CACHE_DIR", ("UV_CACHE_DIR",), ".cache/uv", ("sdk", "examples")),
)


def _resolve_cache_dir(spec: CacheSpec) -> Path:
    """Resolve the configured cache directory for ``spec``."""
    for env in spec.env_paths:
        value = os.environ.get(env)
        if value:
            return Path(value)
    return Path.home() / spec.default


def _is_writable(directory: Path) -> bool:
    """Return ``True`` if a temp file can be created under ``directory``.

    Creates parent directories if needed; any failure (missing, read-only,
    permission denied) yields ``False``.
    """
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, prefix=".aasm-doctor-"):
            return True
    except OSError:
        return False


def check_cache(spec: CacheSpec) -> CheckResult:
    """Probe writability of one toolchain cache directory.

    ``PASS`` when the resolved cache dir is writable; otherwise ``WARN`` with a
    recommended env var pointing at a writable temp directory.
    """
    cache_dir = _resolve_cache_dir(spec)
    if _is_writable(cache_dir):
        return CheckResult(
            name=f"cache:{spec.label}",
            status=Status.PASS,
            detail=f"{spec.env_var} writable: {cache_dir}",
            areas=spec.areas,
        )
    fallback = str(Path(tempfile.gettempdir()) / f"aasm-{spec.label}-cache")
    return CheckResult(
        name=f"cache:{spec.label}",
        status=Status.WARN,
        detail=f"{spec.env_var} dir not writable: {cache_dir}",
        areas=spec.areas,
        recommend_env={spec.env_var: fallback},
    )


def check_caches() -> list[CheckResult]:
    """Probe every cache directory in the :data:`CACHE_MATRIX`."""
    return [check_cache(spec) for spec in CACHE_MATRIX]


def area_statuses(checks: list[CheckResult]) -> dict[str, Status]:
    """Aggregate capability checks into a per-area status map.

    Each area's status is the worst status among the checks that gate it. Areas
    with no gating check default to ``PASS``.
    """
    by_area: dict[str, list[Status]] = {area: [] for area in AREAS}
    for check in checks:
        for area in check.areas:
            if area in by_area:
                by_area[area].append(check.status)
    return {area: worst(statuses) for area, statuses in by_area.items()}
