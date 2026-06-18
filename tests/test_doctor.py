"""Unit tests for the `aasm-verify doctor` environment preflight command.

The probes are exercised in isolation with the real environment monkeypatched
away, so the suite is deterministic and offline-safe: no test depends on which
tools, network, or browser the host machine happens to have.
"""

from __future__ import annotations

import errno

from aasm_verify import doctor
from aasm_verify.doctor import Status


def test_check_tool_present_passes(monkeypatch) -> None:
    spec = doctor.ToolSpec("cargo", "--version", ("runtime",))
    monkeypatch.setattr(doctor.shutil, "which", lambda _: "/usr/bin/cargo")
    monkeypatch.setattr(doctor, "_tool_version", lambda *a: "cargo 1.95.0")

    result = doctor.check_tool(spec)

    assert result.status is Status.PASS
    assert result.name == "tool:cargo"
    assert "1.95.0" in result.detail
    assert result.areas == ("runtime",)


def test_check_tool_missing_required_fails(monkeypatch) -> None:
    spec = doctor.ToolSpec("protoc", "--version", ("runtime",), required=True)
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)

    result = doctor.check_tool(spec)

    assert result.status is Status.FAIL
    assert "not found" in result.detail


def test_check_tool_missing_optional_warns(monkeypatch) -> None:
    spec = doctor.ToolSpec("pnpm", "--version", ("sdk",), required=False)
    monkeypatch.setattr(doctor.shutil, "which", lambda _: None)

    result = doctor.check_tool(spec)

    assert result.status is Status.WARN


def test_check_localhost_bind_succeeds_when_allowed() -> None:
    # In a normal environment a loopback bind succeeds; assert the happy path
    # reports PASS and gates the server-booting areas.
    result = doctor.check_localhost_bind()

    assert result.status is Status.PASS
    assert result.areas == ("runtime", "conformance")


def test_check_localhost_bind_eperm_maps_to_fail(monkeypatch) -> None:
    class _DeniedSocket:
        def bind(self, _addr):
            raise OSError(errno.EPERM, "Operation not permitted")

        def getsockname(self):  # pragma: no cover - never reached on EPERM
            return ("127.0.0.1", 0)

        def close(self):
            pass

    monkeypatch.setattr(doctor.socket, "socket", lambda *a, **k: _DeniedSocket())

    result = doctor.check_localhost_bind()

    assert result.status is Status.FAIL
    assert "denied" in result.detail


def test_check_localhost_bind_eacces_maps_to_fail(monkeypatch) -> None:
    class _DeniedSocket:
        def bind(self, _addr):
            raise OSError(errno.EACCES, "Permission denied")

        def getsockname(self):  # pragma: no cover
            return ("127.0.0.1", 0)

        def close(self):
            pass

    monkeypatch.setattr(doctor.socket, "socket", lambda *a, **k: _DeniedSocket())

    result = doctor.check_localhost_bind()

    assert result.status is Status.FAIL


def test_check_network_passes_when_reachable(monkeypatch) -> None:
    monkeypatch.setattr(doctor, "_can_connect", lambda *a, **k: True)

    result = doctor.check_network()

    assert result.status is Status.PASS
    assert "reachable" in result.detail


def test_check_network_offline_degrades_to_warn(monkeypatch) -> None:
    # Being offline must WARN, never FAIL — flagging the limit is the point.
    monkeypatch.setattr(doctor, "_can_connect", lambda *a, **k: False)

    result = doctor.check_network()

    assert result.status is Status.WARN
    assert "network unavailable" in result.detail
