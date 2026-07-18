"""Unit tests for the static marker-audit tool (AAASM-4479).

Everything here is offline and fixture-driven: markers are enumerated straight
from source strings / throwaway files, and the Jira status cross-check is
exercised through an injected fake resolver so no network is touched.
"""

from __future__ import annotations

from pathlib import Path

from aasm_verify import skip_audit

# A synthetic test file exercising every marker shape the audit must recognize.
_FIXTURE = """
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
"""


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


def test_reason_resolved_from_module_level_constant() -> None:
    # A reason factored into a module-level string constant (the DENY_XFAIL_REASON
    # / _HOMEBREW_SKIP_REASON pattern) must still be statically classifiable: the
    # audit resolves the Name to the constant's literal so its ticket / env phrase
    # is recovered rather than read as an empty reason.
    src = (
        "import pytest\n"
        'DENY = "deny path unprovable today — AAASM-3172 flips it once fixed"\n'
        'GATE = "Homebrew tap not published — set AASM_HOMEBREW_GATE=1 to enable"\n'
        "@pytest.mark.xfail(strict=True, reason=DENY)\n"
        "def test_deny():\n    assert False\n"
        "@pytest.mark.skipif(True, reason=GATE)\n"
        "def test_gate():\n    assert True\n"
    )
    markers = skip_audit.collect_markers_from_source(src, "tests/t.py")
    deny = next(m for m in markers if m.kind == "xfail")
    assert deny.ticket == "AAASM-3172"
    gate = next(m for m in markers if m.kind == "skipif")
    assert gate.ticket is None
    assert gate.justified  # env requirement ("set AASM_HOMEBREW_GATE=1") in the constant


def test_reason_constant_via_fstring_literals() -> None:
    # An f-string constant contributes its literal parts (interpolations dropped),
    # enough to recover the env phrase — the CREWAI_PY314 / _EXAMPLES pattern.
    src = (
        "import pytest\n"
        'REASON = f"examples repo not found — clone it alongside {here} to run"\n'
        "def test_x():\n    pytest.skip(REASON)\n"
    )
    marker = skip_audit.collect_markers_from_source(src, "tests/t.py")[0]
    assert marker.justified  # "not found" / "clone" survive the f-string


def test_classification_tag_justifies_marker() -> None:
    src = (
        "import pytest\n"
        "def test_a():\n    pytest.skip('dist not built (classification: known_prerequisite)')\n"
        "def test_b():\n    pytest.skip('flaky net (classification: external_flake)')\n"
        "def test_c():\n    pytest.skip('wrong version (classification: release_blocker)')\n"
    )
    markers = skip_audit.collect_markers_from_source(src, "tests/t.py")
    audit = skip_audit.MarkerAudit(markers=markers)
    unref = {m.reason for m in audit.unreferenced}
    # known_prerequisite / external_flake are justified; release_blocker is not.
    assert unref == {"wrong version (classification: release_blocker)"}


def test_string_literal_skip_calls_are_not_collected(tmp_path: Path) -> None:
    # pytest.skip(...) appearing *inside a string* (e.g. pytester.makepyfile)
    # is a Constant, not a Call — the AST tool must not mistake it for a marker.
    src = "def test_a():\n    body = \"pytest.skip('x')\"\n    assert body\n"
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


def test_partial_resolver_failure_is_recorded_not_reported_clean() -> None:
    # One ticket's status can't be checked (auth/network error); the others
    # resolve fine. The unresolved ticket must land in `unresolved` — NOT be
    # silently treated as "not stale" / clean.
    def resolver(ticket: str) -> str | None:
        if ticket == "AAASM-9001":
            raise skip_audit.JiraResolverError("Jira returned HTTP 401")
        return "In Progress"

    markers = _markers()
    tickets = {m.ticket for m in markers if m.ticket}
    stale, unresolved = skip_audit.resolve_ticket_statuses(tickets, resolver)
    assert unresolved == frozenset({"AAASM-9001"})
    assert "AAASM-9001" not in stale
    audit = skip_audit.MarkerAudit(
        markers=markers, stale=stale, unresolved=unresolved, jira_checked=True
    )
    # The skipif marker pinned to the unresolved ticket surfaces as unverified,
    # and does NOT masquerade as a clean (stale) result.
    assert [m.kind for m in audit.unresolved_markers] == ["skipif"]
    assert audit.stale_markers == []


def test_wholesale_resolver_failure_raises() -> None:
    # Every ticket fails to resolve (wrong/expired creds, wrong site). This must
    # NOT report a clean "stale: 0" — it raises so the run fails loudly instead.
    import pytest

    def always_fails(ticket: str) -> str | None:
        raise skip_audit.JiraResolverError("auth failure")

    markers = _markers()
    tickets = {m.ticket for m in markers if m.ticket}
    assert tickets  # guard: the fixture has ticketed markers to attempt
    with pytest.raises(skip_audit.JiraResolverError):
        skip_audit.resolve_ticket_statuses(tickets, always_fails)


