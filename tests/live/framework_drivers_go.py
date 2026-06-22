"""Locate and run the Go AI-agent *framework* smoke driver (AAASM-3525).

This is the framework-smoke analogue of :mod:`tests.live.sdk_drivers` for Go.
It is a **separate module** (not an edit of the shared SDK-driver harness) so the
AAASM-3525 Go work adds only new files and never conflicts with the parallel
Python/Node framework PRs. It reuses the same *justified-skip* discipline:
:func:`locate_go_framework_driver` makes every prerequisite decision (toolchain,
go-sdk checkout, the committed driver module, and the built cgo FFI library)
**without launching anything**, raising :class:`DriverUnavailable` with a
concrete reason a skip-audit accepts; :func:`run_go_framework_driver` then builds
+ runs the driver under the ``aa_ffi_go`` cgo tag against the live runtime UDS.

What the driver proves (real, not mock): a genuine **LangChainGo** agent (offline
fake LLM + real ``langchaingo/tools.Tool``) — and the generic ``WrapTools`` Go
path — runs through the real ``assembly.WrapTools`` / ``assembly.WrapChain``
governance code against a reachable live ``aa-runtime``, for an action the policy
allows. The deny path stays a strict xfail in the orchestrator (AAASM-3000 /
AAASM-3021, flip-gated on AAASM-3172); this harness only drives the allow path
and never asserts a clean ``close()``, which deadlocks against a real runtime
today (AAASM-3000).

The module path / replace casing mirrors the go-sdk's *actual* declared,
lowercase module path (``github.com/ai-agent-assembly/go-sdk``); Go module paths
are case-sensitive and the SDK imports its own internal packages under that
spelling, so the locator overrides the replace with the lowercase key.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Root of the integration-tests repo (this file is at tests/live/framework_drivers_go.py).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where the committed Go framework driver module lives.
FRAMEWORK_DRIVER_DIR = Path(__file__).resolve().parent / "drivers" / "go" / "framework"

#: Env override letting a caller point at a go-sdk checkout outside the
#: conventional sibling layout (mirrors AASM_GO_SDK_DIR used by sdk_drivers).
GO_SDK_DIR_ENV = "AASM_GO_SDK_DIR"

#: The go-sdk's actual declared (lowercase) module path. Used as the replace key
#: so it matches the SDK's own internal-package import spelling.
GO_SDK_MODULE_PATH = "github.com/ai-agent-assembly/go-sdk"

#: How long a driver subprocess may run before we treat it as hung and tear it
#: down. The driver does bounded work (plan + one governed tool call + a
#: non-blocking UDS dial), so a generous-but-finite bound keeps a wedged
#: transport (AAASM-3000-adjacent) from blocking the suite. Building the driver
#: with cgo + langchaingo is included in this budget.
DRIVER_TIMEOUT_SECONDS = 180.0

#: The framework modes the driver supports (argv[1]).
LANGCHAINGO_MODE = "langchaingo"
WRAPTOOLS_MODE = "wraptools"


class DriverUnavailable(Exception):
    """A prerequisite for the Go framework driver is absent (justified skip).

    Carries a human-readable reason (names the missing tool / SDK / native
    binding) so a caller can ``pytest.skip(str(exc))`` without a Jira ref.
    """


class DriverFailed(Exception):
    """The Go framework driver ran but the allowed action was not permitted.

    A *hard* failure (a broken allow path), distinct from a justified skip —
    callers must let it fail the test, not swallow it.
    """


@dataclass(frozen=True)
class GoFrameworkDriver:
    """A ready-to-run Go framework driver and the context to launch it.

    :param sdk_dir: the go-sdk checkout the driver module ``replace``-points at.
    :param module_dir: the committed driver module under ``drivers/go/framework``.
    """

    sdk_dir: Path
    module_dir: Path


def _go_sdk_dir() -> Path | None:
    """Return the go-sdk checkout from the env override, else sibling ``../go-sdk``.

    Returns ``None`` when neither location is an existing directory, so the
    locator can raise a justified :class:`DriverUnavailable`.
    """
    raw = os.environ.get(GO_SDK_DIR_ENV)
    if raw:
        candidate = Path(raw).expanduser()
        return candidate if candidate.is_dir() else None
    sibling = REPO_ROOT.parent / "go-sdk"
    return sibling if sibling.is_dir() else None


def _go_native_lib_present(sdk_dir: Path) -> bool:
    """Return True when the go-sdk's cgo FFI library appears to be built.

    The genuine Go ``SDK → aa-ffi → aa-runtime`` transport only links under the
    ``aa_ffi_go`` cgo build tag against a compiled ``libaa_ffi_go`` library.
    Without it the SDK falls back to a *simulated* transport that never dials the
    socket — so a driver run would not exercise the real core. We treat the
    library's absence as a justified skip rather than a silent no-op pass.
    """
    for pattern in ("libaa_ffi_go.a", "libaa_ffi_go.dylib", "libaa_ffi_go.so"):
        if any(sdk_dir.rglob(pattern)):
            return True
    return False


def locate_go_framework_driver(*, require_native_lib: bool = True) -> GoFrameworkDriver:
    """Locate the Go toolchain + go-sdk + driver, or raise :class:`DriverUnavailable`.

    Checks, in order, for ``go`` on ``PATH``, a go-sdk checkout (sibling
    ``../go-sdk`` or :data:`GO_SDK_DIR_ENV`), the committed framework driver
    module (``go.mod`` present), and — when *require_native_lib* — the built cgo
    FFI library the genuine SDK→runtime transport needs. Each missing piece
    raises with a concrete, skip-audit-justified reason. Launches nothing.

    *require_native_lib* is a seam for the offline unit test, which exercises the
    locator's tool/SDK checks without demanding a compiled native library.
    """
    if shutil.which("go") is None:
        raise DriverUnavailable(
            "Go toolchain not available — install go to run the Go framework "
            "smoke driver (AAASM-3525)"
        )
    sdk_dir = _go_sdk_dir()
    if sdk_dir is None:
        raise DriverUnavailable(
            "Go SDK checkout not found — clone go-sdk alongside this repo or set "
            f"{GO_SDK_DIR_ENV} to run the Go framework smoke driver"
        )
    if not (FRAMEWORK_DRIVER_DIR / "go.mod").is_file():
        raise DriverUnavailable(
            "Go framework driver module is missing its go.mod — the live driver "
            "cannot be built (AAASM-3525)"
        )
    if require_native_lib and not _go_native_lib_present(sdk_dir):
        raise DriverUnavailable(
            "go-sdk cgo FFI library not built — build libaa_ffi_go (`make native` "
            "in the go-sdk checkout) so the Go SDK reaches a real core instead of "
            "its simulated fallback, to run the framework smoke driver (AAASM-3525)"
        )
    return GoFrameworkDriver(sdk_dir=sdk_dir, module_dir=FRAMEWORK_DRIVER_DIR)


def _parse_driver_result(stdout: str) -> dict:
    """Parse the driver's last stdout line as its JSON result object.

    The driver prints a single-line JSON object; we read the last non-empty line
    so incidental output does not confuse the parse.
    """
    last = ""
    for line in stdout.splitlines():
        if line.strip():
            last = line.strip()
    if not last:
        raise DriverFailed("driver produced no JSON result on stdout")
    try:
        return json.loads(last)
    except json.JSONDecodeError as exc:
        raise DriverFailed(f"driver result was not valid JSON: {last!r}") from exc


def run_go_framework_driver(
    driver: GoFrameworkDriver, socket_path: Path, action: str, mode: str
) -> dict:
    """Run the Go framework driver against *socket_path*; return its JSON result.

    Copies the committed driver module into a private temp dir, repoints its
    ``replace`` at the *located* go-sdk checkout (so an ``AASM_GO_SDK_DIR``
    override works and the committed sibling-relative default is never mutated),
    then builds + runs it with ``go run`` under the ``aa_ffi_go`` cgo tag so it
    links the genuine FFI transport. *mode* selects the framework cell
    (``langchaingo`` or ``wraptools``). Bounded by
    :data:`DRIVER_TIMEOUT_SECONDS`. Returns the parsed result; raises
    :class:`DriverFailed` on a blocked action, non-zero exit, or timeout.
    """
    env = {
        **os.environ,
        # -mod=mod lets `go` resolve the local replace without a network
        # `go mod tidy`; the driver's deps are already pinned in go.sum.
        "GOFLAGS": "-mod=mod",
    }
    with tempfile.TemporaryDirectory(prefix="aaitest-go-framework-") as build_root:
        build_dir = Path(build_root)
        for name in ("go.mod", "go.sum", "framework_agent.go"):
            shutil.copy2(driver.module_dir / name, build_dir / name)
        # Repoint the replace at the resolved (possibly env-overridden) SDK dir,
        # absolute so it does not depend on this temp dir's location. The replace
        # key is the SDK's actual lowercase module path.
        subprocess.run(
            [
                "go",
                "mod",
                "edit",
                "-replace",
                f"{GO_SDK_MODULE_PATH}={driver.sdk_dir.resolve()}",
            ],
            cwd=str(build_dir),
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        proc = subprocess.run(
            [
                "go",
                "run",
                "-tags",
                "cgo aa_ffi_go",
                ".",
                mode,
                str(socket_path),
                action,
            ],
            cwd=str(build_dir),
            capture_output=True,
            text=True,
            timeout=DRIVER_TIMEOUT_SECONDS,
            env=env,
        )
    result = _parse_driver_result(proc.stdout)
    if proc.returncode != 0 or not result.get("ok"):
        raise DriverFailed(
            f"Go {mode} framework driver failed (exit {proc.returncode}): "
            f"{result.get('error', proc.stderr.strip() or 'unknown')}"
        )
    return result
