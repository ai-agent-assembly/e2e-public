#!/usr/bin/env bash
# Smoke test: verify the Agent Assembly Node SDK can be installed from source.
#
# Environment variables:
#   NODE_SDK_REF   Branch, tag, or SHA (default: master)
#   AA_WORK_DIR    Working directory (default: a fresh `mktemp -d` dir)

set -euo pipefail

REPO_URL="https://github.com/ai-agent-assembly/node-sdk.git"
REF="${NODE_SDK_REF:-master}"
if [[ -n "${AA_WORK_DIR:-}" ]]; then
  WORK_DIR="$AA_WORK_DIR"
  rm -rf "$WORK_DIR"
else
  # No caller-supplied AA_WORK_DIR: mint a fresh, unpredictable dir instead of
  # a fixed /tmp path, so there is nothing for a symlink/race to target
  # (AAASM-4792).
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aa-smoke-node-sdk.XXXXXX")"
fi

log()  { echo "[smoke-test-node-sdk] $*"; }
fail() { echo "[smoke-test-node-sdk] FAIL: $*" >&2; exit 1; }

require_cmd() {
  local required_cmd="$1"
  command -v "$required_cmd" &>/dev/null || { log "SKIP: $required_cmd not available"; exit 0; }
}

require_cmd node
require_cmd pnpm

log "Cloning node-sdk @ $REF into $WORK_DIR..."
git clone --depth 1 --branch "$REF" "$REPO_URL" "$WORK_DIR" 2>/dev/null \
  || { git clone "$REPO_URL" "$WORK_DIR"; git -C "$WORK_DIR" checkout "$REF"; }

log "Installing dependencies..."
pnpm --dir "$WORK_DIR" install --frozen-lockfile --silent \
  || fail "pnpm install failed"

log "Building..."
pnpm --dir "$WORK_DIR" build \
  || fail "pnpm build failed"

log "PASS: node-sdk built successfully"
