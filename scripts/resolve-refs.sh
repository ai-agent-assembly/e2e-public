#!/usr/bin/env bash
# resolve-refs.sh — Print the resolved verification target matrix without executing.
#
# Delegates to `aasm-verify public --dry-run`. All args are passed through.
#
# Usage:
#   bash scripts/resolve-refs.sh --mode latest
#   bash scripts/resolve-refs.sh --mode tag --agent-assembly-ref v0.0.1
#   bash scripts/resolve-refs.sh --mode release --version 0.0.1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Public-stack verification CLI entrypoint. Generated from
# metadata/harness.yaml via scripts/generate_harness_metadata.py — do
# not edit by hand.
# BEGIN GENERATED: harness-verify-command
VERIFY_BIN="aasm-verify"
VERIFY_SUBCOMMAND="public"
# END GENERATED: harness-verify-command

cd "${REPO_ROOT}"

exec uv run "${VERIFY_BIN}" "${VERIFY_SUBCOMMAND}" --dry-run "$@"
