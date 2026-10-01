"""Regression tests for the go-sdk toolchain-floor guard (AAASM-6245).

The ``sdk`` area of both verify-public lanes ran without a Go toolchain, so it
used whatever the runner image shipped (go1.24.13) against a go-sdk checkout
declaring ``go 1.26.0``. Go rejected the module graph before compiling anything
and all three ``tests/public/test_go_sdk.py`` source tests failed — but
``skip_if_binary_missing("go")`` had already passed on presence alone, so the
assertions blamed the SDK instead: "the FFI shim may be broken" for a build that
never started. Five scheduled runs failed that way between 2026-08-01 and
2026-10-01, and the harness's own issue #218 sat open for two months.

Everything here is offline and fixture-driven: go.mod bodies are written to
throwaway files and the running-version probe is monkeypatched, so no Go
toolchain is required to run these tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.public import test_go_sdk as go_sdk

# ---------------------------------------------------------------------------
# Version parsing — the two forms the guard has to compare with each other.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.26", (1, 26, 0)),  # go.mod directive, two components
        ("1.26.0", (1, 26, 0)),  # go.mod directive, three components
        ("go1.26.5", (1, 26, 5)),  # `go env GOVERSION`
        ("go1.26", (1, 26, 0)),  # GOVERSION of an x.y.0 release
        ("go1.27rc1", (1, 27, 0)),  # pre-release of the floor satisfies it
        ("go version go1.24.13 linux/amd64", (1, 24, 13)),
        ("", None),
        ("devel", None),
    ],
)
def test_parse_go_version(text: str, expected: tuple[int, int, int] | None) -> None:
    assert go_sdk._parse_go_version(text) == expected


def test_two_and_three_component_forms_of_the_same_release_compare_equal() -> None:
    """``go1.26`` is not older than ``go 1.26.0``.

    Without zero-padding, tuple comparison reads ``(1, 26) < (1, 26, 0)`` and the
    guard would reject a toolchain that in fact satisfies the floor.
    """
    assert go_sdk._parse_go_version("go1.26") == go_sdk._parse_go_version("1.26.0")


# ---------------------------------------------------------------------------
# Floor extraction — read from the checkout, never hardcoded.
# ---------------------------------------------------------------------------


def _write_go_mod(tmp_path: Path, body: str) -> str:
    (tmp_path / "go.mod").write_text(body, encoding="utf-8")
    return str(tmp_path)


def test_declared_floor_reads_the_go_directive(tmp_path: Path) -> None:
    sdk = _write_go_mod(
        tmp_path,
        "module github.com/ai-agent-assembly/go-sdk\n\ngo 1.26.0\n",
    )
    assert go_sdk._declared_go_floor(sdk) == (1, 26, 0)


def test_declared_floor_ignores_the_toolchain_directive(tmp_path: Path) -> None:
    """A dependency's ``toolchain`` line does not constrain the consumer.

    The real go-sdk go.mod pins ``toolchain go1.26.6`` for govulncheck while
    keeping its ``go`` line at 1.26.0. Reading the toolchain line as the floor
    would reject a perfectly adequate go1.26.5.
    """
    sdk = _write_go_mod(
        tmp_path,
        "module github.com/ai-agent-assembly/go-sdk\n\ngo 1.26.0\n\ntoolchain go1.26.6\n",
    )
    assert go_sdk._declared_go_floor(sdk) == (1, 26, 0)


def test_declared_floor_is_none_when_no_go_directive(tmp_path: Path) -> None:
    """No floor declared means nothing to enforce — not a failure of its own."""
    sdk = _write_go_mod(tmp_path, "module example.com/x\n")
    assert go_sdk._declared_go_floor(sdk) is None


# ---------------------------------------------------------------------------
# The guard itself. These are the anti-vacuity cases: each one is driven by a
# running version chosen relative to the fixture's floor, and the test asserts
# on which way the guard goes and what it says.
# ---------------------------------------------------------------------------


def _guard(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    go_mod: str,
    running: str,
    returncode: int = 0,
) -> None:
    """Run the guard against *go_mod* with a faked running toolchain."""
    sdk = _write_go_mod(tmp_path, go_mod)
    parsed = go_sdk._parse_go_version(running) if returncode == 0 else None
    monkeypatch.setattr(
        go_sdk,
        "_running_go_version",
        lambda: (parsed, f"exit {returncode}, stdout: {running!r}, stderr: ''"),
    )
    go_sdk._fail_if_go_below_sdk_floor(sdk)


_GO_MOD = "module github.com/ai-agent-assembly/go-sdk\n\ngo 1.26.0\n\ntoolchain go1.26.6\n"


def test_guard_fails_naming_the_floor_when_the_toolchain_is_too_old(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The exact CI condition: go1.24.13 against a 1.26.0 floor.

    This is the case the whole ticket is about, and it must go red — the lane
    genuinely cannot verify the SDK. What changes is the message: it names the
    floor and the provisioning gap instead of implicating the FFI shim.
    """
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _guard(tmp_path, monkeypatch, go_mod=_GO_MOD, running="go1.24.13")

    message = str(excinfo.value)
    assert "1.26.0" in message, message
    assert "1.24.13" in message, message
    assert "toolchain-provisioning gap" in message, message
    assert "setup-go" in message, message
    # The old failure mode blamed the shim for a build that never started.
    assert go_sdk.FFI_NATIVE_LIB not in message, message


