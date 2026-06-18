"""Shared pytest fixtures for public integration tests."""

from __future__ import annotations

import importlib.util
import os
import platform
import shutil
import warnings

import pytest

from aasm_verify import skip_audit


class UnjustifiedSkipWarning(UserWarning):
    """A test skipped without an env requirement or a linked Jira issue.

    Integration suites legitimately skip when a build artifact, binary, or
    release version is absent — but only when the skip *reason says so*. An
    un-justified skip silently erodes coverage, so we surface it (and, under
    strict mode, fail the run via the AAASM-3155 reporting check).
    """


_UNJUSTIFIED_SKIPS_KEY = pytest.StashKey[list]()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):  # type: ignore[no-untyped-def]
    """Audit skip reasons: record skips that name no env req or Jira ref.

    Additive and non-fatal — it never changes a test's pass/fail/skip outcome
    and never raises (so it is safe under ``-W error``). Offenders are stashed
    on the session and surfaced once in the terminal summary; the hard
    strict-mode gate (``AASM_VERIFY_STRICT=1``) lives in the report generator,
    which fails the run on the same un-justified skips.
    """
    outcome = yield
    report = outcome.get_result()
    if not report.skipped:
        return
    if report.when not in ("call", "setup"):
        return
    reason = _skip_reason_text(report)
    if skip_audit.is_justified(reason):
        return
    stash = item.session.stash
    offenders = stash.setdefault(_UNJUSTIFIED_SKIPS_KEY, [])
    if not any(n == report.nodeid for n, _ in offenders):
        offenders.append((report.nodeid, reason))


def pytest_terminal_summary(terminalreporter) -> None:  # type: ignore[no-untyped-def]
    """Report any un-justified skips collected during the run.

    Emits an :class:`UnjustifiedSkipWarning` per offender so the signal is
    visible in the warnings summary without risking a hookwrapper teardown
    crash under ``-W error``.
    """
    offenders = terminalreporter._session.stash.get(_UNJUSTIFIED_SKIPS_KEY, [])
    for nodeid, reason in offenders:
        warnings.warn(
            f"un-justified skip {nodeid}: {reason or '<no reason given>'} — "
            "a skip reason must name an environment requirement "
            "(binary/package/env var) or a Jira issue (AAASM-NNN).",
            UnjustifiedSkipWarning,
            stacklevel=2,
        )


def _skip_reason_text(report) -> str:  # type: ignore[no-untyped-def]
    """Extract the skip reason string from a pytest TestReport."""
    longrepr = getattr(report, "longrepr", None)
    # Skips serialize as a (file, lineno, "Skipped: <reason>") tuple.
    if isinstance(longrepr, (list, tuple)) and len(longrepr) >= 3:
        text = str(longrepr[2])
        prefix = "Skipped: "
        return text[len(prefix) :].strip() if text.startswith(prefix) else text.strip()
    return str(longrepr).strip() if longrepr else ""


@pytest.fixture(scope="session")
def install_mode() -> str:
    """Return the active installation mode from the environment (default: source)."""
    return os.environ.get("AASM_INSTALL_MODE", "source")


def skip_if_binary_missing(binary: str) -> None:
    """Skip the current test when *binary* is not found in PATH."""
    if shutil.which(binary) is None:
        pytest.skip(f"{binary!r} not found in PATH — install the binary to run this test")


def skip_if_package_missing(package: str) -> None:
    """Skip the current test when the Python *package* is not importable."""
    try:
        spec = importlib.util.find_spec(package)
        if spec is None:
            pytest.skip(f"Python package {package!r} not installed")
    except ModuleNotFoundError:
        pytest.skip(f"Python package {package!r} not installed (parent package absent)")


def release_version() -> str | None:
    """Return AASM_RELEASE_VERSION from environment, or None when unset."""
    return os.environ.get("AASM_RELEASE_VERSION")


def platform_asset_suffix() -> str:
    """Return the expected GitHub Release binary asset suffix for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        arch = "x86_64" if machine in ("x86_64", "amd64") else "aarch64"
        return f"{arch}-unknown-linux-gnu.tar.gz"
    if system == "darwin":
        arch = "aarch64" if machine in ("arm64", "aarch64") else "x86_64"
        return f"{arch}-apple-darwin.tar.gz"
    return f"{system}-{machine}.tar.gz"
