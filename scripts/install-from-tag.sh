#!/usr/bin/env bash
# install-from-tag.sh — Clone an Agent Assembly repo at a specific git tag for exact reproducibility.
#
# Usage:
#   bash scripts/install-from-tag.sh --repo <repo> --tag <tag> [OPTIONS]
#
# Options:
#   --repo <repo>      Repository name: agent-assembly | python-sdk | node-sdk | go-sdk |
#                      agent-assembly-examples (required)
#   --tag <tag>        Git tag to checkout, e.g. v0.1.0 (required)
#   --org <org>        GitHub organization (default: ai-agent-assembly)
#   --dest <dir>       Destination directory (default: /tmp/aa-install/<repo>-<tag>)
#   -h, --help         Show this help message
#
# Examples:
#   bash scripts/install-from-tag.sh --repo agent-assembly --tag v0.1.0
#   bash scripts/install-from-tag.sh --repo python-sdk --tag v0.1.0 --dest /tmp/my-test-dir

set -euo pipefail

REPO=""
TAG=""
ORG="ai-agent-assembly"
DEST=""

usage() {
  sed -n '/^# Usage:/,/^$/p' "$0" | sed 's/^# //' | sed 's/^#//'
  exit 0
}

parse_args() {
  while [[ $# -gt 0 ]]; do
    case "$1" in
      --repo) REPO="$2"; shift 2 ;;
      --tag)  TAG="$2";  shift 2 ;;
      --org)  ORG="$2";  shift 2 ;;
      --dest) DEST="$2"; shift 2 ;;
      -h|--help) usage ;;
      *) echo "Unknown option: $1" >&2; usage ;;
    esac
  done
}

validate_args() {
  [[ -n "$REPO" ]] || { echo "Error: --repo is required" >&2; exit 1; }
  [[ -n "$TAG"  ]] || { echo "Error: --tag is required"  >&2; exit 1; }
}

log() { echo "[install-from-tag] $*"; }

verify_tag_exists() {
  local clone_url="$1"
  local tag="$2"
  log "Verifying tag $tag exists on remote..."
  git ls-remote --tags "$clone_url" "refs/tags/${tag}" | grep -q "$tag" \
    || { echo "Error: tag '$tag' not found on $clone_url" >&2; exit 1; }
}

main() {
  parse_args "$@"
  validate_args

  local clone_url="https://github.com/${ORG}/${REPO}.git"
  local tag_slug="${TAG//\//-}"
  local dest="${DEST:-/tmp/aa-install/${REPO}-${tag_slug}}"

  verify_tag_exists "$clone_url" "$TAG"

  log "Cloning $clone_url @ tag $TAG → $dest"
  rm -rf "$dest"
  git clone --depth 1 --branch "$TAG" "$clone_url" "$dest"

  log "Cloned successfully: $dest"
  log "Commit: $(git -C "$dest" rev-parse HEAD)"
  log "Tag:    $TAG"
}

main "$@"
