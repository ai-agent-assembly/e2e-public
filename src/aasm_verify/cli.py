"""CLI entry point for aasm-verify."""

from __future__ import annotations

import argparse
import json
import os
import sys

from aasm_verify import doctor, reports, runners
from aasm_verify.pathsafe import PathTraversalError, safe_path
from aasm_verify.refs import ResolvedRefs, resolve_refs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aasm-verify",
        description="Public integration verification CLI for Agent Assembly.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    public = sub.add_parser(
        "public",
        help="Verify the public Agent Assembly stack at specified refs.",
    )
    public.add_argument(
        "--mode",
        choices=["latest", "tag", "sha", "release"],
        default="latest",
        help="Verification mode (default: latest)",
    )
    public.add_argument("--agent-assembly-ref", default=None, metavar="REF")
    public.add_argument("--python-sdk-ref", default=None, metavar="REF")
    public.add_argument("--node-sdk-ref", default=None, metavar="REF")
    public.add_argument("--go-sdk-ref", default=None, metavar="REF")
    public.add_argument("--examples-ref", default=None, metavar="REF")
    public.add_argument(
        "--version",
        default=None,
        metavar="VERSION",
        help="Package version for release mode (e.g. 0.0.1)",
    )
    public.add_argument(
        "--area",
        default=os.environ.get("AREA", "all"),
        choices=["all", *runners.AREAS],
        help="Verification area to run (default: $AREA or 'all')",
    )
    public.add_argument(
        "--json-report",
        default=os.environ.get("PYTEST_JSON"),
        metavar="PATH",
        help="Write the pytest JSON report here (default: $PYTEST_JSON). "
        "Consumed by scripts/summarize-run.sh on failure.",
    )
    public.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions and exit without cloning/installing.",
    )

    report = sub.add_parser(
        "report",
        help="Generate summary.json + report.md for a public-integration run.",
    )
    report.add_argument(
        "--summary",
        required=True,
        metavar="PATH",
        help="Path to summary.json. Written when --pytest-json is given; "
        "otherwise read as the input for report.md.",
    )
    report.add_argument(
        "--out",
        required=True,
        metavar="PATH",
        help="Path to write the rendered report.md.",
    )
    report.add_argument(
        "--pytest-json",
        default=None,
        metavar="PATH",
        help="Pytest --json-report output to normalize into summary.json. "
        "When omitted, --summary must already exist and is rendered as-is.",
    )
    report.add_argument(
        "--run-type",
        choices=list(reports.RUN_TYPES),
        default="scheduled",
        help="What triggered the run (default: scheduled).",
    )
    report.add_argument(
        "--result",
        choices=list(reports.RESULTS),
        default=None,
        help="Override the normalized result (default: derived from suites).",
    )
    report.add_argument(
        "--retain",
        choices=list(reports.RETAINS),
        default="short-term",
        help="Retention class (default: short-term).",
    )
    report.add_argument("--date", default=None, metavar="YYYY-MM-DD")
    report.add_argument("--run-url", default="", metavar="URL")
    report.add_argument(
        "--tested-refs",
        default="",
        metavar="REFS",
        help="Comma-separated source/version refs under test.",
    )
    report.add_argument("--related-issue", default=None, metavar="ISSUE")
    report.add_argument("--scope", default="", metavar="TEXT")
    report.add_argument(
        "--jira",
        default=None,
        metavar="PATH",
        help="Also write a Jira-ready evidence report (markdown) to this path.",
    )
    report.add_argument(
        "--strict",
        action="store_true",
        help="Fail the run on un-justified skips. Also enabled by "
        "AASM_VERIFY_STRICT=1 (contract shared with AAASM-3160 CI profiles).",
    )
    report.add_argument(
        "--bundle",
        default=None,
        metavar="OUTDIR",
        help="Also assemble a QA evidence bundle (summary, sanitized env, "
        "commands, CI links, screenshots) under OUTDIR (AAASM-3162).",
    )
    report.add_argument(
        "--bundle-command",
        action="append",
        default=None,
        metavar="CMD",
        dest="bundle_commands",
        help="Reproduction command to record in the bundle transcript "
        "(repeatable). Only used with --bundle.",
    )
    report.add_argument(
        "--bundle-screenshots",
        action="append",
        default=None,
        metavar="DIR",
        dest="bundle_screenshots",
        help="Directory to scan for browser-test screenshots to copy into the "
        "bundle (repeatable, best-effort). Only used with --bundle.",
    )

    doctor_cmd = sub.add_parser(
        "doctor",
        help="Preflight: check whether this machine can run each validation area.",
    )
    doctor_cmd.add_argument(
        "--json",
        action="store_true",
        help="Emit the machine-readable report as JSON (for a CI summary).",
    )
    return parser


