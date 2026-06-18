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
import importlib.util
import os
import shutil
import socket
import subprocess
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path

# Verification areas mirror aasm_verify.runners.AREAS. Kept as a local literal so
# the doctor command stays importable without constructing a runner, and so the
# area-status report is stable even if runner ordering changes.
AREAS: tuple[str, ...] = ("runtime", "sdk", "examples", "install", "conformance")


class Status(StrEnum):
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
        # Fixed argv, no shell — safe to run as-is.
        proc = subprocess.run(  # noqa: S603
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
    CacheSpec(
        "cargo", "CARGO_HOME", ("CARGO_HOME",), ".cargo", ("runtime", "install", "conformance")
    ),
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


# Browser availability gates dashboard screenshot tests, which ride along with
# the examples area. Its absence is a *warn*: screenshot coverage is optional and
# the rest of the examples area still runs without a browser.
_BROWSER_AREAS: tuple[str, ...] = ("examples",)


def _playwright_browsers_dir() -> Path:
    """Resolve the Playwright browser-cache directory without importing it."""
    override = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if override and override not in ("0", "1"):
        return Path(override)
    home = Path.home()
    # Platform default locations Playwright installs Chromium under.
    candidates = (
        home / "Library" / "Caches" / "ms-playwright",  # macOS
        home / ".cache" / "ms-playwright",  # Linux
        home / "AppData" / "Local" / "ms-playwright",  # Windows
    )
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def check_browser() -> CheckResult:
    """Detect a Playwright/Chromium install *without launching* a browser.

    Detection is two-stage and never launches a process: the ``playwright``
    Python package must be importable, and its browser cache must contain a
    Chromium install. Absent either, return :data:`Status.WARN` (dashboard
    screenshots are skipped, not fatal).
    """
    if importlib.util.find_spec("playwright") is None:
        return CheckResult(
            name="browser",
            status=Status.WARN,
            detail="playwright package not importable; dashboard screenshot tests skipped",
            areas=_BROWSER_AREAS,
        )
    browsers_dir = _playwright_browsers_dir()
    chromium_installs = sorted(browsers_dir.glob("chromium-*")) if browsers_dir.exists() else []
    if not chromium_installs:
        return CheckResult(
            name="browser",
            status=Status.WARN,
            detail=(
                f"playwright present but no Chromium in {browsers_dir}; "
                "run 'playwright install chromium'"
            ),
            areas=_BROWSER_AREAS,
        )
    return CheckResult(
        name="browser",
        status=Status.PASS,
        detail=f"playwright + chromium available: {chromium_installs[-1].name}",
        areas=_BROWSER_AREAS,
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


def run_all_checks() -> list[CheckResult]:
    """Run every capability probe and return the flat list of results.

    Probe order is deterministic (tools, bind, network, caches, browser) so text
    and JSON output is stable across runs and machines.
    """
    checks: list[CheckResult] = []
    checks.extend(check_tools())
    checks.append(check_localhost_bind())
    checks.append(check_network())
    checks.extend(check_caches())
    checks.append(check_browser())
    return checks


@dataclass
class DoctorReport:
    """Full preflight report: the capability checks plus per-area rollup.

    Attributes:
        checks: Every capability :class:`CheckResult`, in probe order.
        areas: Per-area aggregated :class:`Status` (worst gating capability).
        overall: The single worst status across all areas — the CI exit signal.
    """

    checks: list[CheckResult]
    areas: dict[str, Status]
    overall: Status

    @classmethod
    def build(cls) -> DoctorReport:
        """Run all probes and assemble the report."""
        checks = run_all_checks()
        areas = area_statuses(checks)
        overall = worst(list(areas.values()))
        return cls(checks=checks, areas=areas, overall=overall)

    def recommended_env(self) -> dict[str, str]:
        """Merge every check's recommended env vars into one mapping."""
        merged: dict[str, str] = {}
        for check in self.checks:
            merged.update(check.recommend_env)
        return merged

    def as_dict(self) -> dict[str, object]:
        """Render the report as a JSON-serializable structure for CI."""
        return {
            "overall": self.overall.value,
            "areas": {area: status.value for area, status in self.areas.items()},
            "checks": [check.as_dict() for check in self.checks],
            "recommended_env": self.recommended_env(),
        }


# ASCII glyphs (not unicode) so the report is safe in any CI log encoding.
_GLYPH: dict[Status, str] = {
    Status.PASS: "[PASS]",
    Status.WARN: "[WARN]",
    Status.FAIL: "[FAIL]",
}


def render_text(report: DoctorReport) -> str:
    """Render a human-readable pass/warn/fail report for a terminal or CI log."""
    lines: list[str] = ["Environment preflight (aasm-verify doctor)", ""]

    lines.append("Capabilities:")
    for check in report.checks:
        lines.append(f"  {_GLYPH[check.status]} {check.name}: {check.detail}")

    lines.append("")
    lines.append("Areas:")
    for area in AREAS:
        status = report.areas[area]
        lines.append(f"  {_GLYPH[status]} {area}")

    recommended = report.recommended_env()
    if recommended:
        lines.append("")
        lines.append("Recommended environment variables:")
        for key, value in sorted(recommended.items()):
            lines.append(f"  export {key}={value}")

    lines.append("")
    lines.append(f"Overall: {_GLYPH[report.overall]} {report.overall.value}")
    return "\n".join(lines)


# A FAIL in any area is the only outcome that blocks the run; WARN is advisory.
def exit_code(report: DoctorReport) -> int:
    """Map the overall status to a CLI exit code (0 unless an area is ``FAIL``)."""
    return 1 if report.overall is Status.FAIL else 0