def test_guard_passes_when_the_toolchain_satisfies_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """go1.26.5 satisfies ``go 1.26.0`` even though it predates ``toolchain go1.26.6``."""
    _guard(tmp_path, monkeypatch, go_mod=_GO_MOD, running="go1.26.5")


def test_guard_passes_on_the_exact_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The floor is inclusive — ``>=``, not ``>``."""
    _guard(tmp_path, monkeypatch, go_mod=_GO_MOD, running="go1.26")


def test_guard_fails_on_a_lower_major(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A 1.x toolchain does not satisfy a hypothetical 2.x floor."""
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _guard(
            tmp_path,
            monkeypatch,
            go_mod="module example.com/x\n\ngo 2.0.0\n",
            running="go1.26.5",
        )
    assert "2.0.0" in str(excinfo.value)


def test_guard_fails_when_the_running_version_is_unreadable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreadable toolchain version is reported, not silently treated as fine."""
    with pytest.raises(pytest.fail.Exception) as excinfo:
        _guard(tmp_path, monkeypatch, go_mod=_GO_MOD, running="", returncode=1)

    message = str(excinfo.value)
    assert "go env GOVERSION" in message, message
    assert "1.26.0" in message, message


def test_guard_is_a_no_op_when_the_checkout_declares_no_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No ``go`` directive: nothing to enforce, and the probe is not even run."""

    def _explode() -> tuple[tuple[int, int, int] | None, str]:
        raise AssertionError("the running version must not be probed with no floor to check")

    monkeypatch.setattr(go_sdk, "_running_go_version", _explode)
    go_sdk._fail_if_go_below_sdk_floor(_write_go_mod(tmp_path, "module example.com/x\n"))


# ---------------------------------------------------------------------------
# Wiring — the guard has to be reached, by all three source parametrizations.
# ---------------------------------------------------------------------------


def test_consumer_runs_the_guard_before_touching_the_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``_consumer("source", ...)`` calls the guard, and does so first.

    All three source tests route through ``_consumer``, so one call site covers
    them. Order matters: the guard has to run before the consumer module is
    written, or the test still fails on the build with the wrong cause named.
    """
    calls: list[str] = []
    monkeypatch.setattr(go_sdk, "_go_sdk_path", lambda: "/nonexistent/go-sdk")
    monkeypatch.setattr(
        go_sdk,
        "_fail_if_go_below_sdk_floor",
        lambda sdk_path: calls.append(f"guard:{sdk_path}"),
    )
    monkeypatch.setattr(go_sdk, "_module_path_of", lambda sdk_path: "example.com/sdk")
    monkeypatch.setattr(
        go_sdk,
        "_write_source_consumer",
        lambda tmp, sdk_path, module_path: calls.append("write"),
    )

    go_sdk._consumer("source", str(tmp_path))

    assert calls == ["guard:/nonexistent/go-sdk", "write"]
