#!/usr/bin/env bash
# Smoke test: clone agent-assembly and verify it builds successfully.
#
# This test verifies the public install path for the core Rust monorepo.
# It clones the repo at the specified ref, runs `cargo check`, and reports pass/fail.
#
# Environment variables:
#   AA_REF      Branch, tag, or SHA to test (default: master)
#   AA_WORK_DIR Working directory for the clone (default: /tmp/aa-smoke-rust-build)

set -euo pipefail

REPO_URL="https://github.com/ai-agent-assembly/agent-assembly.git"
REF="${AA_REF:-master}"
WORK_DIR="${AA_WORK_DIR:-/tmp/aa-smoke-rust-build}"

log() { echo "[smoke-test-rust-build] $*"; }
fail() { echo "[smoke-test-rust-build] FAIL: $*" >&2; exit 1; }

log "Cloning agent-assembly @ $REF..."
rm -rf "$WORK_DIR"
git clone --depth 1 --branch "$REF" "$REPO_URL" "$WORK_DIR" 2>/dev/null \
  || { git clone "$REPO_URL" "$WORK_DIR"; git -C "$WORK_DIR" checkout "$REF"; }

log "Running cargo check..."
if ! command -v cargo &>/dev/null; then
  log "SKIP: cargo not available in PATH — marking as skipped (not failed)"
  log "Install Rust: https://rustup.rs"
  exit 0
fi
# aa-proto's build script needs protoc; without it cargo check fails. Skip (not
# fail) when protoc is absent so this smoke can run in toolchain-light jobs.
if ! command -v protoc &>/dev/null; then
  log "SKIP: protoc not available — skipping rust build (aa-proto build needs protoc)"
  log "Install protobuf-compiler to enable this check."
  exit 0
fi
cargo check --manifest-path "$WORK_DIR/Cargo.toml" --workspace \
  || fail "cargo check failed"
log "PASS: cargo check succeeded"
