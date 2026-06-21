"""Locate and run the real-framework Node agent smoke drivers (AAASM-3525).

This is the Node analogue of :mod:`tests.live.sdk_drivers` for the *framework*
smoke tests: where ``sdk_drivers`` ships one synthetic allow-path event, this
module drives a **genuine agent on each supported Node framework** (LangChain.js,
LangGraph.js, OpenAI Agents, Vercel AI SDK, Mastra) through the SDK's governance
hooks against a **live** ``aa-runtime`` — the production ``SDK → aa-ffi →
aa-runtime`` path, not a mock.

It owns all the *justified-skip* decisions and does them **without launching
anything**, so a per-framework test can call the locator, translate a
:class:`FrameworkDriverUnavailable` into a clean ``pytest.skip``, and only then
spawn the driver — keeping the offline path (collection + locator logic) green
with no toolchain, exactly like the existing live tests.

Layout the drivers live under (committed, self-contained fixtures):

* ``drivers/node-frameworks/_governance.mjs`` — shared real-governance harness:
  builds a ``GatewayClient``-shaped client over the SDK's live native client.
* ``drivers/node-frameworks/zod3-frameworks/`` — LangChain.js, LangGraph.js,
  Vercel AI SDK, Mastra (all resolve ``zod`` 3).
* ``drivers/node-frameworks/zod4-frameworks/`` — OpenAI Agents (pins ``zod`` 4).

The two groups have **separate** ``node_modules`` because ``@openai/agents``
requires ``zod@^4`` while the others require ``zod@^3`` — a single tree would be
an unresolvable major conflict. Each group needs its framework deps installed
(``npm install`` in the group dir) and a ``native/aa-ffi-node`` symlink to the
SDK's native binding (so the SDK native client loads when a driver runs with
``cwd`` = the group dir). When either is absent the locator raises a justified
:class:`FrameworkDriverUnavailable` rather than a false green.

Why allow-path only: the live deny/block path is unprovable today
(AAASM-3000 IPC deadlock + AAASM-3021 pre-exec ``check()`` unwired); the
per-framework deny assertion is a strict xfail pinned on AAASM-3172, mirroring
the existing live E2E.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from tests.live.sdk_drivers import (
    NODE_SDK_DIR_ENV,
    DriverFailed,
    DriverUnavailable,
    _sibling_sdk_dir,
)

#: Where the framework driver fixtures live.
NODE_FRAMEWORKS_DIR = Path(__file__).resolve().parent / "drivers" / "node-frameworks"

#: How long a framework driver may run before we treat it as hung. A real
#: framework agent doing one governed tool call is bounded but slower than the
#: bare event driver, so this is generous-but-finite.
FRAMEWORK_DRIVER_TIMEOUT_SECONDS = 90.0

#: The supported Node frameworks and the (group dir, driver script) that drives a
#: real agent on each. The group dir is relative to NODE_FRAMEWORKS_DIR and owns
#: the framework deps; see the module docstring for the zod 3 / zod 4 split.
FRAMEWORK_DRIVERS: dict[str, tuple[str, str]] = {
    "langchain": ("zod3-frameworks", "langchain.mjs"),
    "langgraph": ("zod3-frameworks", "langgraph.mjs"),
    "vercel-ai": ("zod3-frameworks", "vercel-ai.mjs"),
    "mastra": ("zod3-frameworks", "mastra.mjs"),
    "openai-agents": ("zod4-frameworks", "openai-agents.mjs"),
}


class FrameworkDriverUnavailable(DriverUnavailable):
    """A framework driver cannot run because a prerequisite is absent.

    Subclasses :class:`DriverUnavailable` so the same skip-audit acceptance
    applies — it names the concrete missing piece (node, SDK, built SDK, the
    framework's installed deps, or the native-binding symlink) so a caller can
    ``pytest.skip(str(exc))`` without a Jira ref.
    """


@dataclass(frozen=True)
class FrameworkDriver:
    """A ready-to-run real-framework Node driver and the context to launch it.

    :param framework: the framework key (e.g. ``"langchain"``).
    :param group_dir: the fixture group dir (its cwd, so the framework packages
        and the SDK native-binding symlink both resolve there).
    :param script: the per-framework driver ``.mjs``.
    :param native_client_module: absolute path to the SDK's compiled
        ``dist/esm/native/client.js`` — the genuine SDK native client.
    """

    framework: str
    group_dir: Path
    script: Path
    native_client_module: Path


def _locate_sdk_native_client() -> Path:
    """Return the built SDK native client module, or raise a justified skip.

    Mirrors :func:`tests.live.sdk_drivers.locate_node_driver`'s SDK checks: a
    Node SDK checkout (sibling ``../node-sdk`` or ``AASM_NODE_SDK_DIR``) whose
    package is built (``dist/esm/native/client.js``) with the native binding
    present (``native/aa-ffi-node/index.cjs``).
    """
    sdk_dir = _sibling_sdk_dir(NODE_SDK_DIR_ENV, "node-sdk")
    if sdk_dir is None:
        raise FrameworkDriverUnavailable(
            "Node SDK checkout not found — clone node-sdk alongside this repo or "
            f"set {NODE_SDK_DIR_ENV} to run the Node framework smoke drivers"
        )
    native_client = sdk_dir / "dist" / "esm" / "native" / "client.js"
    if not native_client.is_file():
        raise FrameworkDriverUnavailable(
            "Node SDK is not built — run `pnpm build` to install the SDK dist in "
            "the node-sdk checkout (dist/esm/native/client.js is absent) to run "
            "the framework smoke drivers (AAASM-3525)"
        )
    binding = sdk_dir / "native" / "aa-ffi-node" / "index.cjs"
    if not binding.is_file():
        raise FrameworkDriverUnavailable(
            "Node SDK native binding not built — run `pnpm native:build` to "
            "install the binding in the node-sdk checkout "
            "(native/aa-ffi-node/index.cjs is absent) to run the framework smoke "
            "drivers (AAASM-3525)"
        )
    return native_client


def _ensure_native_symlink(group_dir: Path, sdk_dir: Path) -> None:
    """Make ``<group_dir>/native/aa-ffi-node`` point at the SDK's native binding.

    The drivers run with ``cwd`` = *group_dir* so the framework packages resolve
    from the group's own ``node_modules``; the SDK native client's binding loader
    then resolves ``${cwd}/native/aa-ffi-node/index.cjs``. We materialise that as
    a symlink to the SDK's ``native/aa-ffi-node`` so the genuine binding loads
    without copying it. Idempotent; tolerates an existing correct link.
    """
    target = sdk_dir / "native" / "aa-ffi-node"
    link = group_dir / "native" / "aa-ffi-node"
    if link.is_symlink() and link.resolve() == target.resolve():
        return
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.exists() or link.is_symlink():
        link.unlink()
    link.symlink_to(target)


def locate_framework_driver(framework: str) -> FrameworkDriver:
    """Locate the toolchain + built SDK + installed framework deps for *framework*.

    Checks, in order: a known framework key, ``node`` on ``PATH``, the built SDK
    native client (:func:`_locate_sdk_native_client`), the per-framework driver
    script, and the group's installed ``node_modules`` (i.e. ``npm install`` was
    run in the group dir). Ensures the native-binding symlink exists. Each
    missing piece raises a concrete, skip-audit-justified
    :class:`FrameworkDriverUnavailable`. Launches nothing.
    """
    if framework not in FRAMEWORK_DRIVERS:
        raise FrameworkDriverUnavailable(f"unknown Node framework: {framework!r}")
    if shutil.which("node") is None:
        raise FrameworkDriverUnavailable(
            "Node toolchain not available — install node to run the Node framework "
            "smoke drivers (AAASM-3525)"
        )

    native_client = _locate_sdk_native_client()
    sdk_dir = native_client.parents[3]  # <sdk>/dist/esm/native/client.js → <sdk>

    group_name, script_name = FRAMEWORK_DRIVERS[framework]
    group_dir = NODE_FRAMEWORKS_DIR / group_name
    script = group_dir / script_name
    if not script.is_file():
        raise FrameworkDriverUnavailable(
            f"{framework} driver script is missing ({script}) — the live driver "
            "cannot run (AAASM-3525)"
        )
    if not (group_dir / "node_modules").is_dir():
        raise FrameworkDriverUnavailable(
            f"{framework} framework deps are not installed — run `npm install` in "
            f"{group_dir} to run the {framework} live smoke driver (AAASM-3525)"
        )

    _ensure_native_symlink(group_dir, sdk_dir)

    return FrameworkDriver(
        framework=framework,
        group_dir=group_dir,
        script=script,
        native_client_module=native_client,
    )


def _parse_driver_result(stdout: str) -> dict:
    """Parse a framework driver's last stdout line as the JSON result object.

    Drivers print a single-line JSON object; we read the last non-empty line so a
    framework's own incidental output does not confuse the parse.
    """
    last = ""
    for line in stdout.splitlines():
        if line.strip():
            last = line.strip()
    if not last:
        raise DriverFailed("framework driver produced no JSON result on stdout")
    try:
        return json.loads(last)
    except json.JSONDecodeError as exc:
        raise DriverFailed(f"framework driver result was not valid JSON: {last!r}") from exc


def run_framework_driver(driver: FrameworkDriver, socket_path: Path) -> dict:
    """Run a real-framework driver against *socket_path*; return its result.

    Spawns ``node <driver.script> <native-client-module> <socket>`` with
    ``cwd`` = the fixture group dir (so the framework packages and the SDK native
    binding both resolve), bounded by
    :data:`FRAMEWORK_DRIVER_TIMEOUT_SECONDS`. Returns the parsed JSON result on
    success; raises :class:`DriverFailed` if the driver reports a broken allow
    path (``ok`` is false / a governed tool did not run), exits non-zero, or
    times out.
    """
    proc = subprocess.run(
        [
            "node",
            str(driver.script),
            str(driver.native_client_module),
            str(socket_path),
        ],
        cwd=str(driver.group_dir),
        capture_output=True,
        text=True,
        timeout=FRAMEWORK_DRIVER_TIMEOUT_SECONDS,
        env=os.environ.copy(),
    )
    result = _parse_driver_result(proc.stdout)
    if proc.returncode != 0 or not result.get("ok"):
        raise DriverFailed(
            f"{driver.framework} framework allow-path driver failed "
            f"(exit {proc.returncode}): "
            f"{result.get('error', proc.stderr.strip() or 'unknown')}"
        )
    return result
