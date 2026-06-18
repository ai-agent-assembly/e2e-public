#!/usr/bin/env bash
# Assemble a QA evidence bundle from a production-validation run (AAASM-3162).
#
# Thin wrapper over `aasm-verify report --bundle`: it normalizes a pytest JSON
# report into summary.json + report.md and assembles a self-contained evidence
# folder (sanitized env, commands, CI links, screenshots) for QA review and
# Jira attachment. The bundle is identical for local and CI runs — only the
# inputs differ. No secrets are written: the env snapshot is allow-listed.
#
# Usage:
#   make-evidence-bundle.sh --pytest-json PATH --outdir DIR \
#                           [--run-url URL] [--run-type TYPE] \
#                           [--tested-refs REFS] [--screenshots DIR] [--strict]
#
# Defaults: --run-type scheduled, --tested-refs master. A reproduction command
# transcript is recorded automatically.
set -euo pipefail

PYTEST_JSON="${PYTEST_JSON:-}"
OUTDIR=""
RUN_URL="${GITHUB_SERVER_URL:-}"
RUN_TYPE="scheduled"
TESTED_REFS="master"
SCREENSHOTS=""
STRICT=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pytest-json)  PYTEST_JSON="$2"; shift 2 ;;
    --outdir)       OUTDIR="$2";      shift 2 ;;
    --run-url)      RUN_URL="$2";     shift 2 ;;
    --run-type)     RUN_TYPE="$2";    shift 2 ;;
    --tested-refs)  TESTED_REFS="$2"; shift 2 ;;
    --screenshots)  SCREENSHOTS="$2"; shift 2 ;;
    --strict)       STRICT=1;         shift   ;;
    *) echo "error: unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$PYTEST_JSON" ]] && { echo "error: --pytest-json is required" >&2; exit 1; }
[[ -z "$OUTDIR" ]] && { echo "error: --outdir is required" >&2; exit 1; }
[[ ! -f "$PYTEST_JSON" ]] && { echo "error: pytest json not found: $PYTEST_JSON" >&2; exit 1; }

mkdir -p "$OUTDIR"

# Run aasm-verify via `uv run` when available, else the installed console script.
if command -v uv >/dev/null 2>&1; then
  RUN=(uv run aasm-verify)
else
  RUN=(aasm-verify)
fi

ARGS=(
  report
  --pytest-json "$PYTEST_JSON"
  --summary "$OUTDIR/summary.json"
  --out "$OUTDIR/report.md"
  --run-type "$RUN_TYPE"
  --tested-refs "$TESTED_REFS"
  --bundle "$OUTDIR/bundle"
  --bundle-command "bash scripts/verify-public-stack.sh"
)
[[ -n "$RUN_URL" ]] && ARGS+=(--run-url "$RUN_URL")
[[ -n "$SCREENSHOTS" ]] && ARGS+=(--bundle-screenshots "$SCREENSHOTS")
[[ "$STRICT" -eq 1 ]] && ARGS+=(--strict)

"${RUN[@]}" "${ARGS[@]}"
echo "evidence bundle written to $OUTDIR/bundle" >&2
