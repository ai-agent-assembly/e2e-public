"""Dashboard production build smoke checks (AAASM-3154).

Two layers, mirroring the install-matrix suite's offline/online split:

* **Offline (always runs):** the build-result classifier wiring collects and
  the AC4 regression-catch holds — a simulated non-zero ``pnpm build`` exit
  (the AAASM-3142 build break) is classified as a HARD failure, never a skip.
  This proves the catch contract without a live toolchain.

* **Online (skip-guarded, opt-in):** when ``AASM_RUN_DASHBOARD=1`` and the
  toolchain + dashboard checkout are present, an actual ``pnpm install`` +
  ``pnpm build`` runs. A non-zero build exit is a HARD test failure (AC1); the
  built ``dist/`` static assets are then asserted to exist (AC2). A missing
  toolchain / absent checkout / not-opted-in run skips with a justified reason.
"""

from __future__ import annotations

import pytest

from tests.dashboard import _support
from tests.dashboard.manifest import EXPECTED_BUILD_ASSETS
from tests.dashboard._support import (
    BuildResult,
    BuildVerdict,
    classify_build_result,
)

# Bounds for the opt-in online build. Install can pull packages; build runs
# tsc + vite. Generous so a slow first install does not flake, but bounded so a
# hung run surfaces as a (hard) failure rather than wedging the suite.
_INSTALL_TIMEOUT_S = 600
_BUILD_TIMEOUT_S = 600


# --------------------------------------------------------------------------- #
# Offline: classifier wiring + AC4 regression-catch (always runs)
# --------------------------------------------------------------------------- #


def test_classifier_passes_on_zero_exit() -> None:
    """A zero-exit build is classified PASS."""
    assert classify_build_result(BuildResult(returncode=0)) is BuildVerdict.PASS


def test_ac4_nonzero_build_exit_is_hard_failure() -> None:
    """AC4: a non-zero ``pnpm build`` exit is classified HARD_FAIL, not a skip.

    AAASM-3142's build break exits 2 (tsc errors before vite emits). This
    asserts that such an exit is classified as a hard failure — i.e. *would be
    caught* by the online smoke test — without needing a live toolchain.
    """
    aaasm_3142_exit = 2
    verdict = classify_build_result(BuildResult(returncode=aaasm_3142_exit))
    assert verdict is BuildVerdict.HARD_FAIL


def test_build_timeout_is_hard_failure() -> None:
    """A timed-out build (synthetic exit 124) is a hard failure, not a pass."""
    assert classify_build_result(BuildResult(returncode=124)) is BuildVerdict.HARD_FAIL


def test_skip_reason_is_justified_when_present() -> None:
    """Any skip reason the suite emits is non-empty (skip-audit justified).

    The reason always names an env var / binary / Jira ref, so the repo's
    skip-audit never flags the dashboard skips as un-justified.
    """
    reason = _support.dashboard_skip_reason()
    # In a default (not-opted-in) run a reason is always present; if a CI host
    # *is* fully set up, None is acceptable (the build runs instead).
    if reason is not None:
        assert reason.strip()
        assert "AAASM-3154" in reason or "PATH" in reason


def test_expected_assets_list_drives_static_check() -> None:
    """The AC2 static-asset expectation is wired from the manifest."""
    assert "index.html" in EXPECTED_BUILD_ASSETS


# --------------------------------------------------------------------------- #
# Online: actual pnpm build (skip-guarded, opt-in via AASM_RUN_DASHBOARD=1)
# --------------------------------------------------------------------------- #


def test_pnpm_build_succeeds_and_emits_assets() -> None:
    """AC1 + AC2: run ``pnpm install`` + ``pnpm build``; a non-zero build fails.

    Skips (justified) when not opted-in or when the toolchain / checkout is
    absent. When it runs: a non-zero ``pnpm build`` exit is a HARD failure (the
    AAASM-3142 regression), and on success the built ``dist/`` must contain the
    expected production assets (AC2 static-output check).
    """
    reason = _support.dashboard_skip_reason()
    if reason is not None:
        pytest.skip(reason)

    dashboard_dir = _support.resolve_dashboard_dir()

    # Install dependencies (the AAASM-3142 root cause was an unresolved dep, so
    # a clean install is part of the smoke check). A failed install is itself a
    # hard failure — the documented build path is not reproducible without it.
    install = _support.run_pnpm(
        ["install", "--frozen-lockfile"], cwd=dashboard_dir, timeout=_INSTALL_TIMEOUT_S
    )
    assert install.returncode == 0, (
        f"pnpm install failed (exit {install.returncode}) — dashboard production "
        f"build path is not reproducible:\n{install.stderr_tail}"
    )

    build = _support.run_pnpm(["build"], cwd=dashboard_dir, timeout=_BUILD_TIMEOUT_S)
    verdict = classify_build_result(build)
    assert verdict is BuildVerdict.PASS, (
        f"pnpm build is a HARD failure (exit {build.returncode}) — production "
        f"build regression (AAASM-3142 class):\n{build.stderr_tail}"
    )

    missing = _support.built_assets_present(dashboard_dir, EXPECTED_BUILD_ASSETS)
    assert not missing, (
        f"AC2: pnpm build succeeded but dist/ is missing expected assets: {missing}"
    )
