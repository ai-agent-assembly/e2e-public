"""Unit tests for aasm_verify.runners (area dispatch + exit-code propagation)."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from aasm_verify import runners
from aasm_verify.refs import ResolvedRefs


@dataclass
class _FakeResult:
    returncode: int


class _Recorder:
    """Callable stand-in for subprocess.run that records calls and returns a code."""

    def __init__(self, code: int = 0) -> None:
        self.code = code
        self.calls: list[tuple[list[str], dict[str, str]]] = []

    def __call__(self, cmd, *, env):  # type: ignore[no-untyped-def]
        self.calls.append((cmd, env))
        return _FakeResult(self.code)


def _refs(mode: str = "latest") -> ResolvedRefs:
    return ResolvedRefs(mode=mode)


def test_resolve_areas_all() -> None:
    assert runners.resolve_areas("all") == list(runners.AREAS)


def test_resolve_areas_single() -> None:
    assert runners.resolve_areas("sdk") == ["sdk"]


def test_resolve_areas_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown area"):
        runners.resolve_areas("bogus")


def test_marker_area_runs_pytest() -> None:
    rec = _Recorder()
    code = runners.run_area(_refs(), "sdk", json_report="/tmp/r.json", _runner=rec)
    assert code == 0
    cmd, env = rec.calls[0]
    assert "pytest" in cmd and "-m" in cmd and "sdk" in cmd
    assert "--json-report-file=/tmp/r.json" in cmd
    assert env["AASM_INSTALL_MODE"] == "source"


def test_install_area_runs_smoke_script() -> None:
    rec = _Recorder()
    runners.run_area(_refs(), "install", _runner=rec)
    cmd, _ = rec.calls[0]
    assert cmd[0] == "bash" and cmd[1].endswith("smoke-test-rust-build.sh")


def test_release_mode_runs_release_marker_with_version() -> None:
    rec = _Recorder()
    refs = ResolvedRefs(mode="release", python_sdk="0.0.1", node_sdk="0.0.1", go_sdk="v0.0.1")
    runners.run_area(refs, "sdk", _runner=rec)
    cmd, env = rec.calls[0]
    assert "release" in cmd
    assert env["AASM_INSTALL_MODE"] == "release"
    assert env["AASM_RELEASE_VERSION"] == "0.0.1"


def test_run_area_propagates_nonzero() -> None:
    assert runners.run_area(_refs(), "sdk", _runner=_Recorder(code=1)) == 1


def test_run_areas_all_pass() -> None:
    rec = _Recorder(code=0)
    assert runners.run_areas(_refs(), ["runtime", "sdk"], _runner=rec) == 0
    assert len(rec.calls) == 2


def test_run_areas_any_failure_returns_one() -> None:
    assert runners.run_areas(_refs(), ["runtime", "sdk"], _runner=_Recorder(code=1)) == 1


def test_run_areas_runs_every_area_despite_failure() -> None:
    rec = _Recorder(code=1)
    runners.run_areas(_refs(), list(runners.AREAS), _runner=rec)
    # Every area is attempted even though the first fails.
    assert len(rec.calls) == len(runners.AREAS)
