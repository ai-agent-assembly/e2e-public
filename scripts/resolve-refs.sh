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

cd "${REPO_ROOT}"

exec uv run aasm-verify public --dry-run "$@"
