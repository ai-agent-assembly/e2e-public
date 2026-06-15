"""Unit tests for aasm_verify.reports (summary.json + report.md generator)."""

from __future__ import annotations

import json

import pytest

from aasm_verify import reports
from aasm_verify.reports import Suite, Summary


def _summary(**overrides: object) -> Summary:
    base: dict = {
        "run_type": "scheduled",
        "result": "pass",
        "date": "2026-06-18",
        "workflow_run_url": "https://github.com/ai-agent-assembly/agent-assembly-integration-tests/actions/runs/1",
        "tested_refs": ["master"],
        "retain": "short-term",
        "suites": [Suite("test_python_sdk", "pass", 12)],
    }
    base.update(overrides)
    return Summary(**base)  # type: ignore[arg-type]


def test_channel_identity_is_public_integration() -> None:
    s = _summary()
    assert s.report_type == "public-integration"
    assert s.source_repo == "agent-assembly-integration-tests"


def test_frontmatter_has_nine_fields_in_schema_order() -> None:
    fm = _summary().frontmatter()
    assert list(fm.keys()) == list(reports.FRONTMATTER_FIELDS)
    assert len(fm) == 9


def test_invalid_run_type_rejected() -> None:
    with pytest.raises(ValueError, match="run_type"):
        _summary(run_type="bogus")


def test_invalid_result_rejected() -> None:
    with pytest.raises(ValueError, match="result"):
        _summary(result="green")


def test_invalid_retain_rejected() -> None:
    with pytest.raises(ValueError, match="retain"):
        _summary(retain="forever")


def test_empty_tested_refs_rejected() -> None:
    with pytest.raises(ValueError, match="tested_refs"):
        _summary(tested_refs=[])


def test_fail_result_requires_related_issue() -> None:
    with pytest.raises(ValueError, match="related_issue"):
        _summary(result="fail", related_issue=None)


def test_partial_result_requires_related_issue() -> None:
    with pytest.raises(ValueError, match="related_issue"):
        _summary(result="partial", related_issue=None)


def test_fail_result_with_related_issue_ok() -> None:
    s = _summary(result="fail", related_issue="AAASM-1")
    assert s.frontmatter()["related_issue"] == "AAASM-1"


def test_counts_derived_from_suites() -> None:
    s = _summary(
        suites=[
            Suite("a", "pass"),
            Suite("b", "pass"),
            Suite("c", "fail"),
            Suite("d", "skipped"),
        ],
        result="partial",
        related_issue="AAASM-1",
    )
    assert s.counts == {"total": 4, "passed": 2, "failed": 1, "skipped": 1}


def test_summary_dict_roundtrip() -> None:
    s = _summary(
        suites=[Suite("a", "pass", 5, "note")],
        scope="custom scope",
    )
    rebuilt = reports.summary_from_dict(s.as_dict())
    assert rebuilt.as_dict() == s.as_dict()


def test_write_summary_json_is_deterministic(tmp_path) -> None:
    s = _summary()
    p1 = tmp_path / "a.json"
    p2 = tmp_path / "b.json"
    reports.write_summary_json(str(p1), s)
    reports.write_summary_json(str(p2), s)
    assert p1.read_text() == p2.read_text()
    # Valid JSON, frontmatter keys present.
    data = json.loads(p1.read_text())
    for field in reports.FRONTMATTER_FIELDS:
        assert field in data


def test_render_report_md_frontmatter_matches_schema() -> None:
    md = reports.render_report_md(_summary())
    assert md.startswith("---\n")
    body = md.split("---\n", 2)
    frontmatter_block = body[1]
    for field in reports.FRONTMATTER_FIELDS:
        assert f"{field}:" in frontmatter_block
    # public-integration channel identity is present and correct.
    assert "report_type: public-integration" in frontmatter_block
    assert "source_repo: agent-assembly-integration-tests" in frontmatter_block


def test_render_report_md_is_deterministic() -> None:
    s = _summary()
    assert reports.render_report_md(s) == reports.render_report_md(s)


def test_render_report_md_none_related_issue_serializes_null() -> None:
    md = reports.render_report_md(_summary())
    assert "related_issue: null" in md


def test_render_report_md_lists_tested_refs() -> None:
    md = reports.render_report_md(_summary(tested_refs=["v0.1.0", "python-sdk@0.1.0"]))
    assert "  - v0.1.0" in md
    assert "  - python-sdk@0.1.0" in md


def test_summary_from_pytest_json_aggregates_suites_by_file() -> None:
    data = {
        "tests": [
            {"nodeid": "tests/public/test_a.py::test_one", "outcome": "passed", "duration": 1.4},
            {"nodeid": "tests/public/test_a.py::test_two", "outcome": "passed", "duration": 0.6},
            {"nodeid": "tests/public/test_b.py::test_x", "outcome": "skipped", "duration": 0.0},
        ]
    }
    s = reports.summary_from_pytest_json(
        data,
        run_type="scheduled",
        date="2026-06-18",
        workflow_run_url="https://example/run/1",
        tested_refs=["master"],
        retain="short-term",
    )
    names = [su.name for su in s.suites]
    assert names == ["test_a", "test_b"]
    # Durations summed and rounded to whole seconds (1.4 + 0.6 = 2.0).
    assert s.suites[0].duration_seconds == 2
    assert s.suites[0].result == "pass"
    assert s.suites[1].result == "skipped"
    assert s.result == "pass"


def test_summary_from_pytest_json_fail_rolls_up_to_partial() -> None:
    data = {
        "tests": [
            {"nodeid": "tests/public/test_a.py::test_one", "outcome": "passed", "duration": 1.0},
            {"nodeid": "tests/public/test_b.py::test_x", "outcome": "failed", "duration": 1.0},
        ]
    }
    s = reports.summary_from_pytest_json(
        data,
        run_type="scheduled",
        date="2026-06-18",
        workflow_run_url="https://example/run/1",
        tested_refs=["master"],
        retain="long-term",
        related_issue="AAASM-1",
    )
    assert s.result == "partial"


def test_summary_from_pytest_json_all_fail_rolls_up_to_fail() -> None:
    data = {
        "tests": [
            {"nodeid": "tests/public/test_a.py::test_one", "outcome": "failed", "duration": 1.0},
        ]
    }
    s = reports.summary_from_pytest_json(
        data,
        run_type="scheduled",
        date="2026-06-18",
        workflow_run_url="https://example/run/1",
        tested_refs=["master"],
        retain="long-term",
        related_issue="AAASM-1",
    )
    assert s.result == "fail"


def test_generator_output_does_not_leak_token_like_strings() -> None:
    # The generator only emits normalized counts + suite names, never raw env.
    md = reports.render_report_md(_summary())
    summary_json = json.dumps(_summary().as_dict())
    for needle in ("ghp_", "github_pat_", "AASM_", "Bearer ", "token="):
        assert needle not in md
        assert needle not in summary_json
