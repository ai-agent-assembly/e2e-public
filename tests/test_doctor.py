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
            """No-op: the stub socket holds no real OS resource to release."""

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
            """No-op: the stub socket holds no real OS resource to release."""

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


def test_check_cache_writable_passes(tmp_path, monkeypatch) -> None:
    cache = tmp_path / "gocache"
    cache.mkdir()
    monkeypatch.setenv("GOCACHE", str(cache))
    spec = doctor.CacheSpec("go", "GOCACHE", ("GOCACHE",), ".cache/go-build", ("sdk",))

    result = doctor.check_cache(spec)

    assert result.status is Status.PASS
    assert result.recommend_env == {}


def test_check_cache_not_writable_warns_with_env_recommendation(monkeypatch) -> None:
    # Force the resolved dir to be non-writable; expect WARN + a GOCACHE override.
    monkeypatch.setattr(doctor, "_is_writable", lambda _d: False)
    spec = doctor.CacheSpec("go", "GOCACHE", ("GOCACHE",), ".cache/go-build", ("sdk",))

    result = doctor.check_cache(spec)

    assert result.status is Status.WARN
    assert "GOCACHE" in result.recommend_env
    assert result.recommend_env["GOCACHE"].endswith("aasm-go-cache")


def test_check_browser_no_playwright_warns(monkeypatch) -> None:
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _: None)

    result = doctor.check_browser()

    assert result.status is Status.WARN
    assert result.areas == ("examples",)
    assert "playwright" in result.detail.lower()


def test_check_browser_present_with_chromium_passes(tmp_path, monkeypatch) -> None:
    browsers = tmp_path / "ms-playwright"
    (browsers / "chromium-1187").mkdir(parents=True)
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(doctor, "_playwright_browsers_dir", lambda: browsers)

    result = doctor.check_browser()

    assert result.status is Status.PASS
    assert "chromium" in result.detail.lower()


def test_check_browser_present_without_chromium_warns(tmp_path, monkeypatch) -> None:
    browsers = tmp_path / "ms-playwright"
    browsers.mkdir()
    monkeypatch.setattr(doctor.importlib.util, "find_spec", lambda _: object())
    monkeypatch.setattr(doctor, "_playwright_browsers_dir", lambda: browsers)

    result = doctor.check_browser()

    assert result.status is Status.WARN
    assert "Chromium" in result.detail


def test_area_statuses_takes_worst_status_per_area() -> None:
    checks = [
        doctor.CheckResult("a", Status.PASS, areas=("runtime",)),
        doctor.CheckResult("b", Status.FAIL, areas=("runtime",)),
        doctor.CheckResult("c", Status.WARN, areas=("sdk",)),
    ]

    areas = doctor.area_statuses(checks)

    assert areas["runtime"] is Status.FAIL  # worst of PASS + FAIL
    assert areas["sdk"] is Status.WARN
    assert areas["install"] is Status.PASS  # no gating check defaults to PASS


def test_worst_of_empty_is_pass() -> None:
    assert doctor.worst([]) is Status.PASS


def _report_with(checks: list[doctor.CheckResult]) -> doctor.DoctorReport:
    areas = doctor.area_statuses(checks)
    overall = doctor.worst(list(areas.values()))
    return doctor.DoctorReport(checks=checks, areas=areas, overall=overall)


def test_exit_code_zero_unless_fail() -> None:
    warn_report = _report_with([doctor.CheckResult("n", Status.WARN, areas=("sdk",))])
    fail_report = _report_with([doctor.CheckResult("b", Status.FAIL, areas=("runtime",))])

    assert doctor.exit_code(warn_report) == 0
    assert doctor.exit_code(fail_report) == 1


def test_report_recommended_env_merges_checks() -> None:
    # Opaque cache-dir placeholders: this test only checks that recommend_env
    # values merge across checks, so the strings need not be real paths — and
    # must not be world-writable /tmp paths (S5443).
    go_cache = "<gocache>"
    uv_cache = "<uvcache>"
    checks = [
        doctor.CheckResult(
            "cache:go", Status.WARN, areas=("sdk",), recommend_env={"GOCACHE": go_cache}
        ),
        doctor.CheckResult(
            "cache:uv", Status.WARN, areas=("sdk",), recommend_env={"UV_CACHE_DIR": uv_cache}
        ),
    ]
    report = _report_with(checks)

    assert report.recommended_env() == {"GOCACHE": go_cache, "UV_CACHE_DIR": uv_cache}


def test_render_text_includes_glyphs_and_overall() -> None:
    report = _report_with([doctor.CheckResult("bind", Status.FAIL, areas=("runtime",))])

    text = doctor.render_text(report)

    assert "[FAIL]" in text
    assert "Overall:" in text
    assert "runtime" in text


def test_cli_doctor_json_output_shape(capsys) -> None:
    import json

    from aasm_verify import cli

    args = cli.build_parser().parse_args(["doctor", "--json"])
    code = cli.cmd_doctor(args)

    payload = json.loads(capsys.readouterr().out)
    assert code in (0, 1)
    assert payload["overall"] in ("pass", "warn", "fail")
    assert set(payload["areas"]) == set(doctor.AREAS)
    assert isinstance(payload["checks"], list)
    assert isinstance(payload["recommended_env"], dict)
    # Every check carries the four documented keys.
    for check in payload["checks"]:
        assert {"name", "status", "detail", "areas", "recommend_env"} <= set(check)


def test_cli_doctor_text_output_is_human_readable(capsys) -> None:
    from aasm_verify import cli

    args = cli.build_parser().parse_args(["doctor"])
    cli.cmd_doctor(args)

    out = capsys.readouterr().out
    assert "Environment preflight" in out
    assert "Areas:" in out
