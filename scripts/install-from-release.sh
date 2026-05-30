#!/usr/bin/env bash
# install-from-release.sh — Install Agent Assembly SDK packages from public registries.
#
# Verifies the user-facing install path: what a developer actually runs to get the SDK.
#
# Usage:
#   bash scripts/install-from-release.sh [OPTIONS]
#
# Options:
#   --python-sdk <version>   PyPI version to install, e.g. 0.1.0 (optional)
#   --node-sdk <version>     npm version to install, e.g. 0.1.0 (optional)
#   --go-sdk <version>       Go module version, e.g. v0.1.0 (optional)
#   --repo <name>            Single repo mode: python-sdk | node-sdk | go-sdk
#   --version <version>      Version for single-repo mode (used with --repo)
#   --tmpdir <dir>           Working directory (default: /tmp/aa-release-test)
#   -h, --help               Show this help message
#
# Examples:
#   # Install all SDKs at version 0.1.0
#   bash scripts/install-from-release.sh \
#     --python-sdk 0.1.0 \
#     --node-sdk 0.1.0 \
#     --go-sdk v0.1.0
#
#   # Single SDK (called by verify-public-stack.sh in release mode)
#   bash scripts/install-from-release.sh --repo python-sdk --version 0.1.0

set -euo pipefail

PYTHON_SDK_VERSION=""
NODE_SDK_VERSION=""
GO_SDK_VERSION=""
SINGLE_REPO=""
SINGLE_VERSION=""
TMPDIR_ROOT="/tmp/aa-release-test"

usage() {
  sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# //' | sed 's/^#//'
  exit 0
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --python-sdk) PYTHON_SDK_VERSION="$2"; shift 2 ;;
      --node-sdk)   NODE_SDK_VERSION="$2";   shift 2 ;;
      --go-sdk)     GO_SDK_VERSION="$2";     shift 2 ;;
      --repo)       SINGLE_REPO="$2";        shift 2 ;;
      --version)    SINGLE_VERSION="$2";     shift 2 ;;
      --tmpdir)     TMPDIR_ROOT="$2";        shift 2 ;;
      -h|--help)    usage ;;
      *) echo "Unknown option: $1" >&2; usage ;;
    esac
  done

  if [[ -n "$SINGLE_REPO" ]]; then
    [[ -n "$SINGLE_VERSION" ]] || { echo "Error: --version required with --repo" >&2; exit 1; }
    case "$SINGLE_REPO" in
      python-sdk) PYTHON_SDK_VERSION="$SINGLE_VERSION" ;;
      node-sdk)   NODE_SDK_VERSION="$SINGLE_VERSION"   ;;
      go-sdk)     GO_SDK_VERSION="$SINGLE_VERSION"     ;;
      *) echo "Error: unknown repo '$SINGLE_REPO'" >&2; exit 1 ;;
    esac
  fi
}

log() { echo "[install-from-release] $*"; }

install_python_sdk() {
  local version="$1"
  local venv_dir="${TMPDIR_ROOT}/python-sdk-${version}"
  log "Installing agent-assembly-sdk==${version} from PyPI..."
  python3 -m venv "$venv_dir"
  "${venv_dir}/bin/pip" install --quiet "agent-assembly-sdk==${version}"
  log "Python SDK installed: $("${venv_dir}/bin/pip" show agent-assembly-sdk | grep Version)"
}

install_node_sdk() {
  local version="$1"
  local work_dir="${TMPDIR_ROOT}/node-sdk-${version}"
  log "Installing @agent-assembly/sdk@${version} from npm..."
  mkdir -p "$work_dir"
  cd "$work_dir"
  npm install --silent "@agent-assembly/sdk@${version}"
  log "Node SDK installed: $(node -e "console.log(require('./node_modules/@agent-assembly/sdk/package.json').version)")"
  cd -
}

install_go_sdk() {
  local version="$1"
  local work_dir="${TMPDIR_ROOT}/go-sdk-${version}"
  log "Installing github.com/agent-assembly/go-sdk@${version}..."
  mkdir -p "$work_dir"
  cd "$work_dir"
  go mod init aa-release-test
  go get "github.com/agent-assembly/go-sdk@${version}"
  log "Go SDK installed: $version"
  cd -
}

main() {
  parse_args "$@"

  mkdir -p "$TMPDIR_ROOT"

  [[ -n "$PYTHON_SDK_VERSION" ]] && install_python_sdk "$PYTHON_SDK_VERSION"
  [[ -n "$NODE_SDK_VERSION"   ]] && install_node_sdk   "$NODE_SDK_VERSION"
  [[ -n "$GO_SDK_VERSION"     ]] && install_go_sdk     "$GO_SDK_VERSION"

  if [[ -z "$PYTHON_SDK_VERSION" && -z "$NODE_SDK_VERSION" && -z "$GO_SDK_VERSION" ]]; then
    echo "Error: specify at least one of --python-sdk, --node-sdk, --go-sdk (or use --repo/--version)" >&2
    exit 1
  fi

  log "Release install verification complete."
}

main "$@"
