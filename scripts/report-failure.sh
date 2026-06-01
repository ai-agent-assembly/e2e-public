#!/usr/bin/env bash
# Reads summary.json (produced by summarize-run.sh) and creates or updates a
# GitHub Issue for the failing test area.
#
# Behaviour:
#   status: pass    -> no issue created (silent exit 0)
#   status: failure -> create or update open/closed issue for the area
#   status: unknown -> create issue (cannot confirm pass)
#
# One issue per area, not one per run:
#   - Open issue with matching labels  -> add a comment
#   - Closed issue with matching labels -> reopen + add a comment
#   - No issue                          -> create a new issue
#
# Usage:
#   report-failure.sh --summary PATH [--repo OWNER/REPO] [--dry-run]
#
# Environment:
#   GITHUB_TOKEN       required for gh CLI calls
#   GITHUB_REPOSITORY  used as default --repo value
set -euo pipefail

SUMMARY_PATH=""
REPO="${GITHUB_REPOSITORY:-}"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --summary)  SUMMARY_PATH="$2"; shift 2 ;;
    --repo)     REPO="$2";         shift 2 ;;
    --dry-run)  DRY_RUN=1;         shift   ;;
    *) echo "error: unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$SUMMARY_PATH" ]] && { echo "error: --summary is required" >&2; exit 1; }
[[ ! -f "$SUMMARY_PATH" ]] && { echo "error: summary file not found: $SUMMARY_PATH" >&2; exit 1; }
[[ -z "$REPO" ]] && { echo "error: --repo or GITHUB_REPOSITORY must be set" >&2; exit 1; }

# Parse the summary fields from JSON using Python stdlib
eval "$(python3 - "$SUMMARY_PATH" <<'PYEOF'
import json, sys
with open(sys.argv[1]) as fh:
    d = json.load(fh)
def q(s):
    return "'" + str(s).replace("'", "'\"'\"'") + "'"
print(f"AREA={q(d.get('area', ''))}")
print(f"MODE={q(d.get('mode', 'latest'))}")
print(f"RUN_URL={q(d.get('run_url', ''))}")
print(f"STATUS={q(d.get('status', 'unknown'))}")
print(f"SHORT_SUMMARY={q(d.get('short_summary', ''))}")
PYEOF
)"

if [[ "$STATUS" == "pass" ]]; then
  echo "All tests passed in area: $AREA — no issue created."
  exit 0
fi

AREA_LABEL="area: ${AREA}"
ISSUE_TITLE="[test-failure] Scheduled verification failed: ${AREA}"

ISSUE_BODY="## Scheduled verification failure

**Area:** \`${AREA}\`
**Mode:** \`${MODE}\`
**Status:** \`${STATUS}\`
**Summary:** ${SHORT_SUMMARY}

**Run:** ${RUN_URL:-_run URL not available_}

---

This issue was created automatically by \`report-failure.sh\`.
To investigate, visit the run URL above and review the \`${AREA}\` matrix job."

COMMENT_BODY="### Failure recurrence

**Area:** \`${AREA}\`
**Mode:** \`${MODE}\`
**Status:** \`${STATUS}\`
**Summary:** ${SHORT_SUMMARY}

**Run:** ${RUN_URL:-_run URL not available_}"

if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "[dry-run] Repo:   $REPO"
  echo "[dry-run] Area:   $AREA  Status: $STATUS"
  echo "[dry-run] Would search for open/closed issue with labels: test-failure, $AREA_LABEL"
  echo "[dry-run] Would create or comment on: $ISSUE_TITLE"
  exit 0
fi

# Search for an existing open issue with the area label
OPEN_NUMBER=$(gh issue list \
  --repo "$REPO" \
  --label "test-failure" \
  --label "$AREA_LABEL" \
  --state open \
  --json number \
  --jq '.[0].number // empty' 2>/dev/null || true)

if [[ -n "$OPEN_NUMBER" ]]; then
  echo "Open issue #${OPEN_NUMBER} found — appending comment."
  gh issue comment "$OPEN_NUMBER" --repo "$REPO" --body "$COMMENT_BODY"
  exit 0
fi

# Search for a closed issue to reopen
CLOSED_NUMBER=$(gh issue list \
  --repo "$REPO" \
  --label "test-failure" \
  --label "$AREA_LABEL" \
  --state closed \
  --json number \
  --jq '.[0].number // empty' 2>/dev/null || true)

if [[ -n "$CLOSED_NUMBER" ]]; then
  echo "Closed issue #${CLOSED_NUMBER} found — reopening and adding comment."
  gh issue reopen "$CLOSED_NUMBER" --repo "$REPO"
  gh issue comment "$CLOSED_NUMBER" --repo "$REPO" --body "### Regression — issue reopened

${COMMENT_BODY}"
  exit 0
fi

# No existing issue — create a new one
echo "No existing issue for area: $AREA — creating new issue."
gh issue create \
  --repo "$REPO" \
  --title "$ISSUE_TITLE" \
  --body "$ISSUE_BODY" \
  --label "test-failure" \
  --label "scheduled-run" \
  --label "needs-triage" \
  --label "$AREA_LABEL"
