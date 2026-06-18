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
_ALLOWED_MARKERS: frozenset[str] = frozenset({*AREAS, "release"})


def _pytest_command(marker: str, json_report: str | None) -> list[str]:
    """Build a ``pytest -m <marker>`` command, optionally emitting a JSON report.

    *marker* must be one of :data:`_ALLOWED_MARKERS`; anything else is rejected
    before it can reach the subprocess argv.
    """
    if marker not in _ALLOWED_MARKERS:
        raise ValueError(f"refusing to run pytest with unknown marker {marker!r}")
    cmd = [sys.executable, "-m", "pytest", "-m", marker, "-v"]
    if json_report:
        cmd += ["--json-report", f"--json-report-file={json_report}"]
    return cmd


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
