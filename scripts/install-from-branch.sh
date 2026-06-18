#!/usr/bin/env bash
# install-from-branch.sh — Clone an Agent Assembly repo at a named branch, tag, or SHA.
#
# Usage:
#   bash scripts/install-from-branch.sh --repo <repo> --ref <ref> [OPTIONS]
#
# Options:
#   --repo <repo>      Repository name: agent-assembly | python-sdk | node-sdk | go-sdk |
#                      agent-assembly-examples (required)
#   --ref <ref>        Branch name, git tag, or commit SHA (required)
#   --org <org>        GitHub organization (default: ai-agent-assembly)
#   --dest <dir>       Destination directory (default: /tmp/aa-install/<repo>)
#   -h, --help         Show this help message
#
# Examples:
#   bash scripts/install-from-branch.sh --repo agent-assembly --ref master
#   bash scripts/install-from-branch.sh --repo python-sdk --ref feat/my-feature
#   bash scripts/install-from-branch.sh --repo go-sdk --ref v0.1.0

set -euo pipefail

REPO=""
REF=""
ORG="ai-agent-assembly"
DEST=""

usage() {
  sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# //' | sed 's/^#//'
  exit 0
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    local opt="$1"
    case "$opt" in
      --repo) REPO="$2"; shift 2 ;;
      --ref)  REF="$2";  shift 2 ;;
      --org)  ORG="$2";  shift 2 ;;
      --dest) DEST="$2"; shift 2 ;;
      -h|--help) usage ;;
      *) echo "Unknown option: $opt" >&2; usage ;;
    esac
  done
}

validate_args() {
  [[ -n "$REPO" ]] || { echo "Error: --repo is required" >&2; exit 1; }
  [[ -n "$REF"  ]] || { echo "Error: --ref is required"  >&2; exit 1; }
}

log() { echo "[install-from-branch] $*"; }

main() {
  parse_args "$@"
  validate_args

  local clone_url="https://github.com/${ORG}/${REPO}.git"
  local dest="${DEST:-/tmp/aa-install/${REPO}}"

  log "Cloning $clone_url @ $REF → $dest"

  rm -rf "$dest"
  git clone --depth 1 --branch "$REF" "$clone_url" "$dest" 2>/dev/null \
    || git clone "$clone_url" "$dest" && git -C "$dest" checkout "$REF"

  log "Cloned successfully: $dest"
  log "Commit: $(git -C "$dest" rev-parse HEAD)"
}

main "$@"