def test_audit_markers_raises_on_wholesale_resolver_failure(tmp_path: Path) -> None:
    # End-to-end via audit_markers: a resolver that always errors must not yield
    # a green audit with empty stale/unresolved — it raises.
    import pytest

    (tmp_path / "test_x.py").write_text(
        "import pytest\n@pytest.mark.skip(reason='AAASM-1: gap')\ndef test_y():\n    pass\n"
    )

    def always_fails(ticket: str) -> str | None:
        raise skip_audit.JiraResolverError("network down")

    with pytest.raises(skip_audit.JiraResolverError):
        skip_audit.audit_markers(tmp_path, root=tmp_path, resolver=always_fails)


def test_not_found_ticket_is_never_fatal() -> None:
    # A genuine "ticket not found" (resolver returns None) stays never-fatal:
    # neither stale nor unresolved, and no wholesale-failure raise.
    stale, unresolved = skip_audit.resolve_ticket_statuses({"AAASM-1", "AAASM-2"}, lambda _t: None)
    assert stale == frozenset()
    assert unresolved == frozenset()


def test_render_flags_unresolved_distinctly_from_clean() -> None:
    markers = _markers()
    audit = skip_audit.MarkerAudit(
        markers=markers, unresolved=frozenset({"AAASM-9001"}), jira_checked=True
    )
    text = skip_audit.render_marker_audit(audit)
    assert "## Unable to verify (Jira status not checkable)" in text
    assert "UNABLE TO VERIFY" in text  # summary line warns against reading as clean


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
    # The AAASM-3172 deny-enforcement xfail is a known, ticket-referenced marker
    # (the behavioral deny xfails were re-pointed from the Done AAASM-3021 to the
    # still-open gate AAASM-3172 in AAASM-4827).
    assert any(m.ticket == "AAASM-3172" for m in audit.markers)


# The AAASM-4853 de-stale set: six now-Done tickets that markers used to cite.
# The env-justified skips dropped the ref (staying justified by an env phrase /
# ``classification:`` tag); the ENFORCEMENT_MODES parity skip was re-pointed from
# the Done coverage Story AAASM-3158 to the open defect Bug AAASM-4856. None of
# these Done keys may reappear as a live marker citation or the weekly
# ``markers --check-jira --strict`` drift lane goes red on a stale citation again.
_DESTALED_DONE_TICKETS = frozenset(
    {"AAASM-3151", "AAASM-3157", "AAASM-3158", "AAASM-3525", "AAASM-3533", "AAASM-3955"}
)


def test_destaled_done_tickets_no_longer_cited_by_any_marker() -> None:
    tests_dir = Path(__file__).parent
    audit = skip_audit.audit_markers(tests_dir, root=tests_dir.parent)
    cited = {m.ticket for m in audit.markers if m.ticket}
    assert cited.isdisjoint(_DESTALED_DONE_TICKETS), (
        f"a de-staled Done ticket is cited again: {sorted(cited & _DESTALED_DONE_TICKETS)}"
    )
    # The parity gap re-point must stay visible against the open defect ticket.
    assert "AAASM-4856" in cited
    # De-staling must not have dropped any marker into an unreferenced policy
    # violation: every env-justified skip kept an env phrase / classification tag.
    assert audit.unreferenced == []


def _markers_cli_args(tmp_path: Path) -> object:
    import argparse

    return argparse.Namespace(
        check_jira=True, strict=True, json=False, tests_dir=str(tmp_path), root=str(tmp_path)
    )


def _two_ticketed_markers(tmp_path: Path) -> None:
    (tmp_path / "test_x.py").write_text(
        "import pytest\n"
        "@pytest.mark.skip(reason='AAASM-1: gap one')\n"
        "def test_a():\n    pass\n"
        "@pytest.mark.skip(reason='AAASM-2: gap two')\n"
        "def test_b():\n    pass\n"
    )


def test_cli_markers_strict_exits_nonzero_on_partial_unresolved(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # LOW defect (cli.py): a PARTIAL Jira failure (one ticket resolves, one hits
    # 401/timeout) must make `markers --strict` exit non-zero — not read as clean.
    # AAASM-4850 fixed only the wholesale case; this closes the partial case.
    from aasm_verify import cli

    def partial_resolver(ticket: str) -> str | None:
        if ticket == "AAASM-2":
            raise skip_audit.JiraResolverError("Jira returned HTTP 401 for AAASM-2")
        return "In Progress"

    monkeypatch.setattr(cli.skip_audit, "jira_resolver_from_env", lambda: partial_resolver)
    _two_ticketed_markers(tmp_path)
    assert cli.cmd_markers(_markers_cli_args(tmp_path)) == 1


def test_cli_markers_strict_exits_zero_when_all_resolve_open(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    # Contrast: when every ticket resolves to an open status, strict exits 0 — so
    # the non-zero above is specifically the unresolved marker, not the tickets.
    from aasm_verify import cli

    monkeypatch.setattr(cli.skip_audit, "jira_resolver_from_env", lambda: lambda _t: "In Progress")
    _two_ticketed_markers(tmp_path)
    assert cli.cmd_markers(_markers_cli_args(tmp_path)) == 0
