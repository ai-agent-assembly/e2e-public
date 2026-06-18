"""Offline tests for the Node/Go allow-path driver locators (AAASM-3194).

These exercise the *justified-skip* logic in :mod:`tests.live.sdk_drivers`
without launching any toolchain, SDK, or runtime — so they are green in a bare
``-m e2e`` run with nothing installed. They assert the load-bearing contract the
live tests depend on: when a prerequisite is absent the locator raises
:class:`~tests.live.sdk_drivers.DriverUnavailable` with a reason the skip-audit
(:mod:`aasm_verify.skip_audit`) accepts as *justified* (an env requirement or a
Jira ref), never a bare/empty reason that would silently erode coverage.

The driver *execution* (a real subprocess against a live runtime) is covered by
the per-language E2E allow tests, which skip when the toolchain is absent; here
we only prove the locator + result-parser behave offline.
"""

from __future__ import annotations

import pytest

from aasm_verify.skip_audit import is_justified
from tests.live import sdk_drivers
from tests.live.sdk_drivers import (
    DriverFailed,
    DriverUnavailable,
    locate_go_driver,
    locate_node_driver,
)

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]


def test_node_locator_missing_toolchain_raises_justified(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``node`` on PATH → a DriverUnavailable whose reason is skip-audit-justified."""
    monkeypatch.setattr(sdk_drivers.shutil, "which", lambda _name: None)
    with pytest.raises(DriverUnavailable) as exc:
        locate_node_driver()
    assert is_justified(str(exc.value))


def test_go_locator_missing_toolchain_raises_justified(monkeypatch: pytest.MonkeyPatch) -> None:
    """No ``go`` on PATH → a DriverUnavailable whose reason is skip-audit-justified."""
    monkeypatch.setattr(sdk_drivers.shutil, "which", lambda _name: None)
    with pytest.raises(DriverUnavailable) as exc:
        locate_go_driver()
    assert is_justified(str(exc.value))


def test_node_locator_missing_sdk_raises_justified(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool present but no SDK checkout → justified skip naming the missing SDK.

    Forces the toolchain probe to pass and the SDK-dir resolver to miss, so the
    SDK-absent branch (not the toolchain branch) is the one exercised.
    """
    monkeypatch.setattr(sdk_drivers.shutil, "which", lambda _name: "/usr/bin/node")
    monkeypatch.setattr(sdk_drivers, "_sibling_sdk_dir", lambda _env, _name: None)
    with pytest.raises(DriverUnavailable) as exc:
        locate_node_driver()
    reason = str(exc.value)
    assert is_justified(reason)
    assert "Node SDK" in reason


def test_go_locator_missing_native_lib_raises_justified(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """Tool + SDK present but no cgo FFI lib → justified skip, not a silent no-op.

    The Go SDK's default binding is a *simulated* UDS; without the compiled
    ``libaa_ffi_go`` a driver run would not reach a real core, so the locator
    must skip (justified) rather than pass against the fallback.
    """
    monkeypatch.setattr(sdk_drivers.shutil, "which", lambda _name: "/usr/bin/go")
    sdk_dir = sdk_drivers.Path(str(tmp_path))
    monkeypatch.setattr(sdk_drivers, "_sibling_sdk_dir", lambda _env, _name: sdk_dir)
    monkeypatch.setattr(sdk_drivers, "_go_native_lib_present", lambda _dir: False)
    with pytest.raises(DriverUnavailable) as exc:
        locate_go_driver()
    assert is_justified(str(exc.value))


def test_go_locator_skips_native_lib_check_when_not_required(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pytest.TempPathFactory
) -> None:
    """``require_native_lib=False`` resolves a GoDriver when tool + SDK + module exist."""
    monkeypatch.setattr(sdk_drivers.shutil, "which", lambda _name: "/usr/bin/go")
    sdk_dir = sdk_drivers.Path(str(tmp_path))
    monkeypatch.setattr(sdk_drivers, "_sibling_sdk_dir", lambda _env, _name: sdk_dir)
    driver = locate_go_driver(require_native_lib=False)
    assert driver.sdk_dir == sdk_dir
    assert (driver.module_dir / "go.mod").is_file()


def test_result_parser_rejects_non_json() -> None:
    """A driver line that is not JSON is a hard DriverFailed, never a silent pass."""
    with pytest.raises(DriverFailed):
        sdk_drivers._parse_driver_result("not json at all")


def test_result_parser_reads_last_json_line() -> None:
    """The parser reads the last non-empty line, ignoring earlier banner output."""
    result = sdk_drivers._parse_driver_result('banner\n{"ok": true, "action": "tool.search"}\n')
    assert result == {"ok": True, "action": "tool.search"}
