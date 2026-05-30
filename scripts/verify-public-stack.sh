#!/usr/bin/env bash
# verify-public-stack.sh — Verify the Agent Assembly public stack at specified refs.
#
# Usage:
#   bash scripts/verify-public-stack.sh [OPTIONS]
#
# Options:
#   --agent-assembly <ref>   Branch, tag, SHA, or version for agent-assembly (default: master)
#   --python-sdk <ref>       Branch, tag, SHA, or version for python-sdk (default: master)
#   --node-sdk <ref>         Branch, tag, SHA, or version for node-sdk (default: master)
#   --go-sdk <ref>           Branch, tag, SHA, or version for go-sdk (default: master)
#   --examples <ref>         Branch, tag, SHA, or version for agent-assembly-examples (default: master)
#   --mode <mode>            Verification mode: latest | tag | sha | release (default: latest)
#   -h, --help               Show this help message
#
# Examples:
#   # Verify latest base branches
#   bash scripts/verify-public-stack.sh
#
#   # Verify a specific tag across all repos
#   bash scripts/verify-public-stack.sh \
#     --agent-assembly v0.1.0 \
#     --python-sdk v0.1.0 \
#     --node-sdk v0.1.0 \
#     --go-sdk v0.1.0 \
#     --examples v0.1.0 \
#     --mode tag
#
#   # Verify published release packages
#   bash scripts/verify-public-stack.sh \
#     --python-sdk 0.1.0 \
#     --node-sdk 0.1.0 \
#     --mode release

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

AGENT_ASSEMBLY_REF="master"
PYTHON_SDK_REF="master"
NODE_SDK_REF="master"
GO_SDK_REF="master"
EXAMPLES_REF="master"
MODE="latest"

usage() {
  sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# //' | sed 's/^#//'
  exit 0
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --agent-assembly) AGENT_ASSEMBLY_REF="$2"; shift 2 ;;
      --python-sdk)     PYTHON_SDK_REF="$2";     shift 2 ;;
      --node-sdk)       NODE_SDK_REF="$2";        shift 2 ;;
      --go-sdk)         GO_SDK_REF="$2";          shift 2 ;;
      --examples)       EXAMPLES_REF="$2";        shift 2 ;;
      --mode)           MODE="$2";                shift 2 ;;
      -h|--help)        usage ;;
      *) echo "Unknown option: $1" >&2; usage ;;
    esac
  done
}

validate_mode() {
  case "$MODE" in
    latest|tag|sha|release) ;;
    *) echo "Error: unknown mode '$MODE'. Expected: latest | tag | sha | release" >&2; exit 1 ;;
  esac
}

log() { echo "[verify-public-stack] $*"; }

REGISTRY_REPOS=("python-sdk" "node-sdk" "go-sdk")

is_registry_repo() {
  local repo="$1"
  for r in "${REGISTRY_REPOS[@]}"; do [[ "$r" == "$repo" ]] && return 0; done
  return 1
}

run_install_step() {
  local repo="$1"
  local ref="$2"
  if [[ "$MODE" == "release" ]] && is_registry_repo "$repo"; then
    log "Installing $repo @ $ref from registry (mode=release)"
    bash "${SCRIPT_DIR}/install-from-release.sh" --repo "$repo" --version "$ref"
  else
    if [[ "$MODE" == "release" ]]; then
      log "Skipping registry install for $repo (not a published package) — cloning master instead"
      ref="master"
    fi
    log "Installing $repo @ $ref (mode=$MODE)"
    bash "${SCRIPT_DIR}/install-from-branch.sh" --repo "$repo" --ref "$ref"
  fi
}

run_smoke_tests() {
  log "Running smoke tests..."
  local exit_code=0
  for test_script in "${REPO_ROOT}/tests/install/"*.sh; do
    [[ -f "$test_script" ]] || continue
    log "  Running: $test_script"
    if ! bash "$test_script"; then
      log "  FAIL: $test_script"
      exit_code=1
    else
      log "  PASS: $test_script"
    fi
  done
  return $exit_code
}

main() {
  parse_args "$@"
  validate_mode

  log "Starting public stack verification"
  log "  mode:            $MODE"
  log "  agent-assembly:  $AGENT_ASSEMBLY_REF"
  log "  python-sdk:      $PYTHON_SDK_REF"
  log "  node-sdk:        $NODE_SDK_REF"
  log "  go-sdk:          $GO_SDK_REF"
  log "  examples:        $EXAMPLES_REF"

  run_install_step "agent-assembly"          "$AGENT_ASSEMBLY_REF"
  run_install_step "python-sdk"              "$PYTHON_SDK_REF"
  run_install_step "node-sdk"               "$NODE_SDK_REF"
  run_install_step "go-sdk"                 "$GO_SDK_REF"
  run_install_step "agent-assembly-examples" "$EXAMPLES_REF"

  run_smoke_tests

  log "Verification complete."
}

main "$@"
