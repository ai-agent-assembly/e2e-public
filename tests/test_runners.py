"""Unit tests for aasm_verify.runners (area dispatch + exit-code propagation)."""

from __future__ import annotations

from dataclasses import dataclass
from unittest import mock

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
    # Path is only forwarded to the (mocked) runner, never written.
    report = "report.json"
    code = runners.run_area(_refs(), "sdk", json_report=report, _runner=rec)
    assert code == 0
    cmd, env = rec.calls[0]
    assert "pytest" in cmd and "-m" in cmd and "sdk" in cmd
    assert f"--json-report-file={report}" in cmd
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


def test_pytest_command_allows_known_markers() -> None:
    for marker in (*runners.AREAS, "release"):
        if marker == "install":
            continue  # install has no pytest marker; it runs the smoke script
        cmd = runners._pytest_command(marker, None)
        assert cmd[:5] == [runners.sys.executable, "-m", "pytest", "-m", marker]


def test_pytest_command_rejects_unknown_marker() -> None:
    # Defense-in-depth against OS-command argument injection (S8705): a marker
    # must come from the fixed allowlist, never straight from untrusted input.
    # The payload below is inert test data — it is rejected, never executed.
    with pytest.raises(ValueError, match="unknown marker"):
        runners._pytest_command("sdk; --inject-extra-pytest-arg", None)


def test_prepare_area_artifacts_installs_aasm_for_runtime() -> None:
    # Regression for AAASM-4736: the runtime area used to skip unconditionally
    # because nothing installed the aasm binary first. prepare_area_artifacts
    # must invoke the (real) installer for the runtime area and put the built
    # binary's dir on PATH so run_area's pytest subprocess inherits it. The
    # installer is fully mocked so no real clone/build runs.
    refs = ResolvedRefs(mode="latest", agent_assembly="abc123")
    with (
        mock.patch.object(
            runners.installers, "install_aasm_cli", return_value="/fake/bin"
        ) as installer,
        # Mock the sibling area installers too so the "sdk" in the selection does
        # not fire a real python-sdk/node-sdk/go-sdk clone/install/build here.
        mock.patch.object(runners.installers, "install_python_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_node_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_go_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_examples", return_value=None),
        mock.patch.dict(runners.os.environ, {"PATH": "/usr/bin"}, clear=False),
    ):
        runners.prepare_area_artifacts(refs, ["runtime", "sdk"])
        installer.assert_called_once_with("abc123")
        assert runners.os.environ["PATH"].startswith("/fake/bin" + runners.os.pathsep)

    # An area selection without runtime must not trigger the runtime installer.
    with (
        mock.patch.object(runners.installers, "install_aasm_cli") as installer,
        mock.patch.object(runners.installers, "install_python_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_node_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_go_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_examples", return_value=None),
    ):
        runners.prepare_area_artifacts(refs, ["sdk", "examples"])
        installer.assert_not_called()


def test_prepare_area_artifacts_installs_python_sdk_for_sdk() -> None:
    # AAASM-4770: the sdk area used to skip unconditionally because nothing
    # installed the python-sdk first. prepare_area_artifacts must invoke the
    # python-sdk installer for the sdk area (and not for others). The installers
    # are fully mocked so no real clone/install runs.
    refs = ResolvedRefs(mode="latest", python_sdk="py-ref")
    with (
        mock.patch.object(runners.installers, "install_aasm_cli", return_value=None),
        mock.patch.object(runners.installers, "install_node_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_go_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_examples", return_value=None),
        mock.patch.object(runners.installers, "install_python_sdk") as installer,
    ):
        runners.prepare_area_artifacts(refs, ["sdk"])
        installer.assert_called_once_with("py-ref")

        # An area selection without sdk must not trigger the python-sdk installer.
        installer.reset_mock()
        runners.prepare_area_artifacts(refs, ["runtime", "examples"])
        installer.assert_not_called()


def test_prepare_area_artifacts_installs_node_sdk_for_sdk() -> None:
    # AAASM-4774: the sdk area now also exercises the node SDK. prepare_area_artifacts
    # must invoke the node-sdk installer for the sdk area (and not for others) and
    # expose the built checkout via AASM_NODE_SDK_DIR so the pytest subprocess runs
    # node with that cwd. The installers are fully mocked so no real clone/build runs.
    refs = ResolvedRefs(mode="latest", node_sdk="node-ref")
    with (
        mock.patch.object(runners.installers, "install_aasm_cli", return_value=None),
        mock.patch.object(runners.installers, "install_python_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_go_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_examples", return_value=None),
        mock.patch.object(
            runners.installers, "install_node_sdk", return_value="/fake/node-sdk"
        ) as installer,
        mock.patch.dict(runners.os.environ, {}, clear=False),
    ):
        runners.prepare_area_artifacts(refs, ["sdk"])
        installer.assert_called_once_with("node-ref")
        assert runners.os.environ["AASM_NODE_SDK_DIR"] == "/fake/node-sdk"

        # An area selection without sdk must not trigger the node-sdk installer.
        installer.reset_mock()
        runners.prepare_area_artifacts(refs, ["runtime", "examples"])
        installer.assert_not_called()


