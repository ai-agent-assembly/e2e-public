#!/usr/bin/env bash
# Smoke test: verify the agent-assembly conformance vector directory is present and non-empty.
#
# The conformance/ test suite in agent-assembly contains protocol vectors that SDK implementations
# must pass. This skeleton checks the vectors exist at the expected path so future tests can
# reference them by SHA or tag for pinned reproducibility.
#
# Environment variables:
#   AA_REF      Branch, tag, or SHA (default: master)
#   AA_WORK_DIR Working directory for the clone (default: a fresh `mktemp -d` dir)

set -euo pipefail

REPO_URL="https://github.com/ai-agent-assembly/agent-assembly.git"
REF="${AA_REF:-master}"
if [[ -n "${AA_WORK_DIR:-}" ]]; then
  WORK_DIR="$AA_WORK_DIR"
  rm -rf "$WORK_DIR"
else
  # No caller-supplied AA_WORK_DIR: mint a fresh, unpredictable dir instead of
  # a fixed /tmp path, so there is nothing for a symlink/race to target
  # (AAASM-4792/4812).
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aa-smoke-conformance.XXXXXX")"
fi

log()  { echo "[smoke-test-conformance] $*"; }
fail() { echo "[smoke-test-conformance] FAIL: $*" >&2; exit 1; }

log "Cloning agent-assembly @ $REF into $WORK_DIR (for conformance vectors)..."
git clone --depth 1 --branch "$REF" "$REPO_URL" "$WORK_DIR" 2>/dev/null \
  || { git clone "$REPO_URL" "$WORK_DIR"; git -C "$WORK_DIR" checkout "$REF"; }

VECTORS_DIR="${WORK_DIR}/conformance/vectors"
[[ -d "$VECTORS_DIR" ]] || fail "conformance/vectors directory missing"

vector_count=$(find "$VECTORS_DIR" -type f | wc -l)
[[ "$vector_count" -gt 0 ]] || fail "conformance/vectors is empty — no test vectors found"

log "PASS: conformance/vectors present with ${vector_count} vector file(s)"
