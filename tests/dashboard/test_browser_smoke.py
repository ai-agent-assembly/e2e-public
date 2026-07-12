"""Optional browser smoke for the dashboard (AAASM-3154, AC3).

This path is OPTIONAL and clearly reported: it serves the built dashboard
through the documented ``pnpm serve`` (vite preview) path, loads the default
route in a real browser via Playwright, asserts no page/console errors, and
captures a screenshot as evidence.

It is **skip-guarded** on every prerequisite (opt-in, toolchain, checkout,
loopback-bind, Playwright). The live browser run + screenshot self-verification
is a *documented deferred exception* in the standard sandbox: port-bind is
blocked (AAASM-3145) and Chromium launch is sandboxed (AAASM-3146), so this
test skips with a justified reason there rather than failing. It exercises the
browser path only where the environment supports it.
"""

from __future__ import annotations

import socket
import subprocess
import time
from contextlib import closing
from pathlib import Path

import pytest

from tests.dashboard import _support
from tests.dashboard.manifest import DASHBOARD_ROUTES

# Bound for waiting on the preview server to accept connections.
_SERVE_READY_TIMEOUT_S = 30
_BUILD_TIMEOUT_S = 600
_INSTALL_TIMEOUT_S = 600


def _free_port() -> int:
    """Return a kernel-assigned free loopback TCP port.

    A free port avoids collisions when the suite runs concurrently; there is an
    inherent (small) race between releasing the port here and the preview
    server binding it, which the readiness wait below tolerates.
    """
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_until_serving(port: int, timeout: float) -> bool:
    """Poll ``127.0.0.1:port`` until it accepts a connection or *timeout*."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


def test_browser_route_loads_without_console_errors(tmp_path: Path) -> None:
    """AC3: load the default route in a browser; assert no errors + screenshot.

    Skips (justified) unless opted-in with a usable toolchain, a bindable
    loopback port, and Playwright installed. When it runs: builds the
    dashboard, serves it via ``pnpm serve``, loads the first route, fails on any
    page error or console ``error`` message, and writes a screenshot to
    ``tmp_path`` as evidence.
    """
    reason = _support.browser_skip_reason()
    if reason is not None:
        pytest.skip(f"{reason} (classification: known_prerequisite)")

    # Imported lazily so a non-Playwright environment never imports it at
    # collection time (the skip-guard above gates reaching this point).
    from playwright.sync_api import sync_playwright

    dashboard_dir = _support.resolve_dashboard_dir()

    install = _support.run_pnpm(
        ["install", "--frozen-lockfile"], cwd=dashboard_dir, timeout=_INSTALL_TIMEOUT_S
    )
    assert install.returncode == 0, f"pnpm install failed:\n{install.stderr_tail}"

    build = _support.run_pnpm(["build"], cwd=dashboard_dir, timeout=_BUILD_TIMEOUT_S)
    assert build.returncode == 0, f"pnpm build is a hard failure:\n{build.stderr_tail}"

    port = _free_port()
    # vite preview serves the built dist/. --strictPort fails fast if taken.
    server = subprocess.Popen(
        ["pnpm", "exec", "vite", "preview", "--port", str(port), "--strictPort"],
        cwd=str(dashboard_dir),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _wait_until_serving(port, _SERVE_READY_TIMEOUT_S), (
            f"preview server did not start on 127.0.0.1:{port} within "
            f"{_SERVE_READY_TIMEOUT_S}s"
        )

        first_route = DASHBOARD_ROUTES[0].path
        console_errors: list[str] = []
        page_errors: list[str] = []

        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                page = browser.new_page()
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg.text)
                    if msg.type == "error"
                    else None,
                )
                page.on("pageerror", lambda exc: page_errors.append(str(exc)))
                page.goto(f"http://127.0.0.1:{port}{first_route}", wait_until="networkidle")
                shot = tmp_path / "dashboard-overview.png"
                page.screenshot(path=str(shot))
            finally:
                browser.close()

        assert shot.is_file(), "browser smoke produced no screenshot evidence"
        assert not page_errors, f"page errors on {first_route}: {page_errors}"
        assert not console_errors, f"console errors on {first_route}: {console_errors}"
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
