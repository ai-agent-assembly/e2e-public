#!/usr/bin/env bash
# install-from-source.sh — Install a repo from a source ref (branch, tag, or SHA).
#
# Compatibility wrapper for install-from-branch.sh.
# All args are passed through unchanged.
#
# Usage:
#   bash scripts/install-from-source.sh --repo agent-assembly --ref main
#   bash scripts/install-from-source.sh --repo python-sdk --ref v0.0.1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

exec bash "${SCRIPT_DIR}/install-from-branch.sh" "$@"
