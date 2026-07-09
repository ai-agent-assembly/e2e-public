"""End-to-end tests for the `aasm-verify report` CLI subcommand."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aasm_verify import cli, reports

FIXTURES = Path(__file__).parent / "fixtures"


def _run(argv: list[str]) -> int:
    parser = cli.build_parser()
    args = parser.parse_args(argv)
    return cli.cmd_report(args)


def test_report_from_pytest_json_writes_both_artifacts(tmp_path) -> None:
    summary_path = tmp_path / "summary.json"
    out_path = tmp_path / "report.md"
    code = _run(
        [
            "report",
            "--pytest-json",
            str(FIXTURES / "pytest-report-pass.json"),
            "--summary",
            str(summary_path),
            "--out",
            str(out_path),
            "--date",
            "2026-06-18",
            "--run-url",
            "https://github.com/ai-agent-assembly/e2e-public/actions/runs/1",
            "--tested-refs",
            "master, python-sdk@master",
            "--retain",
            "short-term",
        ]
    )
    assert code == 0
    assert summary_path.exists()
    assert out_path.exists()

    data = json.loads(summary_path.read_text())
    assert data["report_type"] == "public-integration"
    assert data["source_repo"] == "agent-assembly-integration-tests"
    assert data["result"] == "pass"
    assert data["tested_refs"] == ["master", "python-sdk@master"]


def test_report_md_frontmatter_is_schema_valid(tmp_path) -> None:
    summary_path = tmp_path / "summary.json"
    out_path = tmp_path / "report.md"
    _run(
        [
            "report",
            "--pytest-json",
            str(FIXTURES / "pytest-report-pass.json"),
            "--summary",
            str(summary_path),
            "--out",
            str(out_path),
            "--date",
            "2026-06-18",
            "--tested-refs",
            "master",
        ]
    )
    md = out_path.read_text()
    assert md.startswith("---\n")
    frontmatter = md.split("---\n", 2)[1]
    for field in reports.FRONTMATTER_FIELDS:
        assert f"{field}:" in frontmatter


def test_report_output_is_deterministic_for_fixture(tmp_path) -> None:
    """Two identical runs over the same fixture yield byte-identical artifacts."""
    args = [
        "report",
        "--pytest-json",
        str(FIXTURES / "pytest-report-pass.json"),
        "--date",
        "2026-06-18",
        "--run-url",
        "https://example/run/9",
        "--tested-refs",
        "master, node-sdk@master",
        "--retain",
        "short-term",
        "--scope",
        "OSS runtime + all language SDKs + installer paths",
    ]
    s1, r1 = tmp_path / "s1.json", tmp_path / "r1.md"
    s2, r2 = tmp_path / "s2.json", tmp_path / "r2.md"
    _run(args + ["--summary", str(s1), "--out", str(r1)])
    _run(args + ["--summary", str(s2), "--out", str(r2)])
    assert s1.read_text() == s2.read_text()
    assert r1.read_text() == r2.read_text()


def test_report_render_only_from_existing_summary(tmp_path) -> None:
    """With no --pytest-json, an existing summary.json is rendered as-is."""
    summary_path = tmp_path / "summary.json"
    out_path = tmp_path / "report.md"
    # First produce a summary.json from the fixture.
    _run(
        [
            "report",
            "--pytest-json",
            str(FIXTURES / "pytest-report-pass.json"),
            "--summary",
            str(summary_path),
            "--out",
            str(tmp_path / "first.md"),
            "--date",
            "2026-06-18",
            "--tested-refs",
            "master",
        ]
    )
    # Now render-only from that summary.json.
    code = _run(["report", "--summary", str(summary_path), "--out", str(out_path)])
    assert code == 0
    assert (tmp_path / "first.md").read_text() == out_path.read_text()


def test_report_fail_without_related_issue_errors(tmp_path, capsys) -> None:
    code = _run(
        [
            "report",
            "--pytest-json",
            str(FIXTURES / "pytest-report-fail.json"),
            "--summary",
            str(tmp_path / "s.json"),
            "--out",
            str(tmp_path / "r.md"),
            "--tested-refs",
            "master",
        ]
    )
    assert code == 1
    assert "related_issue" in capsys.readouterr().err


def test_report_fail_with_related_issue_is_partial(tmp_path) -> None:
    summary_path = tmp_path / "s.json"
    code = _run(
        [
            "report",
            "--pytest-json",
            str(FIXTURES / "pytest-report-fail.json"),
            "--summary",
            str(summary_path),
            "--out",
            str(tmp_path / "r.md"),
            "--tested-refs",
            "master",
            "--related-issue",
            "AAASM-9999",
        ]
    )
    assert code == 0
    assert json.loads(summary_path.read_text())["result"] == "partial"


def test_report_missing_summary_input_errors(tmp_path) -> None:
    code = _run(
        ["report", "--summary", str(tmp_path / "missing.json"), "--out", str(tmp_path / "r.md")]
    )
    assert code == 1


@pytest.mark.parametrize("run_type", list(reports.RUN_TYPES))
def test_report_accepts_all_run_types(tmp_path, run_type: str) -> None:
    code = _run(
        [
            "report",
            "--pytest-json",
            str(FIXTURES / "pytest-report-pass.json"),
            "--summary",
            str(tmp_path / "s.json"),
            "--out",
            str(tmp_path / "r.md"),
            "--tested-refs",
            "master",
            "--run-type",
            run_type,
        ]
    )
    assert code == 0


def _mixed_args(tmp_path) -> list[str]:
    return [
        "report",
        "--pytest-json",
        str(FIXTURES / "pytest-report-mixed.json"),
        "--summary",
        str(tmp_path / "s.json"),
        "--out",
        str(tmp_path / "r.md"),
        "--tested-refs",
        "master",
        "--related-issue",
        "AAASM-1",
    ]


def test_report_jira_flag_writes_jira_report(tmp_path) -> None:
    jira_path = tmp_path / "jira.md"
    code = _run(_mixed_args(tmp_path) + ["--jira", str(jira_path)])
    assert code == 0
    text = jira_path.read_text()
    assert "h2. Verification Evidence" in text
    assert "tests/public/test_node_sdk.py::test_node_sdk_init" in text


def test_strict_flag_fails_on_unjustified_skip(tmp_path, capsys) -> None:
    code = _run(_mixed_args(tmp_path) + ["--strict"])
    assert code == 1
    err = capsys.readouterr().err
    assert "un-justified skip" in err
    assert "test_allow_deny" in err


def test_strict_env_var_fails_on_unjustified_skip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("AASM_VERIFY_STRICT", "1")
    code = _run(_mixed_args(tmp_path))
    assert code == 1


def test_strict_mode_passes_when_all_skips_justified(tmp_path, monkeypatch) -> None:
    # The all-pass fixture's lone skip carries an env-justified reason once
    # routed through the auditor, so a justified-only run exits 0 under strict.
    monkeypatch.setenv("AASM_VERIFY_STRICT", "1")
    summary_path = tmp_path / "s.json"
    data = {
        "tests": [
            {
                "nodeid": "tests/public/test_a.py::t",
                "keywords": ["sdk"],
                "outcome": "skipped",
                "call": {"longrepr": ["a.py", 1, "Skipped: binary not found in PATH"]},
            }
        ]
    }
    s = reports.summary_from_pytest_json(
        data,
        run_type="scheduled",
        date="2026-06-18",
        workflow_run_url="",
        tested_refs=["master"],
        retain="short-term",
    )
    reports.write_summary_json(str(summary_path), s)
    code = _run(["report", "--summary", str(summary_path), "--out", str(tmp_path / "r.md")])
    assert code == 0


def test_report_rejects_pytest_json_traversal(tmp_path, monkeypatch, capsys) -> None:
    """A relative ``..`` --pytest-json path is rejected, not opened (S8707)."""
    monkeypatch.chdir(tmp_path)
    code = _run(
        [
            "report",
            "--pytest-json",
            "../../../etc/passwd",
            "--summary",
            "summary.json",
            "--out",
            "report.md",
        ]
    )
    assert code == 1
    assert "outside the allowed base" in capsys.readouterr().err
    assert not (tmp_path / "summary.json").exists()


def test_report_rejects_summary_input_traversal(tmp_path, monkeypatch, capsys) -> None:
    """A relative ``..`` --summary input path is rejected before any read."""
    monkeypatch.chdir(tmp_path)
    code = _run(["report", "--summary", "../../secret.json", "--out", "report.md"])
    assert code == 1
    assert "outside the allowed base" in capsys.readouterr().err


def test_report_rejects_out_traversal(tmp_path, monkeypatch, capsys) -> None:
    """A relative ``..`` --out path is rejected before report.md is written."""
    monkeypatch.chdir(tmp_path)
    code = _run(
        [
            "report",
            "--pytest-json",
            str(FIXTURES / "pytest-report-pass.json"),
            "--summary",
            "summary.json",
            "--out",
            "../../escape.md",
            "--tested-refs",
            "master",
        ]
    )
    assert code == 1
    assert "outside the allowed base" in capsys.readouterr().err
