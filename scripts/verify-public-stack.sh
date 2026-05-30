#!/usr/bin/env bash
# verify-public-stack.sh — Thin wrapper around `aasm-verify public`.
#
# All argument parsing and validation is handled by the Python CLI.
# This script exists for developer convenience and CI entrypoints.
#
# Usage:
#   bash scripts/verify-public-stack.sh --mode latest [--dry-run]
#   bash scripts/verify-public-stack.sh --mode tag \
#     --agent-assembly-ref v0.0.1 --python-sdk-ref v0.0.1
#   bash scripts/verify-public-stack.sh --mode release --version 0.0.1
#
# Full option reference:
#   uv run aasm-verify public --help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPO_ROOT}"

exec uv run aasm-verify public "$@"
