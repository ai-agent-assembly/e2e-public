#!/usr/bin/env bash
# Smoke test: verify the Agent Assembly Python SDK can be installed from source.
#
# Environment variables:
#   PYTHON_SDK_REF   Branch, tag, or SHA (default: master)
#   AA_WORK_DIR      Working directory (default: /tmp/aa-smoke-python-sdk)

set -euo pipefail

REPO_URL="https://github.com/ai-agent-assembly/python-sdk.git"
REF="${PYTHON_SDK_REF:-master}"
WORK_DIR="${AA_WORK_DIR:-/tmp/aa-smoke-python-sdk}"
VENV_DIR="${WORK_DIR}/.venv"

log()  { echo "[smoke-test-python-sdk] $*"; }
fail() { echo "[smoke-test-python-sdk] FAIL: $*" >&2; exit 1; }

require_cmd() {
  command -v "$1" &>/dev/null || { log "SKIP: $1 not available"; exit 0; }
}

require_cmd python3
require_cmd pip3

log "Cloning python-sdk @ $REF..."
rm -rf "$WORK_DIR"
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