def print_target_matrix(refs: ResolvedRefs) -> None:
    """Print a formatted table of resolved refs to stdout."""
    print("┌─ Verification Target Matrix ─────────────────────────────┐")
    print(f"│  mode:              {refs.mode:<38}│")
    print(f"│  agent-assembly:    {refs.agent_assembly:<38}│")
    print(f"│  python-sdk:        {refs.python_sdk:<38}│")
    print(f"│  node-sdk:          {refs.node_sdk:<38}│")
    print(f"│  go-sdk:            {refs.go_sdk:<38}│")
    print(f"│  examples:          {refs.examples:<38}│")
    print("└──────────────────────────────────────────────────────────┘")


def cmd_public(args: argparse.Namespace) -> int:
    """Run the 'public' subcommand."""
    try:
        refs = resolve_refs(
            args.mode,
            agent_assembly_ref=args.agent_assembly_ref,
            python_sdk_ref=args.python_sdk_ref,
            node_sdk_ref=args.node_sdk_ref,
            go_sdk_ref=args.go_sdk_ref,
            examples_ref=args.examples_ref,
            version=args.version,
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print_target_matrix(refs)

    if args.dry_run:
        print("\n[dry-run] No cloning or installing performed.")
        return 0

    try:
        areas = runners.resolve_areas(args.area)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"\nRunning verification for area(s): {', '.join(areas)}")
    return runners.run_areas(refs, areas, json_report=args.json_report)


def cmd_report(args: argparse.Namespace) -> int:
    """Run the 'report' subcommand: build summary.json and render report.md."""
    date = args.date or _today_utc()
    tested_refs = [r.strip() for r in args.tested_refs.split(",") if r.strip()]

    try:
        if args.pytest_json is not None:
            with open(safe_path(args.pytest_json), encoding="utf-8") as fh:
                pytest_data = json.load(fh)
            summary = reports.summary_from_pytest_json(
                pytest_data,
                run_type=args.run_type,
                date=date,
                workflow_run_url=args.run_url,
                tested_refs=tested_refs,
                retain=args.retain,
                related_issue=args.related_issue,
                scope=args.scope,
                result=args.result,
            )
            reports.write_summary_json(args.summary, summary)
        else:
            with open(safe_path(args.summary), encoding="utf-8") as fh:
                summary = reports.summary_from_dict(json.load(fh))
    except PathTraversalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except (ValueError, KeyError) as exc:
        print(f"error: invalid summary data: {exc}", file=sys.stderr)
        return 1

    try:
        reports.write_report_md(args.out, summary)
        print(f"summary: {args.summary}")
        print(f"report:  {args.out}")
        if args.jira is not None:
            reports.write_jira_report(args.jira, summary)
            print(f"jira:    {args.jira}")
    except PathTraversalError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    if args.bundle is not None:
        out = _write_bundle(args, summary)
        print(f"bundle:  {out}")

    # Strict mode (CLI flag or AASM_VERIFY_STRICT=1) fails on un-justified skips.
    if args.strict or reports.strict_mode_enabled():
        violations = reports.strict_skip_violations(summary)
        if violations:
            print(
                f"error: strict mode: {len(violations)} un-justified skip(s) "
                "(reason must name an env requirement or a Jira issue):",
                file=sys.stderr,
            )
            for v in violations:
                reason = v["reason"] or "<no reason given>"
                print(f"  - [{v['area']}] {v['nodeid']}: {reason}", file=sys.stderr)
            return 1

    return 0


def _write_bundle(args: argparse.Namespace, summary: reports.Summary) -> str:
    """Assemble the QA evidence bundle from the report args (AAASM-3162).

    Reuses the report's reproduction inputs (``--pytest-json``, ``--run-url``)
    and the bundle-only flags. Screenshot dirs are best-effort: absent ones are
    silently tolerated by the assembler.
    """
    from pathlib import Path

    from aasm_verify import bundle as bundle_mod

    ci_links = [args.run_url] if args.run_url else []
    evidence = bundle_mod.EvidenceBundle(
        summary=summary,
        commands=list(args.bundle_commands or []),
        ci_links=ci_links,
        pytest_json_path=Path(args.pytest_json) if args.pytest_json else None,
        screenshot_dirs=[Path(d) for d in (args.bundle_screenshots or [])],
    )
    return str(evidence.write(args.bundle))


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run the 'doctor' subcommand: preflight the environment by area.

    Exit code is ``1`` only when an area is FAIL (a required capability is
    missing); WARN is advisory and exits ``0``.
    """
    report = doctor.DoctorReport.build()
    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
    else:
        print(doctor.render_text(report))
    return doctor.exit_code(report)


def _today_utc() -> str:
    """Return today's UTC date as ISO-8601 ``YYYY-MM-DD``."""
    from datetime import UTC, datetime

    return datetime.now(UTC).strftime("%Y-%m-%d")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "public":
        sys.exit(cmd_public(args))
    if args.command == "report":
        sys.exit(cmd_report(args))
    if args.command == "doctor":
        sys.exit(cmd_doctor(args))


if __name__ == "__main__":
    main()
