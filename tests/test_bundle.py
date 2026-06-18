"""Unit tests for aasm_verify.bundle (the QA evidence-bundle assembler).

These cover the AAASM-3162 acceptance criteria that have a code surface:
the bundle is produced with the expected files (AC1/AC2), carries the Jira-ready
summary (AC3), copies screenshots when present and tolerates their absence
(AC4), and — most important — never echoes a secret (AC5).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aasm_verify import bundle
from aasm_verify.bundle import EvidenceBundle, collect_env
from aasm_verify.pathsafe import PathTraversalError
from aasm_verify.reports import Suite, Summary

# A run env carrying a deliberately-named fake secret. Every bundle file is
# asserted clean of this value to prove the allow-list scrubs it (AC5).
_FAKE_SECRET = "sk-LEAK-do-not-emit-12345"
_LEAKY_ENV = {
    "GITHUB_REF": "refs/heads/master",
    "AREA": "sdk",
    "GITHUB_TOKEN": _FAKE_SECRET,
    "AWS_SECRET_ACCESS_KEY": _FAKE_SECRET,
    "PRIVATE_GATEWAY_URL": "https://internal.example.invalid",
}


def _summary(**overrides: object) -> Summary:
    base: dict = {
        "run_type": "scheduled",
        "result": "pass",
        "date": "2026-06-18",
        "workflow_run_url": "https://github.com/ai-agent-assembly/agent-assembly-integration-tests/actions/runs/1",
        "tested_refs": ["master"],
        "retain": "short-term",
        "suites": [Suite("test_python_sdk", "pass", 5)],
    }
    base.update(overrides)
    return Summary(**base)  # type: ignore[arg-type]


def _bundle(tmp_path: Path, **overrides: object) -> Path:
    kwargs: dict = {
        "summary": _summary(),
        "commands": ["bash scripts/verify-public-stack.sh"],
        "ci_links": ["https://github.com/x/actions/runs/1"],
        "env": dict(_LEAKY_ENV),
    }
    kwargs.update(overrides)
    return EvidenceBundle(**kwargs).write(tmp_path / "bundle")  # type: ignore[arg-type]


def test_bundle_contains_core_files(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    names = {p.name for p in out.iterdir()}
    assert {
        "summary.md",
        "report.json",
        "env.json",
        "commands.txt",
        "ci-links.txt",
        "jira-summary.txt",
    } <= names


def test_report_json_round_trips_summary(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    data = json.loads((out / "report.json").read_text())
    assert data["result"] == "pass"
    assert data["tested_refs"] == ["master"]


def test_commands_and_ci_links_recorded(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    assert "verify-public-stack.sh" in (out / "commands.txt").read_text()
    assert "runs/1" in (out / "ci-links.txt").read_text()


def test_jira_summary_is_present_and_jira_formatted(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    text = (out / "jira-summary.txt").read_text()
    assert "h2. Verification Evidence" in text


def test_env_json_carries_allowlisted_metadata(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    env = json.loads((out / "env.json").read_text())
    assert env["os"]
    assert env["tools"]["python"]
    assert env["ci_env"]["GITHUB_REF"] == "refs/heads/master"


def test_secret_absent_from_every_bundle_file(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    for path in out.rglob("*"):
        if path.is_file():
            assert _FAKE_SECRET not in path.read_text(), f"secret leaked into {path.name}"


def test_collect_env_drops_unlisted_and_redacts_sensitive() -> None:
    env = collect_env(_LEAKY_ENV)
    ci = env["ci_env"]
    assert "GITHUB_TOKEN" not in ci  # not on the allow-list -> dropped
    assert "AWS_SECRET_ACCESS_KEY" not in ci
    assert "PRIVATE_GATEWAY_URL" not in ci
    assert _FAKE_SECRET not in json.dumps(env)


def test_private_endpoint_not_emitted(tmp_path: Path) -> None:
    out = _bundle(tmp_path)
    for path in out.rglob("*"):
        if path.is_file():
            assert "internal.example.invalid" not in path.read_text()


def test_screenshots_copied_when_present(tmp_path: Path) -> None:
    shots = tmp_path / "shots"
    shots.mkdir()
    (shots / "login.png").write_bytes(b"\x89PNG\r\n")
    (shots / "notes.txt").write_text("ignored")  # non-image is skipped
    out = _bundle(tmp_path, screenshot_dirs=[shots])
    copied = sorted(p.name for p in (out / "screenshots").iterdir())
    assert copied == ["login.png"]


def test_screenshots_absent_is_tolerated(tmp_path: Path) -> None:
    # No screenshot dirs, and a non-existent dir, must both be tolerated (AC4).
    out = _bundle(tmp_path, screenshot_dirs=[tmp_path / "does-not-exist"])
    assert not (out / "screenshots").exists()


def test_pytest_json_copied_when_available(tmp_path: Path) -> None:
    src = tmp_path / "pytest.json"
    src.write_text('{"summary": {"passed": 1}, "tests": []}')
    out = _bundle(tmp_path, pytest_json_path=src)
    assert (out / "pytest-report.json").exists()


def test_pytest_json_absence_is_tolerated(tmp_path: Path) -> None:
    out = _bundle(tmp_path, pytest_json_path=tmp_path / "missing.json")
    assert not (out / "pytest-report.json").exists()


def test_allow_list_has_no_sensitive_keys() -> None:
    # The static allow-list itself must not name a credential-bearing key (AC5).
    leaks = [k for k in bundle.ENV_ALLOW_LIST if bundle._key_is_sensitive(k)]
    assert leaks == []


class _TraversalName:
    """A screenshot file whose ``.name`` is a traversal escape, not a basename.

    Stands in for a real screenshot entry to prove the bundle routes each
    per-file destination through ``safe_path``: a name that climbs out of the
    bundle's ``screenshots/`` dir must be rejected, never copied (S8707).
    """

    suffix = ".png"
    name = "../../escape.png"

    @staticmethod
    def is_file() -> bool:
        return True


class _TraversalSourceDir:
    """A screenshot source dir yielding a single traversal-named file."""

    @staticmethod
    def is_dir() -> bool:
        return True

    @staticmethod
    def rglob(_pattern: str) -> list[_TraversalName]:
        return [_TraversalName()]


def test_screenshot_traversal_name_is_rejected(tmp_path: Path) -> None:
    # A copy whose destination name would escape screenshots/ must raise rather
    # than write outside the bundle — the contract safe_path enforces (S8707).
    with pytest.raises(PathTraversalError):
        _bundle(tmp_path, screenshot_dirs=[_TraversalSourceDir()])


def test_write_rejects_relative_outdir_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The bundle *root* (``--bundle``/``--out``) is operator-supplied: a relative
    # ``../`` value must be rejected before any mkdir, so the bundle can never be
    # written outside the run's working tree (path traversal, S8707).
    monkeypatch.chdir(tmp_path)
    bundle_obj = EvidenceBundle(summary=_summary(), env=dict(_LEAKY_ENV))
    with pytest.raises(PathTraversalError):
        bundle_obj.write("../escape-bundle")


def test_write_accepts_legitimate_relative_outdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A normal relative outdir that stays within the working tree still writes
    # the full bundle — the guard must not break legitimate paths.
    monkeypatch.chdir(tmp_path)
    bundle_obj = EvidenceBundle(
        summary=_summary(),
        commands=["bash scripts/verify-public-stack.sh"],
        env=dict(_LEAKY_ENV),
    )
    out = bundle_obj.write("out/bundle")
    assert out == (tmp_path / "out" / "bundle").resolve()
    names = {p.name for p in out.iterdir()}
    assert {"summary.md", "report.json", "env.json"} <= names
