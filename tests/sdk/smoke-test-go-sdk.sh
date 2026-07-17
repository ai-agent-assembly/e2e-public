#!/usr/bin/env bash
# Smoke test: verify the Agent Assembly Go SDK can be built from source.
#
# Environment variables:
#   GO_SDK_REF   Branch, tag, or SHA (default: master)
#   AA_WORK_DIR  Working directory (default: a fresh `mktemp -d` dir)

set -euo pipefail

REPO_URL="https://github.com/ai-agent-assembly/go-sdk.git"
REF="${GO_SDK_REF:-master}"
if [[ -n "${AA_WORK_DIR:-}" ]]; then
  WORK_DIR="$AA_WORK_DIR"
  rm -rf "$WORK_DIR"
else
  # No caller-supplied AA_WORK_DIR: mint a fresh, unpredictable dir instead of
  # a fixed /tmp path, so there is nothing for a symlink/race to target
  # (AAASM-4792).
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aa-smoke-go-sdk.XXXXXX")"
fi

log()  { echo "[smoke-test-go-sdk] $*"; }
fail() { echo "[smoke-test-go-sdk] FAIL: $*" >&2; exit 1; }

require_cmd() {
  local cmd="$1"
  command -v "$cmd" &>/dev/null || { log "SKIP: $cmd not available"; exit 0; }
}

require_cmd go
require_cmd git

log "Cloning go-sdk @ $REF into $WORK_DIR..."
git clone --depth 1 --branch "$REF" "$REPO_URL" "$WORK_DIR" 2>/dev/null \
  || { git clone "$REPO_URL" "$WORK_DIR"; git -C "$WORK_DIR" checkout "$REF"; }

log "Downloading modules..."
( cd "$WORK_DIR" && go mod download ) \
  || fail "go mod download failed"

log "Building..."
( cd "$WORK_DIR" && go build ./... ) \
  || fail "go build failed"

log "PASS: go-sdk built successfully"
