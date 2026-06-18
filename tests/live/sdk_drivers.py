"""Locate and run the per-language SDK allow-path drivers (AAASM-3194).

The live enforcement E2E drives the **Python** SDK in-process (its ``_core``
extension is importable; see ``runtime_client.py``), but the **Node** and **Go**
SDKs are reached only through their own toolchains. This module is the bridge:
for each of those two SDKs it

* **locates** the toolchain (``node``/``pnpm``, ``go``), the SDK checkout, and
  the built native binding that lets the driver actually reach a live core, and
* **runs** the matching subprocess driver under ``tests/live/drivers/`` against
  the live ``aa-runtime`` UDS, parsing its one-line JSON result.

The split is deliberate: :func:`locate_node_driver` / :func:`locate_go_driver`
do all the *justified-skip* decisions (a missing tool / SDK / native binding
raises :class:`DriverUnavailable` with a concrete reason an
``AASM_VERIFY_STRICT`` audit accepts), and they do so **without launching
anything** — so the per-language E2E can call the locator, translate a
``DriverUnavailable`` into a clean ``pytest.skip``, and only then spawn the
driver. That keeps the offline path (collection + locator logic) green with no
runtime, exactly like the existing live tests.

Driver execution mirrors the Python allow path: ship an allowed-action event /
run an allowed governed tool, observe it is permitted — and **never** assert a
clean ``close()``, which deadlocks against a real runtime today (AAASM-3000).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

#: Root of the integration-tests repo (this file is at tests/live/sdk_drivers.py).
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Where the committed driver sources live.
DRIVERS_DIR = Path(__file__).resolve().parent / "drivers"

#: Env overrides letting a caller point at SDK checkouts outside the conventional
#: sibling layout (mirrors AASM_CORE_SOURCE_DIR for the core). When unset, we use
#: the sibling ``../node-sdk`` / ``../go-sdk`` next to this repo.
NODE_SDK_DIR_ENV = "AASM_NODE_SDK_DIR"
GO_SDK_DIR_ENV = "AASM_GO_SDK_DIR"

#: How long a driver subprocess may run before we treat it as hung and tear it
#: down. The drivers do bounded work (connect + one event / one tool call), so a
#: generous-but-finite bound keeps a wedged transport (AAASM-3000-adjacent) from
#: blocking the suite.
DRIVER_TIMEOUT_SECONDS = 30.0


class DriverUnavailable(Exception):
    """A language driver cannot run because a prerequisite is absent.

    Carries a human-readable, *justified* reason (names the missing tool / SDK /
    native binding) so a caller can raise ``pytest.skip(str(exc))`` and satisfy
    the skip-audit (:mod:`aasm_verify.skip_audit`) without a Jira ref.
    """


class DriverFailed(Exception):
    """A language driver ran but reported the allowed action was not permitted.

    This is a *hard* failure (a broken allow path), distinct from a justified
    skip — callers must let it fail the test, not swallow it.
    """


@dataclass(frozen=True)
class NodeDriver:
    """A ready-to-run Node allow-path driver and the context to launch it.

    :param sdk_dir: the Node SDK checkout (its cwd, so the native binding loads
        the way the SDK itself loads it).
    :param native_client_module: absolute path to the SDK's compiled
        ``dist/esm/native/client.js`` (the genuine SDK native client).
    :param script: the ``enforce_allow.mjs`` driver.
    """

    sdk_dir: Path
    native_client_module: Path
    script: Path


@dataclass(frozen=True)
class GoDriver:
    """A ready-to-run Go allow-path driver and the context to launch it.

    :param sdk_dir: the go-sdk checkout the driver module ``replace``-points at.
    :param module_dir: the driver's own Go module under ``drivers/go``.
    """

    sdk_dir: Path
    module_dir: Path


def _sibling_sdk_dir(env_var: str, sibling_name: str) -> Path | None:
    """Return the SDK checkout from *env_var*, else the sibling ``../<name>``.

    Returns ``None`` when neither location is an existing directory, so the
    locator can raise a justified ``DriverUnavailable``.
    """
    raw = os.environ.get(env_var)
    if raw:
        candidate = Path(raw).expanduser()
        return candidate if candidate.is_dir() else None
    sibling = REPO_ROOT.parent / sibling_name
    return sibling if sibling.is_dir() else None


def locate_node_driver() -> NodeDriver:
    """Locate the Node toolchain + built SDK, or raise :class:`DriverUnavailable`.

    Checks, in order, for ``node`` on ``PATH``, a Node SDK checkout (sibling
    ``../node-sdk`` or :data:`NODE_SDK_DIR_ENV`), the SDK's compiled native
    client (``dist/esm/native/client.js`` — i.e. the package was built), and the
    checked-in native binding (``native/aa-ffi-node/index.cjs``) that the genuine
    ``SDK → aa-ffi → aa-runtime`` path needs. Each missing piece raises with a
    concrete, skip-audit-justified reason. Launches nothing.
    """
    if shutil.which("node") is None:
        raise DriverUnavailable(
            "Node toolchain not available — install node to run the Node SDK "
            "live allow-path driver (AAASM-3194)"
        )
    sdk_dir = _sibling_sdk_dir(NODE_SDK_DIR_ENV, "node-sdk")
    if sdk_dir is None:
        raise DriverUnavailable(
            "Node SDK checkout not found — clone node-sdk alongside this repo or "
            f"set {NODE_SDK_DIR_ENV} to run the Node SDK live allow-path driver"
        )
    native_client = sdk_dir / "dist" / "esm" / "native" / "client.js"
    if not native_client.is_file():
        raise DriverUnavailable(
            "Node SDK is not built — run `pnpm build` in the node-sdk checkout "
            "(dist/esm/native/client.js is absent) to run the live allow-path driver"
        )
    binding = sdk_dir / "native" / "aa-ffi-node" / "index.cjs"
    if not binding.is_file():
        raise DriverUnavailable(
            "Node SDK native binding not built — run `pnpm native:build` in the "
            "node-sdk checkout (native/aa-ffi-node/index.cjs is absent) to run "
            "the live allow-path driver"
        )
    return NodeDriver(
        sdk_dir=sdk_dir,
        native_client_module=native_client,
        script=DRIVERS_DIR / "enforce_allow.mjs",
    )


def _go_native_lib_present(sdk_dir: Path) -> bool:
    """Return True when the go-sdk's cgo FFI library appears to be built.

    The genuine Go ``SDK → aa-ffi → aa-runtime`` transport only links under the
    ``aa_ffi_go`` cgo build tag against a compiled ``libaa_ffi_go`` static
    library. Without it the SDK falls back to a *simulated* UDS that never dials
    the socket — so a driver run would not exercise the real core. We treat the
    library's absence as a justified skip rather than a silent no-op pass.
    """
    for pattern in ("libaa_ffi_go.a", "libaa_ffi_go.dylib", "libaa_ffi_go.so"):
        if any(sdk_dir.rglob(pattern)):
            return True
    return False


def locate_go_driver(*, require_native_lib: bool = True) -> GoDriver:
    """Locate the Go toolchain + go-sdk, or raise :class:`DriverUnavailable`.

    Checks for ``go`` on ``PATH``, a go-sdk checkout (sibling ``../go-sdk`` or
    :data:`GO_SDK_DIR_ENV`), the committed driver module, and — when
    *require_native_lib* — the built cgo FFI library that the genuine SDK→runtime
    transport needs (see :func:`_go_native_lib_present`). Each missing piece
    raises with a concrete, skip-audit-justified reason. Launches nothing.

    *require_native_lib* is a seam for the offline unit test, which exercises the
    locator's tool/SDK checks without demanding a compiled native library.
    """
    if shutil.which("go") is None:
        raise DriverUnavailable(
            "Go toolchain not available — install go to run the Go SDK live "
            "allow-path driver (AAASM-3194)"
        )
    sdk_dir = _sibling_sdk_dir(GO_SDK_DIR_ENV, "go-sdk")
    if sdk_dir is None:
        raise DriverUnavailable(
            "Go SDK checkout not found — clone go-sdk alongside this repo or set "
            f"{GO_SDK_DIR_ENV} to run the Go SDK live allow-path driver"
        )
    module_dir = DRIVERS_DIR / "go"
    if not (module_dir / "go.mod").is_file():
        raise DriverUnavailable(
            "Go allow-path driver module is missing its go.mod — the live driver "
            "cannot be built (AAASM-3194)"
        )
    if require_native_lib and not _go_native_lib_present(sdk_dir):
        raise DriverUnavailable(
            "go-sdk cgo FFI library not built — build libaa_ffi_go (cargo) so the "
            "Go SDK reaches a real core instead of its simulated fallback, to run "
            "the live allow-path driver (AAASM-3194)"
        )
    return GoDriver(sdk_dir=sdk_dir, module_dir=module_dir)


def _parse_driver_result(stdout: str) -> dict:
    """Parse a driver's last stdout line as the JSON result object.

    Drivers print a single-line JSON object; we read the last non-empty line so
    incidental output (e.g. a runtime banner) does not confuse the parse.
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


