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
import shutil
import socket
import subprocess
from dataclasses import dataclass, field
from enum import Enum

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
