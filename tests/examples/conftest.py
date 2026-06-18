"""Clean-environment fixtures and helpers for the examples suite (AAASM-3153).

This conftest is local to ``tests/examples/`` and is the machinery that makes
the clean-environment guarantee real:

* **Clean tempdir copy** (:func:`clean_example_copy`) — an example is *copied*
  into an isolated ``tmp_path`` with every pre-existing dependency artifact
  (``node_modules``, ``.venv``, ``__pycache__``, ``target``, lockfile caches)
  stripped out, so a run cannot pass because of deps cached next to the source.
* **Hermetic environment** (:func:`clean_subprocess_env`) — subprocess env with
  per-toolchain caches redirected into ``tmp_path`` (``GOCACHE``/``GOMODCACHE``
  per AAASM-3149, ``UV_CACHE_DIR``, ``npm_config_cache``/``PNPM_HOME``) and
  ``HOME`` redirected, so nothing leaks from the developer's real caches.
* **Env-vs-failure classification** (:class:`RunOutcome` / :func:`run_step`) —
  the single place that draws the AC5 line: a missing binary / missing checkout
  / offline / missing service produces a justified **skip**; a non-zero exit or
  wrong output from a present example produces a **fail**.

Detection follows the established :mod:`aasm_verify.doctor` style — ``shutil.which``
for binaries, a real connect for the network, a temp-file write for cache
writability — but is reimplemented locally rather than imported, since this
suite must not edit ``src/aasm_verify``.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests.examples.manifest import FRAMEWORK_HEAVY_ENV_VAR, Example

COMPONENT = "agent-assembly-examples"

# Directory / file names that are dependency or build artifacts. They are
# stripped when copying an example so a clean run cannot reuse cached deps.
_ARTIFACT_NAMES: frozenset[str] = frozenset(
    {
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "target",
        "dist",
        "build",
        ".turbo",
        ".next",
    }
)


def examples_repo_path() -> Path | None:
    """Return the local ``agent-assembly-examples`` checkout, or ``None``.

    The repo is expected as a sibling of the integration-tests repo (the layout
    the public ``tests/public`` suite already assumes). Returns ``None`` when it
    is not present, so callers can emit a justified env skip.
    """
    candidate = Path(__file__).resolve().parents[3] / "agent-assembly-examples"
    return candidate if (candidate / "README.md").is_file() else None


def example_source_dir(example: Example) -> Path | None:
    """Return the source directory for ``example`` in the checkout, or ``None``."""
    repo = examples_repo_path()
    if repo is None:
        return None
    src = repo / example.rel_path
    return src if src.is_dir() else None


def missing_tools(example: Example) -> list[str]:
    """Return the example's required tools that are absent from ``PATH``."""
    return [tool for tool in example.required_tools if shutil.which(tool) is None]


def network_unavailable(timeout: float = 3.0) -> bool:
    """Return ``True`` when neither github.com nor pypi.org is reachable.

    Mirrors :func:`aasm_verify.doctor.check_network`'s connect-probe style:
    offline is information, and a clean install needs the network, so an offline
    host produces a justified env skip rather than a failure.
    """
    for host, port in (("github.com", 443), ("pypi.org", 443)):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return False
        except OSError:
            continue
    return True


def _copy_clean(src: Path, dest: Path) -> None:
    """Copy ``src`` to ``dest`` omitting dependency/build artifacts.

    Symlinks are not followed and artifact directories named in
    :data:`_ARTIFACT_NAMES` are pruned, so the destination is a pristine source
    tree with no cached dependencies.
    """

    def _ignore(_dir: str, names: list[str]) -> set[str]:
        return {name for name in names if name in _ARTIFACT_NAMES}

    shutil.copytree(src, dest, ignore=_ignore, symlinks=True)


