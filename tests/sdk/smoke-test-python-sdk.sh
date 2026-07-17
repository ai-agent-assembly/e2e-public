#!/usr/bin/env bash
# Smoke test: verify the Agent Assembly Python SDK can be installed from source.
#
# Environment variables:
#   PYTHON_SDK_REF   Branch, tag, or SHA (default: master)
#   AA_WORK_DIR      Working directory (default: a fresh `mktemp -d` dir)

set -euo pipefail

REPO_URL="https://github.com/ai-agent-assembly/python-sdk.git"
REF="${PYTHON_SDK_REF:-master}"
if [[ -n "${AA_WORK_DIR:-}" ]]; then
  WORK_DIR="$AA_WORK_DIR"
  rm -rf "$WORK_DIR"
else
  # No caller-supplied AA_WORK_DIR: mint a fresh, unpredictable dir instead of
  # a fixed /tmp path, so there is nothing for a symlink/race to target
  # (AAASM-4792).
  WORK_DIR="$(mktemp -d "${TMPDIR:-/tmp}/aa-smoke-python-sdk.XXXXXX")"
fi
VENV_DIR="${WORK_DIR}/.venv"

log()  { echo "[smoke-test-python-sdk] $*"; }
fail() { echo "[smoke-test-python-sdk] FAIL: $*" >&2; exit 1; }

require_cmd() {
  local required_cmd="$1"
  command -v "$required_cmd" &>/dev/null || { log "SKIP: $required_cmd not available"; exit 0; }
}

require_cmd python3
require_cmd pip3

log "Cloning python-sdk @ $REF into $WORK_DIR..."
git clone --depth 1 --branch "$REF" "$REPO_URL" "$WORK_DIR" 2>/dev/null \
  || { git clone "$REPO_URL" "$WORK_DIR"; git -C "$WORK_DIR" checkout "$REF"; }

log "Creating virtual environment..."
python3 -m venv "$VENV_DIR"

log "Installing SDK..."
"${VENV_DIR}/bin/pip" install --quiet "${WORK_DIR}" \
  || fail "pip install failed"

log "Verifying import..."
"${VENV_DIR}/bin/python" -c "import agent_assembly; print('import OK')" \
  || fail "import agent_assembly failed"

log "PASS: python-sdk installed and importable"
