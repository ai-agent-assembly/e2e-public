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
            "https://github.com/ai-agent-assembly/agent-assembly-integration-tests/actions/runs/1",
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
