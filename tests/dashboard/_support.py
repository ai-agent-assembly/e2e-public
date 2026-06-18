"""Test-local helpers for the dashboard production smoke suite (AAASM-3154).

Kept out of ``src/aasm_verify`` because they touch only this suite. Two
concerns live here:

* **Environment resolution + skip-guarding** — locate the dashboard checkout
  (configurable via ``AASM_DASHBOARD_DIR``), detect the ``pnpm``/``node``
  toolchain, and decide whether a real ``pnpm build`` may run. Every "cannot
  run" path yields a *justified* skip reason (naming the missing binary / env
  var / Jira ref) so the repo's skip-audit (``aasm_verify.skip_audit``) never
  flags it as an un-justified coverage gap.

* **Build-result classification** — the contract at the heart of AC1/AC4: a
  ``pnpm build`` that exits non-zero is a HARD failure, never a skip. The
  classifier (:func:`classify_build_result`) is pure and offline-testable, so
  the regression-catch test can prove that AAASM-3142's non-zero build exit
  *would be* caught without needing a live toolchain.

Why opt-in: a plain ``pytest`` run must not shell out to ``pnpm install`` +
``pnpm build`` (slow, network, side effects). The build only runs when
``AASM_RUN_DASHBOARD=1`` is set *and* the toolchain + checkout are present;
otherwise it skips with a justified reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

# Opt-in toggle: a real ``pnpm install`` + ``pnpm build`` only runs when this
# is set to "1". Unset (the default) → the build-running tests skip cleanly so
# a normal `pytest` run never shells out to the JS toolchain.
RUN_ENV_VAR = "AASM_RUN_DASHBOARD"

# Override for the dashboard checkout location. When unset the default sibling
# path (``<repo-parent>/agent-assembly/dashboard``) is used.
DASHBOARD_DIR_ENV_VAR = "AASM_DASHBOARD_DIR"

# Binaries the production build path needs on PATH.
REQUIRED_TOOLS = ("pnpm", "node")


def default_dashboard_dir() -> Path:
    """Return the default sibling dashboard checkout path.

    This file lives at ``<repo>/tests/dashboard/_support.py``; the dashboard is
    a sibling of the repo, so it resolves to
    ``<repo-parent>/agent-assembly/dashboard``.
    """
    repo_root = Path(__file__).resolve().parents[2]
    return repo_root.parent / "agent-assembly" / "dashboard"


def resolve_dashboard_dir() -> Path:
    """Resolve the dashboard checkout dir, honoring ``AASM_DASHBOARD_DIR``.

    Returns the override path when the env var is set (even if it does not
    exist — existence is checked separately so the caller can emit a justified
    skip naming the env var), else the default sibling path.
    """
    override = os.environ.get(DASHBOARD_DIR_ENV_VAR)
    if override:
        return Path(override).expanduser()
    return default_dashboard_dir()


def missing_tools() -> list[str]:
    """Return the required build tools that are absent from PATH."""
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def dashboard_skip_reason() -> str | None:
    """Return a justified skip reason when the build cannot run, else ``None``.

    Ordered so the most actionable prerequisite is reported first: opt-in →
    checkout present → toolchain present. Each reason names the concrete env
    var / binary / Jira ref so ``aasm_verify.skip_audit`` treats it as
    justified (an environment requirement), never an un-justified skip.
    """
    if os.environ.get(RUN_ENV_VAR) != "1":
        return (
            "dashboard production build is opt-in — set AASM_RUN_DASHBOARD=1 to run "
            "the pnpm build smoke check (AAASM-3154)"
        )
    dash = resolve_dashboard_dir()
    if not dash.is_dir():
        return (
            "dashboard checkout not found — set AASM_DASHBOARD_DIR (AAASM-3154); "
            f"looked at {dash}"
        )
    absent = missing_tools()
    if absent:
        return (
            f"required tool(s) not found in PATH: {', '.join(absent)} — install "
            "pnpm + node to run the dashboard production build (AAASM-3154)"
        )
    return None


class BuildVerdict(Enum):
    """Classification of a ``pnpm build`` run outcome.

    * :attr:`PASS` — build exited 0; production bundle was emitted.
    * :attr:`HARD_FAIL` — build exited non-zero; this is a real regression
      (AAASM-3142 class) and MUST fail the test, never skip.
    """

    PASS = "pass"
    HARD_FAIL = "hard_fail"


@dataclass(frozen=True)
class BuildResult:
    """The outcome of a ``pnpm build`` invocation, as the classifier sees it."""

    returncode: int
    # Tail of stderr/stdout kept for the failure message. Never a full log
    # dump — summaries in this public repo must stay sanitized.
    stderr_tail: str = ""


def classify_build_result(result: BuildResult) -> BuildVerdict:
    """Classify a build result as PASS or HARD_FAIL.

    The AC1/AC4 contract in one place: a zero exit is a pass; **any** non-zero
    exit is a hard failure (the AAASM-3142 build break exits 2, so it lands
    here). Environment-missing conditions are handled *before* a build runs
    (see :func:`dashboard_skip_reason`) and never reach this classifier, so a
    non-zero exit here is unambiguously a regression.
    """
    if result.returncode == 0:
        return BuildVerdict.PASS
    return BuildVerdict.HARD_FAIL


def _tail(text: str, *, limit: int = 2000) -> str:
    """Return the last *limit* chars of *text* (keeps failure msgs bounded)."""
    text = text.strip()
    return text if len(text) <= limit else text[-limit:]


def run_pnpm(args: list[str], *, cwd: Path, timeout: int) -> BuildResult:
    """Run a ``pnpm`` subcommand in *cwd* and return its :class:`BuildResult`.

    Captures output (kept off the test log unless a failure needs it) and
    bounds the run with *timeout* so a hung install/build does not wedge the
    suite. A timeout surfaces as a non-zero result so the classifier treats it
    as a hard failure rather than a silent pass.
    """
    try:
        proc = subprocess.run(
            ["pnpm", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        out = exc.stderr or exc.stdout or ""
        tail = out.decode() if isinstance(out, bytes) else (out or "")
        return BuildResult(returncode=124, stderr_tail=_tail(tail))
    combined = proc.stderr or proc.stdout or ""
    return BuildResult(returncode=proc.returncode, stderr_tail=_tail(combined))


def built_assets_present(dashboard_dir: Path, expected: tuple[str, ...]) -> list[str]:
    """Return the *expected* ``dist/`` entries that are missing after a build.

    An empty list means every expected production asset (the HTML entry point
    and the hashed ``assets/`` bundle dir) exists — the AC2 static-output
    check. A non-empty list names what the build failed to emit.
    """
    dist = dashboard_dir / "dist"
    return [name for name in expected if not (dist / name).exists()]