def test_prepare_area_artifacts_installs_go_sdk_for_sdk() -> None:
    # AAASM-4774: the sdk area now also exercises the go SDK. prepare_area_artifacts
    # must invoke the go-sdk installer for the sdk area (and not for others) and
    # expose the checkout via AASM_GO_SDK_DIR so the pytest subprocess's source
    # acquisition uses it. The installers are fully mocked so no real clone runs.
    refs = ResolvedRefs(mode="latest", go_sdk="go-ref")
    with (
        mock.patch.object(runners.installers, "install_aasm_cli", return_value=None),
        mock.patch.object(runners.installers, "install_python_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_node_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_examples", return_value=None),
        mock.patch.object(
            runners.installers, "install_go_sdk", return_value="/fake/go-sdk"
        ) as installer,
        mock.patch.dict(runners.os.environ, {}, clear=False),
    ):
        runners.prepare_area_artifacts(refs, ["sdk"])
        installer.assert_called_once_with("go-ref")
        assert runners.os.environ["AASM_GO_SDK_DIR"] == "/fake/go-sdk"

        # An area selection without sdk must not trigger the go-sdk installer.
        installer.reset_mock()
        runners.prepare_area_artifacts(refs, ["runtime", "examples"])
        installer.assert_not_called()


def test_prepare_area_artifacts_installs_examples_for_examples() -> None:
    # AAASM-4770: the examples area used to skip unconditionally because nothing
    # materialized the examples checkout. prepare_area_artifacts must invoke the
    # examples installer for the examples area (and not for others) and expose
    # the checkout via AASM_EXAMPLES_DIR so the pytest subprocess inherits it.
    refs = ResolvedRefs(mode="latest", examples="ex-ref")
    with (
        mock.patch.object(runners.installers, "install_aasm_cli", return_value=None),
        mock.patch.object(runners.installers, "install_python_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_node_sdk", return_value=None),
        mock.patch.object(runners.installers, "install_go_sdk", return_value=None),
        mock.patch.object(
            runners.installers, "install_examples", return_value="/fake/examples"
        ) as installer,
        mock.patch.dict(runners.os.environ, {}, clear=False),
    ):
        runners.prepare_area_artifacts(refs, ["examples"])
        installer.assert_called_once_with("ex-ref")
        assert runners.os.environ["AASM_EXAMPLES_DIR"] == "/fake/examples"

        # An area selection without examples must not trigger the examples installer.
        installer.reset_mock()
        runners.prepare_area_artifacts(refs, ["runtime", "sdk"])
        installer.assert_not_called()


def test_prepare_area_artifacts_noop_in_release_mode() -> None:
    # Release mode installs published packages in the workflow, so the source
    # installers must not fire even when their areas are selected.
    refs = ResolvedRefs(mode="release", python_sdk="0.0.1", examples="master")
    with (
        mock.patch.object(runners.installers, "install_aasm_cli") as aasm,
        mock.patch.object(runners.installers, "install_python_sdk") as py,
        mock.patch.object(runners.installers, "install_node_sdk") as node,
        mock.patch.object(runners.installers, "install_go_sdk") as go,
        mock.patch.object(runners.installers, "install_examples") as ex,
    ):
        runners.prepare_area_artifacts(refs, list(runners.AREAS))
        aasm.assert_not_called()
        py.assert_not_called()
        node.assert_not_called()
        go.assert_not_called()
        ex.assert_not_called()


def test_pytest_command_marker_originates_from_constant_allowlist() -> None:
    # The marker placed in the argv must be the *constant* allowlist value, not
    # the caller's parameter object — so no untrusted text can flow into the
    # spawned command (S8705). Identity proves the data origin is the constant:
    # a fresh, non-interned str equal to "sdk" must not be the object emitted.
    marker = "".join(["sd", "k"])  # a new str object, not the literal "sdk"
    cmd = runners._pytest_command(marker, None)
    # The pytest selector marker is the argv element right before "-v" (the
    # leading "-m" belongs to "python -m pytest", so don't index on that one).
    emitted = cmd[cmd.index("-v") - 1]
    assert emitted is runners._ALLOWED_MARKERS["sdk"]
    assert emitted is not marker
