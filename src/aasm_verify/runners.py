"""Per-area test runners for the public verification orchestrator.

Each verification *area* maps to a real check:

* ``runtime``/``sdk``/``examples``/``conformance`` run the matching pytest
  marker in ``tests/public`` (the suite skips gracefully when the built
  artifact — ``aasm`` binary, SDK package, examples checkout — is absent).
* ``install`` runs the Rust build smoke script (no pytest marker exists for it).
* In ``release`` mode every area runs the ``release`` marker, driven by
  ``AASM_RELEASE_VERSION``.

Runners shell out so exit codes and environment isolation are explicit; the
caller propagates a non-zero exit to fail the workflow, and the pytest JSON
report (when requested) feeds ``scripts/summarize-run.sh``.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence

from aasm_verify import installers
from aasm_verify.refs import ResolvedRefs

# All selectable areas, in display order.
AREAS: tuple[str, ...] = ("runtime", "sdk", "examples", "install", "conformance")

# The install area has no pytest marker; it runs the Rust build smoke script.
_INSTALL_SMOKE_SCRIPT: str = "tests/install/smoke-test-rust-build.sh"


def resolve_areas(area: str) -> list[str]:
    """Expand the ``--area`` selector into a concrete list of areas.

    ``"all"`` expands to every area; any other value must be a known area.
    """
    if area == "all":
        return list(AREAS)
    if area not in AREAS:
        raise ValueError(f"Unknown area {area!r}. Valid areas: all, {', '.join(AREAS)}")
    return [area]


def _build_env(refs: ResolvedRefs) -> dict[str, str]:
    """Construct the subprocess environment for a verification run."""
    env = dict(os.environ)
    if refs.mode == "release":
        env["AASM_INSTALL_MODE"] = "release"
        # In release mode the per-ecosystem version is carried on the sdk fields.
        env["AASM_RELEASE_VERSION"] = refs.python_sdk
    else:
        env["AASM_INSTALL_MODE"] = "source"
    # Ref hints consumed by the bash smoke scripts.
    env["AA_REF"] = refs.agent_assembly
    env["PYTHON_SDK_REF"] = refs.python_sdk
    env["NODE_SDK_REF"] = refs.node_sdk
    env["GO_SDK_REF"] = refs.go_sdk
    env["EXAMPLES_REF"] = refs.examples
    return env


# Markers accepted by ``_pytest_command``. The marker is interpolated into the
# pytest ``-m`` expression, so it must come from this fixed allowlist — never
# straight from a CLI arg or env var — to keep untrusted text out of the spawned
# command (S8705: OS-command argument injection / sandbox escape).
#
# This is a name->literal mapping rather than a set so the value that actually
# reaches the subprocess argv is *fetched from this constant*, not the caller's
# parameter: the marker passed in is used only as a lookup key, and the string
# placed in ``cmd`` originates here. That makes the sanitization data-flow
# explicit (a taint analyzer sees the argv value sourced from a constant, not
# from untrusted input).
_ALLOWED_MARKERS: dict[str, str] = {name: name for name in (*AREAS, "release")}


def _pytest_command(marker: str, json_report: str | None) -> list[str]:
    """Build a ``pytest -m <marker>`` command, optionally emitting a JSON report.

    *marker* must be a key of :data:`_ALLOWED_MARKERS`; anything else is rejected
    before it can reach the subprocess argv. The marker string placed in the argv
    is the *constant* mapped value, never the caller-supplied parameter, so no
    untrusted text can flow into the spawned command (S8705).
    """
    safe_marker = _ALLOWED_MARKERS.get(marker)
    if safe_marker is None:
        raise ValueError(f"refusing to run pytest with unknown marker {marker!r}")
    cmd = [sys.executable, "-m", "pytest", "-m", safe_marker, "-v"]
    if json_report:
        cmd += ["--json-report", f"--json-report-file={json_report}"]
    return cmd


def prepare_area_artifacts(refs: ResolvedRefs, areas: Sequence[str]) -> None:
    """Install the artifacts the selected *areas* assert against (AAASM-4736).

    The public pytest areas skip when their artifact is absent, so a run that
    never installs anything goes green without exercising the product. This
    installs what it can up front and exposes it on ``os.environ`` so each
    per-area pytest subprocess (spawned by :func:`run_area` from a copy of
    ``os.environ``) inherits it.

    Best-effort and source-mode only: release mode installs published packages in
    the workflow, and an area whose toolchain is genuinely absent stays skipped
    (unchanged) rather than hard-failing. Wires the ``runtime`` area (the ``aasm``
    CLI, exposed on ``PATH``), the ``sdk`` area (the ``python-sdk``
    ``agent_assembly`` package installed into this interpreter and its checkout
    exposed via ``AASM_PYTHON_SDK_DIR``, the built ``node-sdk`` checkout exposed
    via ``AASM_NODE_SDK_DIR``, and the ``go-sdk`` checkout exposed via
    ``AASM_GO_SDK_DIR``), and the ``examples`` area (the
    examples checkout, exposed via ``AASM_EXAMPLES_DIR``).
    """
    if refs.mode == "release":
        return
    if "runtime" in areas:
        bindir = installers.install_aasm_cli(refs.agent_assembly)
        if bindir:
            os.environ["PATH"] = bindir + os.pathsep + os.environ.get("PATH", "")
    if "sdk" in areas:
        # Installs agent_assembly into this interpreter; the per-area pytest
        # subprocess (same sys.executable) imports it — no env var needed for
        # the import. But the strict cross-SDK parity probe
        # (tests/contract/test_enforcement_mode_parity.py) parses the SDK
        # *source* via AASM_PYTHON_SDK_DIR, so expose the checkout dir the same
        # way node/go do or the Python side of the parity guard resolves to
        # None (AAASM-4845).
        python_dir = installers.install_python_sdk(refs.python_sdk)
        if python_dir:
            os.environ["AASM_PYTHON_SDK_DIR"] = python_dir
        # node-sdk: built pure-JS checkout, exposed via AASM_NODE_SDK_DIR so the
        # node smoke runs with its cwd inside the package and resolves
        # @agent-assembly/sdk by self-reference (AAASM-4774).
        node_dir = installers.install_node_sdk(refs.node_sdk)
        if node_dir:
            os.environ["AASM_NODE_SDK_DIR"] = node_dir
        # go-sdk: source checkout, exposed via AASM_GO_SDK_DIR so the Go smoke's
        # source acquisition runs instead of skipping (AAASM-4774).
        go_dir = installers.install_go_sdk(refs.go_sdk)
        if go_dir:
            os.environ["AASM_GO_SDK_DIR"] = go_dir
    if "examples" in areas:
        examples_dir = installers.install_examples(refs.examples)
        if examples_dir:
            os.environ["AASM_EXAMPLES_DIR"] = examples_dir


def run_area(
    refs: ResolvedRefs,
    area: str,
    *,
    json_report: str | None = None,
    _runner: object | None = None,
) -> int:
    """Run the verification for a single *area*. Returns the process exit code.

    ``_runner`` is an injection seam for tests; it defaults to ``subprocess.run``.
    """
    runner = _runner if _runner is not None else subprocess.run
    env = _build_env(refs)

    if refs.mode == "release":
        cmd = _pytest_command("release", json_report)
    elif area == "install":
        cmd = ["bash", _INSTALL_SMOKE_SCRIPT]
    else:
        cmd = _pytest_command(area, json_report)

    print(f"\n▶ area '{area}' ({refs.mode}): {' '.join(cmd)}", flush=True)
    result = runner(cmd, env=env)  # type: ignore[operator]
    return int(result.returncode)


def run_areas(
    refs: ResolvedRefs,
    areas: Sequence[str],
    *,
    json_report: str | None = None,
    _runner: object | None = None,
) -> int:
    """Run every area in *areas*. Returns 0 only if all areas pass.

    Areas run sequentially; a failure does not stop later areas (so a single
    invocation surfaces every failing area), but the aggregate exit is non-zero.
    """
    failures: list[str] = []
    for area in areas:
        code = run_area(refs, area, json_report=json_report, _runner=_runner)
        if code != 0:
            failures.append(area)
            print(f"✖ area '{area}' failed (exit {code})", file=sys.stderr, flush=True)
        else:
            print(f"✓ area '{area}' passed", flush=True)

    if failures:
        print(f"\nVerification failed in: {', '.join(failures)}", file=sys.stderr)
        return 1
    print("\nVerification passed for all selected areas.")
    return 0