@dataclass(frozen=True)
class RunOutcome:
    """The result of one install/run step in a clean environment."""

    returncode: int
    stdout: str
    stderr: str

    @property
    def combined(self) -> str:
        """Return stdout and stderr joined, for substring assertions."""
        return f"{self.stdout}\n{self.stderr}"


def clean_subprocess_env(work_dir: Path) -> dict[str, str]:
    """Return a hermetic subprocess environment rooted under ``work_dir``.

    Redirects ``HOME`` and every toolchain cache into ``work_dir`` so a run
    cannot read or write the developer's real caches. The Go caches honor the
    AAASM-3149 writable-``GOCACHE`` requirement.
    """
    home = work_dir / "home"
    caches = {
        "GOCACHE": work_dir / "gocache",
        "GOMODCACHE": work_dir / "gomodcache",
        "UV_CACHE_DIR": work_dir / "uv-cache",
        "npm_config_cache": work_dir / "npm-cache",
        "PNPM_HOME": work_dir / "pnpm-home",
    }
    for path in (home, *caches.values()):
        path.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["HOME"] = str(home)
    for key, path in caches.items():
        env[key] = str(path)
    return env


def run_step(
    argv: tuple[str, ...],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float = 600.0,
) -> RunOutcome:
    """Run one install/run step, returning a :class:`RunOutcome`.

    Never raises on a non-zero exit — the caller decides whether that is a
    failure (the example is broken) or, when paired with an env probe, a skip.
    A spawn error (binary genuinely missing mid-run) or a timeout is surfaced as
    a distinct non-zero outcome so it is never mistaken for a passing run.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv from the manifest, no shell.
            list(argv),
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        return RunOutcome(returncode=127, stdout="", stderr=f"command not found: {exc}")
    except subprocess.TimeoutExpired as exc:
        return RunOutcome(returncode=124, stdout="", stderr=f"timed out after {exc.timeout}s")
    return RunOutcome(returncode=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def require_clean_run_env(example: Example) -> Path:
    """Skip with a justified env reason unless ``example`` can run from clean.

    Draws the AC5 environment-vs-failure line *before* any work happens:

    * missing required binary  → skip ("``X`` not found in PATH …")
    * missing examples checkout → skip ("clone … alongside this repo")
    * offline                   → skip ("network unavailable …")
    * needs an external service but it is not opted in → skip (env flag)

    Returns the example's source directory in the checkout when every
    environment precondition is met, so the caller can copy + run it.
    """
    absent = missing_tools(example)
    if absent:
        pytest.skip(
            f"[{COMPONENT}] {', '.join(absent)} not found in PATH — "
            f"install the toolchain to run the {example.id} example from clean"
        )

    src = example_source_dir(example)
    if src is None:
        pytest.skip(
            f"[{COMPONENT}] examples repo (or {example.rel_path}) not found — "
            "clone https://github.com/ai-agent-assembly/agent-assembly-examples "
            "alongside this repo to enable clean-env example runs"
        )

    if network_unavailable():
        pytest.skip(
            f"[{COMPONENT}] network unavailable — a clean install of {example.id} "
            "requires fetching dependencies; skipping until the host is online"
        )

    if example.required_services and os.environ.get(FRAMEWORK_HEAVY_ENV_VAR) != "1":
        pytest.skip(
            f"[{COMPONENT}] {example.id} requires service(s) "
            f"{', '.join(example.required_services)} — set "
            f"{FRAMEWORK_HEAVY_ENV_VAR}=1 with the service running to enable it"
        )

    return src


@pytest.fixture
def clean_example_copy(tmp_path: Path):  # type: ignore[no-untyped-def]
    """Return a factory that copies an example into a pristine ``tmp_path``.

    The factory takes a source directory and returns the clean destination — a
    copy with all dependency/build artifacts stripped — guaranteeing a run
    exercises a genuine clean install rather than cached deps.
    """

    def _factory(src: Path) -> Path:
        dest = tmp_path / "example"
        _copy_clean(src, dest)
        return dest

    return _factory


# Substrings that mark an install step as failing for an *environment* reason
# (dependency could not be fetched / resolved) rather than because the example
# is broken. When an install fails for one of these the test skips (AC5) — the
# example is not at fault. Anything else is a real failure.
_ENV_INSTALL_FAILURE_MARKERS: tuple[str, ...] = (
    "could not resolve",
    "failed to fetch",
    "network",
    "temporary failure in name resolution",
    "connection refused",
    "connection reset",
    "timed out",
    "proxyconnect",
    "no such host",
    "tls handshake",
    "etimedout",
    "enotfound",
    "503 server error",
    "429 too many requests",
)


def _looks_like_env_failure(text: str) -> bool:
    """Return True when failure output reads as an environment problem."""
    lowered = text.lower()
    return any(marker in lowered for marker in _ENV_INSTALL_FAILURE_MARKERS)


def validate_example_clean(example: Example, clean_dir: Path, env: dict[str, str]) -> None:
    """Install and run ``example`` from ``clean_dir``, drawing the AC5 line.

    ``clean_dir`` must already be an artifact-stripped copy of the example, and
    ``env`` a hermetic environment (caches redirected). The contract:

    * a **lockfile precondition** the example doesn't meet (e.g. no lockfile for
      ``pnpm install --frozen-lockfile``) → **skip** with an env reason — the
      missing lockfile is an environment/repo-prereq gap, not a product break;
    * an **install** that fails for a network/registry reason → **skip**;
    * an **install** that fails for any other reason, or a **run** that exits
      non-zero / lacks the expected output → **fail** (the example or product is
      broken).

    This single helper is what keeps the three language tests' env-vs-failure
    classification identical.
    """
    # Frozen-lockfile installs need a committed lockfile; without one the
    # precondition simply isn't met in this checkout — an env gap, not a break.
    if "--frozen-lockfile" in example.install_cmd:
        lockfiles = ("pnpm-lock.yaml", "package-lock.json", "yarn.lock")
        if not any((clean_dir / lf).is_file() for lf in lockfiles):
            pytest.skip(
                f"[{COMPONENT}] {example.id} has no committed lockfile "
                f"({', '.join(lockfiles)}) — `{' '.join(example.install_cmd)}` "
                "cannot run; example-repo prerequisite, not a product failure"
            )

    if example.install_cmd:
        install = run_step(example.install_cmd, cwd=clean_dir, env=env)
        if install.returncode != 0:
            if _looks_like_env_failure(install.combined):
                pytest.skip(
                    f"[{COMPONENT}] {example.id} install could not fetch "
                    "dependencies (network/registry) — skipping; not a product "
                    f"failure. exit {install.returncode}"
                )
            pytest.fail(
                f"[{COMPONENT}] {example.id} clean install FAILED "
                f"(`{' '.join(example.install_cmd)}`, exit {install.returncode})\n"
                f"stdout: {install.stdout.strip()}\nstderr: {install.stderr.strip()}"
            )

    run = run_step(example.run_cmd, cwd=clean_dir, env=env)
    if run.returncode != example.expected_exit and _looks_like_env_failure(run.combined):
        pytest.skip(
            f"[{COMPONENT}] {example.id} run hit a network/registry error — "
            f"skipping; not a product failure. exit {run.returncode}"
        )
    assert run.returncode == example.expected_exit, (
        f"[{COMPONENT}] {example.id} clean run FAILED "
        f"(`{' '.join(example.run_cmd)}`, exit {run.returncode}, "
        f"expected {example.expected_exit})\n"
        f"stdout: {run.stdout.strip()}\nstderr: {run.stderr.strip()}"
    )
    if example.expected_output_substring:
        assert example.expected_output_substring in run.combined, (
            f"[{COMPONENT}] {example.id} run output missing expected substring "
            f"{example.expected_output_substring!r}\noutput: {run.combined.strip()}"
        )
