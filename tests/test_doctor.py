"""Unit tests for the `aasm-verify doctor` environment preflight command.

The probes are exercised in isolation with the real environment monkeypatched
away, so the suite is deterministic and offline-safe: no test depends on which
tools, network, or browser the host machine happens to have.
"""

from __future__ import annotations

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
