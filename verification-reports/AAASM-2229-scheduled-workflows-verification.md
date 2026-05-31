# Verification Report: AAASM-2229

**Story:** Public tests: Add scheduled workflows and failure issue reporting  
**Verified by:** AAASM-2307  
**Date:** 2026-05-31  
**Repo:** https://github.com/ai-agent-assembly/agent-assembly-integration-tests  

---

## Acceptance Criteria Verification

### AC1: Manual workflow can run selected mode/test group

**Status: ✅ PASS**

`verify-public-manual.yml` is triggered exclusively by `workflow_dispatch` and accepts:

- `mode` — choice input: `latest` | `tag` | `release` (default: `latest`)
- `test_group` — choice input: `all` | `runtime` | `sdk` | `examples` | `install` | `conformance` (default: `all`)
- Per-repo ref inputs: `agent_assembly_ref`, `python_sdk_ref`, `node_sdk_ref`, `go_sdk_ref`, `examples_ref`

Matrix `if` condition filters correctly:
```yaml
if: ${{ inputs.test_group == 'all' || inputs.test_group == matrix.area }}
```

---

### AC2: Scheduled workflow runs on agreed low-cost cadence

**Status: ✅ PASS**

`verify-public-scheduled.yml` trigger:
```yaml
schedule:
  - cron: "0 2 1,15 * *"  # 1st and 15th of each month at 02:00 UTC
```
Also supports `workflow_dispatch` for ad-hoc runs.

---

### AC3: Workflows use `uv` and Python CLI as main entrypoint

**Status: ✅ PASS**

Both workflows:
1. Install uv: `pip install uv --quiet`
2. Install Python deps: `uv sync`
3. Call the CLI:
   - Manual: `uv run aasm-verify public --mode "$MODE" --agent-assembly-ref "$AA_REF" ...`
   - Scheduled: `uv run aasm-verify public --mode latest`

---

### AC4: Safe public areas run through GitHub Actions matrix

**Status: ✅ PASS**

Both workflows define:
```yaml
strategy:
  fail-fast: false
  matrix:
    area: [runtime, sdk, examples, install, conformance]
```

All 5 areas covered. `fail-fast: false` ensures all areas run even if one fails.

---

### AC5: Failures create or update GitHub Issues in the same repo

**Status: ✅ PASS**

Both workflows include:
```yaml
- name: Summarize run on failure
  if: failure()
  run: bash scripts/summarize-run.sh ...

- name: Report failure
  if: failure()
  env:
    GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
  run: bash scripts/report-failure.sh --summary /tmp/summary-"$AREA".json
```

`report-failure.sh` implements:
- Open issue → append comment
- Closed issue → reopen + add regression comment
- No issue → create new issue with labels

`permissions: issues: write` is set at workflow level.

---

### AC6: Failure issue includes run URL, test mode, refs, failed area, sanitized summary

**Status: ✅ PASS**

`summarize-run.sh` produces:
```json
{
  "area": "runtime",
  "mode": "latest",
  "run_url": "https://github.com/.../actions/runs/...",
  "passed": 3,
  "failed": 1,
  "status": "failure",
  "failed_tests": ["test_aasm_version"],
  "short_summary": "1 test(s) failed in area: runtime"
}
```

`report-failure.sh` ISSUE_BODY includes all required fields:
- `**Area:** \`${AREA}\``
- `**Mode:** \`${MODE}\``
- `**Status:** \`${STATUS}\``
- `**Summary:** ${SHORT_SUMMARY}`
- `**Run:** ${RUN_URL}`

No log dumps or private data in issue body.

---

### AC7: Successful scheduled runs do not create noise issues

**Status: ✅ PASS**

`report-failure.sh` early-exits with no issue creation when `status == "pass"`:
```bash
if [[ "$STATUS" == "pass" ]]; then
  echo "All tests passed in area: $AREA — no issue created."
  exit 0
fi
```

Additionally, the summarize/report steps only fire on `if: failure()`, so a successful job never runs them.

---

### AC8: README documents schedule, manual trigger, and failure issue policy

**Status: ✅ PASS**

`README.md` updated (AAASM-2305) with:
- Updated **CI** table including `verify-public-manual.yml` and `verify-public-scheduled.yml`
- New **Scheduled verification** section: cron cadence, ad-hoc dispatch steps, selective manual run with input table
- New **Failure issue policy** section: one-per-area rule, open/closed/new behavior, labels, issue body content, silence on success
- Updated repository layout listing all new scripts and workflows

---

## Summary

| Acceptance Criterion | Status |
|---|---|
| Manual workflow can run selected mode/test group | ✅ PASS |
| Scheduled workflow runs on agreed low-cost cadence | ✅ PASS |
| Workflows use `uv` and Python CLI as main entrypoint | ✅ PASS |
| Safe public areas run through GitHub Actions matrix | ✅ PASS |
| Failures create or update GitHub Issues | ✅ PASS |
| Issue body includes required fields | ✅ PASS |
| Successful runs do not create noise issues | ✅ PASS |
| README documents schedule, manual trigger, failure policy | ✅ PASS |

**All 8 acceptance criteria met. AAASM-2229 is ready for review.**

---

## Related PRs

| Sub-ticket | PR | Deliverable |
|---|---|---|
| AAASM-2292 | #14 | `scripts/summarize-run.sh` |
| AAASM-2294 | #17 | `scripts/report-failure.sh` |
| AAASM-2298 | #19 | `.github/workflows/verify-public-manual.yml` |
| AAASM-2303 | #21 | `.github/workflows/verify-public-scheduled.yml` |
| AAASM-2305 | #23 | README update |
| AAASM-2307 | this PR | Verification report |
