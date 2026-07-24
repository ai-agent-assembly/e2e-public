#!/usr/bin/env bash
# Smoke test: verify the examples repo clones and its README exists.
#
# Environment variables:
#   EXAMPLES_REF   Branch, tag, or SHA (default: main)
#   AA_WORK_DIR    Working directory (default: a fresh `mktemp -d` dir)

set -euo pipefail

REPO_URL="https://github.com/ai-agent-assembly/examples.git"
REF="${EXAMPLES_REF:-main}"
if [[ -n "${AA_WORK_DIR:-}" ]]; then
  WORK_DIR="$AA_WORK_DIR"
  rm -rf "$WORK_DIR"
else
  # No caller-supplied AA_WORK_DIR: mint a fresh, unpredictable dir instead of
  # a fixed /tmp path, so there is nothing for a symlink/race to target
  # (AAASM-4792/4812).
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aa-smoke-examples.XXXXXX")"
fi

log()  { echo "[smoke-test-examples] $*"; }
fail() { echo "[smoke-test-examples] FAIL: $*" >&2; exit 1; }

log "Cloning examples @ $REF into $WORK_DIR..."
git clone --depth 1 --branch "$REF" "$REPO_URL" "$WORK_DIR" 2>/dev/null \
  || { git clone "$REPO_URL" "$WORK_DIR"; git -C "$WORK_DIR" checkout "$REF"; }

[[ -f "${WORK_DIR}/README.md" ]] || fail "README.md missing in examples repo"

log "Verifying at least one example directory exists..."
example_count=$(find "$WORK_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l)
[[ "$example_count" -gt 0 ]] || fail "No example directories found in repo"

log "PASS: examples repo cloned, README found, ${example_count} example(s) present"
