"""Report generation for public-integration verification runs.

This module turns a verification run into the two artifacts the AAASM-2236
report contract defines:

* ``summary.json`` — the machine-readable, normalized result. Its first nine
  top-level keys map 1:1 onto the published ``report.md`` frontmatter; the
  remaining keys (``scope``, ``suites``, ``counts``) feed the human-readable
  body. See ``internal-docs`` ``docs/verification-reports/summary-json.md``.
* ``report.md`` — the curated report whose YAML frontmatter matches the
  AAASM-2236 frontmatter schema 1:1 and is published into the
  ``public-integration/`` channel by ``publish-inner-doc-report.sh``.

The channel is fixed to ``public-integration`` for this CLI; ``source_repo`` is
the public integration-tests repo. Public reports do not need the private
sanitizer, but generator output is built only from normalized counts and suite
names (never raw log text), so no secrets are echoed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from aasm_verify import skip_audit
from aasm_verify.pathsafe import safe_path

# Fixed identity for the public-integration channel (AAASM-2236).
REPORT_TYPE: str = "public-integration"
SOURCE_REPO: str = "e2e-public"

# Enum domains from the frontmatter schema.
RUN_TYPES: tuple[str, ...] = ("pr", "scheduled", "release", "manual")
RESULTS: tuple[str, ...] = ("pass", "fail", "partial")
RETAINS: tuple[str, ...] = ("long-term", "short-term")

# Per-area count buckets, in display order. ``unexpected_skipped`` is the
# subset of ``skipped`` whose reason carries no env requirement or Jira ref;
# in strict mode it fails the run (AAASM-3155).
AREA_COUNT_KEYS: tuple[str, ...] = (
    "passed",
    "failed",
    "skipped",
    "unexpected_skipped",
    "xfailed",
    "xpassed",
)

# The nine frontmatter keys, in schema order.
FRONTMATTER_FIELDS: tuple[str, ...] = (
    "report_type",
    "run_type",
    "result",
    "date",
    "source_repo",
    "workflow_run_url",
    "tested_refs",
    "related_issue",
    "retain",
)


@dataclass
class Suite:
    """One verification suite/check result for the Results table."""

    name: str
    result: str
    duration_seconds: int = 0
    notes: str = ""

    def as_dict(self) -> dict:
        return {
            "name": self.name,
            "result": self.result,
            "duration_seconds": self.duration_seconds,
            "notes": self.notes,
        }


@dataclass
class Summary:
    """Normalized verification result — the source of truth for report.md.

    The first nine fields are the frontmatter schema (1:1); ``scope``, ``suites``
    and ``counts`` feed the report body.
    """

    run_type: str
    result: str
    date: str
    workflow_run_url: str
    tested_refs: list[str]
    retain: str
    related_issue: str | None = None
    scope: str = ""
    suites: list[Suite] = field(default_factory=list)
    report_type: str = REPORT_TYPE
    source_repo: str = SOURCE_REPO
    # Per-area test-outcome counts: {area: {bucket: n}} over AREA_COUNT_KEYS.
    area_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    # Skipped tests whose reason names no env requirement or Jira ref.
    unjustified_skips: list[dict] = field(default_factory=list)
    # Nodeids of failed/errored tests, for the Jira-ready evidence report.
    failed_tests: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.run_type not in RUN_TYPES:
            raise ValueError(f"run_type must be one of {RUN_TYPES}, got {self.run_type!r}")
        if self.result not in RESULTS:
            raise ValueError(f"result must be one of {RESULTS}, got {self.result!r}")
        if self.retain not in RETAINS:
            raise ValueError(f"retain must be one of {RETAINS}, got {self.retain!r}")
        if not self.tested_refs:
            raise ValueError("tested_refs must contain at least one ref")
        if self.result in ("fail", "partial") and not self.related_issue:
            raise ValueError("related_issue is required when result is 'fail' or 'partial'")

    @property
    def counts(self) -> dict[str, int]:
        """Suite-level pass/fail/skip counts derived from ``suites``."""
        passed = sum(1 for s in self.suites if s.result == "pass")
        failed = sum(1 for s in self.suites if s.result == "fail")
        skipped = sum(1 for s in self.suites if s.result == "skipped")
        return {
            "total": len(self.suites),
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        }

    def frontmatter(self) -> dict:
        """The nine-field frontmatter mapping, in schema order."""
        return {
            "report_type": self.report_type,
            "run_type": self.run_type,
            "result": self.result,
            "date": self.date,
            "source_repo": self.source_repo,
            "workflow_run_url": self.workflow_run_url,
            "tested_refs": list(self.tested_refs),
            "related_issue": self.related_issue,
            "retain": self.retain,
        }

    def as_dict(self) -> dict:
        """Full summary.json shape: frontmatter keys + scope/suites/counts."""
        data = self.frontmatter()
        data["scope"] = self.scope
        data["suites"] = [s.as_dict() for s in self.suites]
        data["counts"] = self.counts
        data["area_counts"] = {area: dict(buckets) for area, buckets in self.area_counts.items()}
        data["unjustified_skips"] = [dict(s) for s in self.unjustified_skips]
        data["failed_tests"] = list(self.failed_tests)
        return data


def summary_from_dict(data: dict) -> Summary:
    """Rebuild a :class:`Summary` from a parsed ``summary.json`` mapping."""
    suites = [
        Suite(
            name=s["name"],
            result=s["result"],
            duration_seconds=int(s.get("duration_seconds", 0)),
            notes=s.get("notes", ""),
        )
        for s in data.get("suites", [])
    ]
    return Summary(
        run_type=data["run_type"],
        result=data["result"],
        date=data["date"],
        workflow_run_url=data["workflow_run_url"],
        tested_refs=list(data["tested_refs"]),
        retain=data["retain"],
        related_issue=data.get("related_issue"),
        scope=data.get("scope", ""),
        suites=suites,
        report_type=data.get("report_type", REPORT_TYPE),
        source_repo=data.get("source_repo", SOURCE_REPO),
        area_counts={area: dict(buckets) for area, buckets in data.get("area_counts", {}).items()},
        unjustified_skips=[dict(s) for s in data.get("unjustified_skips", [])],
        failed_tests=list(data.get("failed_tests", [])),
    )


def write_summary_json(path: str, summary: Summary) -> None:
    """Write the machine-readable ``summary.json`` deterministically."""
    text = json.dumps(summary.as_dict(), indent=2, sort_keys=False)
    with open(safe_path(path), "w", encoding="utf-8") as fh:
        fh.write(text)
        fh.write("\n")


def _yaml_scalar(value: object) -> str:
    """Render a frontmatter scalar (None -> ``null``)."""
    if value is None:
        return "null"
    return str(value)


def render_frontmatter(summary: Summary) -> str:
    """Render the YAML frontmatter block (AAASM-2236 schema, 1:1, in order)."""
    fm = summary.frontmatter()
    lines = ["---"]
    for key in FRONTMATTER_FIELDS:
        value = fm[key]
        if key == "tested_refs":
            lines.append(f"{key}:")
            for ref in value:  # type: ignore[union-attr]
                lines.append(f"  - {ref}")
        else:
            lines.append(f"{key}: {_yaml_scalar(value)}")
    lines.append("---")
    return "\n".join(lines)


def _area_counts_table(summary: Summary) -> list[str]:
    """Render the per-area outcome counts as a Markdown table (empty if none)."""
    if not summary.area_counts:
        return []
    lines = [
        "## Counts by area",
        "",
        "| Area | Passed | Failed | Skipped | Unexpected skip | xfailed | xpassed |",
        "|---|---|---|---|---|---|---|",
    ]
    for area in sorted(summary.area_counts):
        b = summary.area_counts[area]
        lines.append(
            f"| {area} | {b.get('passed', 0)} | {b.get('failed', 0)} | "
            f"{b.get('skipped', 0)} | {b.get('unexpected_skipped', 0)} | "
            f"{b.get('xfailed', 0)} | {b.get('xpassed', 0)} |"
        )
    lines.append("")
    return lines


def _skip_audit_block(summary: Summary) -> list[str]:
    """Render the skip-audit block listing un-justified skips (empty if none)."""
    lines = ["## Skip audit", ""]
    if not summary.unjustified_skips:
        lines.append(
            "All skips are justified — each names an environment requirement "
            "or a linked Jira issue."
        )
        lines.append("")
        return lines
    lines.append(
        f"{len(summary.unjustified_skips)} skip(s) name no environment "
        "requirement or Jira issue. In strict mode "
        f"(`{skip_audit.STRICT_ENV_VAR}=1`) these fail the run."
    )
    lines.append("")
    lines.append("| Area | Test | Reason |")
    lines.append("|---|---|---|")
    for s in summary.unjustified_skips:
        reason = s.get("reason") or "—"
        lines.append(f"| {s.get('area', '')} | {s.get('nodeid', '')} | {reason} |")
    lines.append("")
    return lines


def render_report_md(summary: Summary) -> str:
    """Render the curated ``report.md`` body for the public-integration channel."""
    fm = summary.frontmatter()
    counts = summary.counts
    scope = summary.scope or "OSS runtime + all language SDKs + installer paths"

    parts: list[str] = [render_frontmatter(summary), ""]

    parts.append(f"# Verification Report — Public Integration ({summary.date})")
    parts.append("")

    parts.append("## Summary")
    parts.append("")
    refs = ", ".join(summary.tested_refs)
    parts.append(
        f"Public integration verification of {scope} against {refs}: "
        f"result **{summary.result}** "
        f"({counts['passed']}/{counts['total']} suites passed)."
    )
    parts.append("")

    parts.append("## Scope")
    parts.append("")
    parts.append("| Field | Value |")
    parts.append("|---|---|")
    parts.append(f"| Test scope | {scope} |")
    parts.append(f"| Trigger | {summary.run_type} |")
    parts.append(f"| Source repo | {summary.source_repo} |")
    parts.append(f"| Tested refs | {refs} |")
    parts.append(f"| Run URL | {summary.workflow_run_url} |")
    parts.append("")

    parts.append("## Results")
    parts.append("")
    parts.append("| Suite / check | Result | Notes |")
    parts.append("|---|---|---|")
    for suite in summary.suites:
        notes = suite.notes or ""
        parts.append(f"| {suite.name} | {suite.result} | {notes} |")
    parts.append("")

    parts.extend(_area_counts_table(summary))
    parts.extend(_skip_audit_block(summary))

    parts.append("## Failures and follow-up")
    parts.append("")
    if summary.result in ("fail", "partial"):
        parts.append(
            "One or more suites did not pass. See the linked issue and the "
            "GitHub Actions run for details (logs are not pasted here)."
        )
        parts.append("")
        parts.append(f"- Linked issue: {_yaml_scalar(summary.related_issue)}")
    else:
        parts.append("None — all suites passed.")
    parts.append("")

    parts.append("## Evidence")
    parts.append("")
    parts.append(
        "Curated evidence only. See the GitHub Actions run linked above for "
        "artifacts and logs. No secrets, private endpoints, or internal "
        "hostnames are included."
    )
    parts.append("")

    parts.append("## Retention")
    parts.append("")
    parts.append(f"Retention class: `{fm['retain']}` — see the publishing SOP.")
    parts.append("")

    return "\n".join(parts)


def write_report_md(path: str, summary: Summary) -> None:
    """Write the curated ``report.md`` deterministically."""
    with open(safe_path(path), "w", encoding="utf-8") as fh:
        fh.write(render_report_md(summary))


def render_jira_report(summary: Summary) -> str:
    """Render a Jira-ready evidence report for an internal ticket/comment.

    This is the internal-workflow companion to ``report.md`` (the published
    public-integration artifact) and the GitHub-issue failure path
    (``scripts/report-failure.sh``). It mirrors ``docs/evidence-template.md``
    and includes the commands, refs, environment, per-area counts, failed-test
    names, and the skip audit. Like every generator here it is built only from
    normalized data, so no secrets or internal endpoints are echoed.
    """
    refs = ", ".join(summary.tested_refs) or "n/a"
    verdict = {
        "pass": "✅ PASS — verification complete",
        "partial": "⚠️ PARTIAL — some areas failed",
        "fail": "❌ FAIL — blocking failures",
    }.get(summary.result, summary.result)

    parts: list[str] = []
    parts.append(f"h2. Verification Evidence — {summary.date}")
    parts.append("")
    parts.append(f"*Verdict:* {verdict}")
    parts.append(f"*Trigger:* {summary.run_type}")
    if summary.related_issue:
        parts.append(f"*Related issue:* {summary.related_issue}")
    parts.append("")

    parts.append("h3. Refs under test")
    parts.append("")
    for ref in summary.tested_refs:
        parts.append(f"* {ref}")
    if not summary.tested_refs:
        parts.append("* n/a")
    parts.append("")

    parts.append("h3. Environment")
    parts.append("")
    parts.append(f"* Source repo: {summary.source_repo}")
    parts.append(f"* Run URL: {summary.workflow_run_url or 'n/a'}")
    parts.append(f"* Retention: {summary.retain}")
    parts.append("")

    parts.append("h3. Commands")
    parts.append("")
    parts.append("{code}")
    parts.append("# verify the public stack at the refs above")
    parts.append("bash scripts/verify-public-stack.sh")
    parts.append("# regenerate this report from the pytest JSON")
    parts.append(
        "aasm-verify report --pytest-json report.json --summary summary.json "
        "--out report.md --jira jira-report.md --strict"
    )
    parts.append("{code}")
    parts.append("")

    parts.extend(_jira_area_counts(summary))
    parts.extend(_jira_failures(summary, refs))
    parts.extend(_jira_skip_audit(summary))
    return "\n".join(parts)


def _jira_area_counts(summary: Summary) -> list[str]:
    """Per-area counts as a Jira table (empty when no counts are present)."""
    if not summary.area_counts:
        return []
    lines = ["h3. Counts by area", ""]
    lines.append(
        "|| Area || Passed || Failed || Skipped || Unexpected skip || xfailed || xpassed ||"
    )
    for area in sorted(summary.area_counts):
        b = summary.area_counts[area]
        lines.append(
            f"| {area} | {b.get('passed', 0)} | {b.get('failed', 0)} | "
            f"{b.get('skipped', 0)} | {b.get('unexpected_skipped', 0)} | "
            f"{b.get('xfailed', 0)} | {b.get('xpassed', 0)} |"
        )
    lines.append("")
    return lines


def _jira_failures(summary: Summary, refs: str) -> list[str]:
    """Failed-test names section for the Jira report."""
    lines = ["h3. Failures", ""]
    if not summary.failed_tests:
        lines.append("None — no failed or errored tests.")
        lines.append("")
        return lines
    lines.append(f"{len(summary.failed_tests)} failing test(s) against {refs}:")
    for nodeid in summary.failed_tests:
        lines.append(f"* {{{{{nodeid}}}}}")
    lines.append("")
    return lines


def _jira_skip_audit(summary: Summary) -> list[str]:
    """Skip-audit section for the Jira report."""
    lines = ["h3. Skip audit", ""]
    if not summary.unjustified_skips:
        lines.append("All skips are justified (env requirement or linked Jira issue).")
        lines.append("")
        return lines
    lines.append(
        f"{len(summary.unjustified_skips)} un-justified skip(s) — strict mode "
        f"(_{skip_audit.STRICT_ENV_VAR}=1_) fails the run on these:"
    )
    for s in summary.unjustified_skips:
        reason = s.get("reason") or "<no reason given>"
        lines.append(f"* {{{{{s.get('nodeid', '')}}}}} — {reason}")
    lines.append("")
    return lines


def write_jira_report(path: str, summary: Summary) -> None:
    """Write the Jira-ready evidence report deterministically."""
    with open(safe_path(path), "w", encoding="utf-8") as fh:
        fh.write(render_jira_report(summary))


def _suite_name_from_nodeid(nodeid: str) -> str:
    """Derive a stable suite name from a pytest nodeid (file stem, no params)."""
    head = nodeid.split("::", 1)[0]
    stem = head.rsplit("/", 1)[-1]
    if stem.endswith(".py"):
        stem = stem[:-3]
    return stem


def _suites_from_pytest(data: dict) -> list[Suite]:
    """Aggregate pytest ``tests[]`` into per-file :class:`Suite` rows.

    A suite is ``fail`` if any of its tests failed/errored, ``skipped`` if all
    its tests were skipped, otherwise ``pass``. Durations are summed and
    rounded to whole seconds for deterministic output.
    """
    by_name: dict[str, dict] = {}
    order: list[str] = []
    for test in data.get("tests", []):
        nodeid = test.get("nodeid", "")
        name = _suite_name_from_nodeid(nodeid)
        if name not in by_name:
            by_name[name] = {"failed": 0, "skipped": 0, "passed": 0, "duration": 0.0}
            order.append(name)
        outcome = test.get("outcome", "")
        bucket = by_name[name]
        if outcome in ("failed", "error"):
            bucket["failed"] += 1
        elif outcome == "skipped":
            bucket["skipped"] += 1
        else:
            bucket["passed"] += 1
        bucket["duration"] += float(test.get("duration", 0.0) or 0.0)

    suites: list[Suite] = []
    for name in order:
        b = by_name[name]
        if b["failed"]:
            result = "fail"
        elif b["passed"] == 0 and b["skipped"]:
            result = "skipped"
        else:
            result = "pass"
        suites.append(Suite(name=name, result=result, duration_seconds=round(b["duration"])))
    return suites


def _result_from_suites(suites: list[Suite]) -> str:
    """Roll suite results up into a normalized run result."""
    if any(s.result == "fail" for s in suites):
        # A mix of pass and fail is partial; all-fail is fail.
        if any(s.result == "pass" for s in suites):
            return "partial"
        return "fail"
    return "pass"


def strict_mode_enabled(env: dict[str, str] | None = None) -> bool:
    """Return True when strict mode is requested via ``AASM_VERIFY_STRICT``.

    Truthy values are ``1``/``true``/``yes``/``on`` (case-insensitive). The
    env-var name is a contract shared with AAASM-3160's CI profiles.
    """
    source = os.environ if env is None else env
    value = source.get(skip_audit.STRICT_ENV_VAR, "")
    return value.strip().lower() in ("1", "true", "yes", "on")


def strict_skip_violations(summary: Summary) -> list[dict]:
    """Return the un-justified skips that fail a run under strict mode."""
    return [dict(s) for s in summary.unjustified_skips]


def _empty_area_buckets() -> dict[str, int]:
    return dict.fromkeys(AREA_COUNT_KEYS, 0)


def area_counts_from_pytest(data: dict) -> dict[str, dict[str, int]]:
    """Tally per-area test outcomes from a pytest-json-report mapping.

    Returns ``{area: {bucket: n}}`` over :data:`AREA_COUNT_KEYS`. Areas appear
    in first-seen order so output is deterministic. ``unexpected_skipped`` is
    the subset of ``skipped`` whose reason is not justified (no env requirement
    or Jira ref) — it is counted *in addition to* ``skipped``.
    """
    counts: dict[str, dict[str, int]] = {}
    for test in data.get("tests", []):
        area = skip_audit.area_for_test(test)
        bucket = counts.setdefault(area, _empty_area_buckets())
        outcome = test.get("outcome", "")
        if outcome in ("failed", "error"):
            bucket["failed"] += 1
        elif outcome == "skipped":
            bucket["skipped"] += 1
            if not skip_audit.is_justified(skip_audit.extract_skip_reason(test)):
                bucket["unexpected_skipped"] += 1
        elif outcome == "xfailed":
            bucket["xfailed"] += 1
        elif outcome == "xpassed":
            bucket["xpassed"] += 1
        else:
            bucket["passed"] += 1
    return counts


def _failed_tests_from_pytest(data: dict) -> list[str]:
    """Return the nodeids of failed/errored tests, in file order."""
    return [
        test.get("nodeid", "")
        for test in data.get("tests", [])
        if test.get("outcome") in ("failed", "error")
    ]


def summary_from_pytest_json(
    data: dict,
    *,
    run_type: str,
    date: str,
    workflow_run_url: str,
    tested_refs: list[str],
    retain: str,
    related_issue: str | None = None,
    scope: str = "",
    result: str | None = None,
) -> Summary:
    """Normalize a pytest-json-report mapping into a :class:`Summary`.

    ``result`` defaults to the rollup of the per-suite outcomes but may be
    overridden (e.g. when the caller already knows the aggregate verdict). The
    summary also carries per-area outcome counts and the list of un-justified
    skips for production-grade (AAASM-3155) reporting.
    """
    suites = _suites_from_pytest(data)
    verdict = result if result is not None else _result_from_suites(suites)
    return Summary(
        run_type=run_type,
        result=verdict,
        date=date,
        workflow_run_url=workflow_run_url,
        tested_refs=tested_refs,
        retain=retain,
        related_issue=related_issue,
        scope=scope,
        suites=suites,
        area_counts=area_counts_from_pytest(data),
        unjustified_skips=[s.as_dict() for s in skip_audit.find_unjustified_skips(data)],
        failed_tests=_failed_tests_from_pytest(data),
    )
