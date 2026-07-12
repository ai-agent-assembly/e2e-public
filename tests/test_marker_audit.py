"""Unit tests for the static marker-audit tool (AAASM-4479).

Everything here is offline and fixture-driven: markers are enumerated straight
from source strings / throwaway files, and the Jira status cross-check is
exercised through an injected fake resolver so no network is touched.
"""

from __future__ import annotations

from pathlib import Path

from aasm_verify import skip_audit

# A synthetic test file exercising every marker shape the audit must recognize.
_FIXTURE = '''
import pytest


@pytest.mark.xfail(
    reason="AAASM-3021: production wiring gap, deny not enforced end-to-end.",
    strict=False,
)
def test_xfail_with_ticket():
    assert False


@pytest.mark.skip(reason="temporarily disabled while we think about it")
def test_bare_skip_no_ticket():
    assert True


@pytest.mark.skipif(True, reason="AAASM-9001 blocks this path")
def test_skipif_with_ticket():
    assert True


# AAASM-7777 — ref lives in a leading comment, not the reason kwarg
@pytest.mark.xfail(reason="known gap", strict=True)
def test_xfail_ticket_in_comment():
    assert False


@pytest.mark.rc_pending(reason="AAASM-4477: native binding check masks a real defect")
def test_rc_pending_quarantined():
    assert False


def test_inline_env_skip():
    pytest.skip("aasm binary not found in PATH")


def test_inline_bare_skip():
    pytest.skip("just because")
'''


def _markers(source: str = _FIXTURE) -> list[skip_audit.Marker]:
    return skip_audit.collect_markers_from_source(source, "tests/fixture.py")


def _by_line(markers: list[skip_audit.Marker], lineno: int) -> skip_audit.Marker:
    return next(m for m in markers if m.lineno == lineno)


def test_collect_finds_all_marker_kinds() -> None:
    kinds = sorted(m.kind for m in _markers())
    assert kinds == [
        "rc_pending",
        "skip",
        "skip_call",
        "skip_call",
        "skipif",
        "xfail",
        "xfail",
    ]


def test_ticket_extracted_from_reason() -> None:
    xfail = next(m for m in _markers() if m.kind == "xfail" and "3021" in m.reason)
    assert xfail.ticket == "AAASM-3021"
    assert xfail.strict is False


def test_ticket_extracted_from_leading_comment() -> None:
    marker = next(m for m in _markers() if m.reason == "known gap")
    assert marker.ticket == "AAASM-7777"
    assert marker.strict is True


def test_skipif_ticket_recognized() -> None:
    marker = next(m for m in _markers() if m.kind == "skipif")
    assert marker.ticket == "AAASM-9001"


def test_rc_pending_marker_carries_blocking_ticket() -> None:
    marker = next(m for m in _markers() if m.kind == "rc_pending")
    assert marker.is_rc_pending
    assert marker.ticket == "AAASM-4477"


def test_env_justified_skip_is_not_unreferenced() -> None:
    marker = next(m for m in _markers() if "not found in PATH" in m.reason)
    assert marker.ticket is None
    assert marker.justified  # env requirement justifies it


def test_bare_skip_is_unreferenced() -> None:
    audit = skip_audit.MarkerAudit(markers=_markers())
    reasons = {m.reason for m in audit.unreferenced}
    assert "temporarily disabled while we think about it" in reasons
    assert "just because" in reasons
    # Ticketed / env-justified / rc_pending markers must NOT be flagged.
    assert not any(m.ticket for m in audit.unreferenced)


def test_rc_quarantine_registry_lists_only_rc_pending() -> None:
    audit = skip_audit.MarkerAudit(markers=_markers())
    assert [m.kind for m in audit.rc_quarantine] == ["rc_pending"]


def test_string_literal_skip_calls_are_not_collected(tmp_path: Path) -> None:
    # pytest.skip(...) appearing *inside a string* (e.g. pytester.makepyfile)
    # is a Constant, not a Call — the AST tool must not mistake it for a marker.
    src = 'def test_a():\n    body = "pytest.skip(\'x\')"\n    assert body\n'
    assert skip_audit.collect_markers_from_source(src, "t.py") == []


def test_collect_markers_walks_directory(tmp_path: Path) -> None:
    (tmp_path / "test_a.py").write_text(
        "import pytest\n@pytest.mark.skip(reason='no ticket here')\ndef test_x():\n    pass\n"
    )
    (tmp_path / "test_b.py").write_text(
        "import pytest\n@pytest.mark.xfail(reason='AAASM-1: gap')\ndef test_y():\n    pass\n"
    )
    markers = skip_audit.collect_markers(tmp_path, root=tmp_path)
    assert [m.path for m in markers] == ["test_a.py", "test_b.py"]


def test_collect_skips_unparseable_files(tmp_path: Path) -> None:
    (tmp_path / "test_broken.py").write_text("def oops(:\n")
    (tmp_path / "test_ok.py").write_text(
        "import pytest\n@pytest.mark.skip(reason='x')\ndef test_z():\n    pass\n"
    )
    markers = skip_audit.collect_markers(tmp_path, root=tmp_path)
    assert [m.path for m in markers] == ["test_ok.py"]


def test_stale_check_flags_closed_tickets() -> None:
    # Fake resolver: only AAASM-9001 is closed. The skipif marker pinned to it
    # is therefore stale; the in-progress / to-do ones are not.
    statuses = {"AAASM-3021": "In Progress", "AAASM-9001": "Done", "AAASM-4477": "To Do"}
    markers = _markers()
    stale = skip_audit.stale_tickets({m.ticket for m in markers if m.ticket}, statuses.get)
    result = skip_audit.MarkerAudit(markers=markers, stale=stale, jira_checked=True)
    assert stale == frozenset({"AAASM-9001"})
    assert [m.kind for m in result.stale_markers] == ["skipif"]


def test_jira_resolver_absent_without_env() -> None:
    assert skip_audit.jira_resolver_from_env(environ={}) is None
    assert (
        skip_audit.jira_resolver_from_env(
            environ={"AASM_VERIFY_JIRA_URL": "x", "AASM_VERIFY_JIRA_EMAIL": "y"}
        )
        is None
    )


def test_jira_resolver_present_with_full_env() -> None:
    env = {
        "AASM_VERIFY_JIRA_URL": "https://example.atlassian.net",
        "AASM_VERIFY_JIRA_EMAIL": "a@b.c",
        "AASM_VERIFY_JIRA_TOKEN": "tok",
    }
    assert skip_audit.jira_resolver_from_env(environ=env) is not None


def test_render_report_has_all_sections() -> None:
    audit = skip_audit.MarkerAudit(markers=_markers())
    text = skip_audit.render_marker_audit(audit)
    assert "# Marker Audit (AAASM-4479)" in text
    assert "## Unreferenced markers (policy violations)" in text
    assert "## rc-quarantine registry (rc_pending)" in text
    assert "## Stale markers" in text
    assert "AAASM-4477" in text  # rc-quarantine entry rendered


def test_real_tree_audit_is_offline_and_finds_markers() -> None:
    # Dogfood the tool against this repo's real tests/ dir (offline).
    tests_dir = Path(__file__).parent
    audit = skip_audit.audit_markers(tests_dir, root=tests_dir.parent)
    assert not audit.jira_checked
    assert len(audit.markers) > 0
    # The AAASM-3021 xfail placeholder is a known, ticket-referenced marker.
    assert any(m.ticket == "AAASM-3021" for m in audit.markers)
