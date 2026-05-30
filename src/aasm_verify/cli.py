"""CLI entry point for aasm-verify."""

from __future__ import annotations

import argparse

from aasm_verify.refs import ResolvedRefs


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
        "--dry-run",
        action="store_true",
        help="Print planned actions and exit without cloning/installing.",
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