def run_node_allow_driver(
    driver: NodeDriver, socket_path: Path, action: str
) -> dict:
    """Run the Node allow-path driver against *socket_path*; return its result.

    Spawns ``node enforce_allow.mjs <native-client-module> <socket> <action>``
    with cwd = the SDK root (so the native binding resolves as the SDK loads it),
    bounded by :data:`DRIVER_TIMEOUT_SECONDS`. Returns the parsed JSON result on
    success; raises :class:`DriverFailed` if the driver reports the allowed
    action was blocked, exits non-zero, or times out (the process is killed).
    """
    proc = subprocess.run(
        [
            "node",
            str(driver.script),
            str(driver.native_client_module),
            str(socket_path),
            action,
        ],
        cwd=str(driver.sdk_dir),
        capture_output=True,
        text=True,
        timeout=DRIVER_TIMEOUT_SECONDS,
    )
    result = _parse_driver_result(proc.stdout)
    if proc.returncode != 0 or not result.get("ok"):
        raise DriverFailed(
            f"Node allow-path driver failed (exit {proc.returncode}): "
            f"{result.get('error', proc.stderr.strip() or 'unknown')}"
        )
    return result


def run_go_allow_driver(driver: GoDriver, socket_path: Path, action: str) -> dict:
    """Run the Go allow-path driver against *socket_path*; return its result.

    Copies the committed driver module into a private temp dir, rewrites its
    ``replace`` to point at the *located* go-sdk checkout (so an
    ``AASM_GO_SDK_DIR`` override works and the committed sibling-relative default
    is never mutated), then builds + runs it with ``go run`` under the
    ``aa_ffi_go`` cgo tag so it links the genuine FFI transport. Bounded by
    :data:`DRIVER_TIMEOUT_SECONDS`. Returns the parsed JSON result; raises
    :class:`DriverFailed` on a blocked action, non-zero exit, or timeout.
    """
    env = {
        **os.environ,
        # -mod=mod lets `go` resolve the local replace without a network
        # `go mod tidy`; the driver's deps are already pinned in go.sum.
        "GOFLAGS": "-mod=mod",
    }
    with tempfile.TemporaryDirectory(prefix="aaitest-go-allow-") as build_root:
        build_dir = Path(build_root)
        for name in ("go.mod", "go.sum", "enforce_allow.go"):
            shutil.copy2(driver.module_dir / name, build_dir / name)
        # Repoint the replace at the resolved (possibly env-overridden) SDK dir,
        # absolute so it does not depend on this temp dir's location.
        subprocess.run(
            [
                "go",
                "mod",
                "edit",
                "-replace",
                f"github.com/AI-agent-assembly/go-sdk={driver.sdk_dir.resolve()}",
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
            f"Go allow-path driver failed (exit {proc.returncode}): "
            f"{result.get('error', proc.stderr.strip() or 'unknown')}"
        )
    return result
