<!-- Copy this file to `verification-reports/releases/<version>/<repo>-<version>-qa.md` and fill it in. -->

# Release QA Report: `<repo>` `<version>`

**Repo:** `<owner>/<repo>` (e.g. `ai-agent-assembly/agent-assembly-integration-tests`)
**Release version:** `<version>` (e.g. `v0.0.1-beta.4`)
**Exact git SHA:** `<full-or-short-sha>` (the commit the release tag points at)
**Date:** `<YYYY-MM-DD>`
**QA owner:** `<name / handle>`

### Environment

| Item | Value |
|---|---|
| OS | `<e.g. ubuntu-24.04 / macOS 15.4 / Linux x86_64>` |
| Runtime versions | `<e.g. Python 3.12.x, Node 22.x, Go 1.23.x, Rust 1.78>` |
| Tool versions | `<e.g. uv 0.5.x, pnpm 9.x, cargo-nextest 0.9.x>` |
| Release tag tested | `<version>` |
| Base tested | release tag / base-branch HEAD — `<which>` |

---

## Scope & method

Which product areas were verified for this release, and how each was exercised.

| Area | In scope? | Method |
|---|---|---|
| runtime | `<yes/no>` | `<how — e.g. live aa-runtime over UDS, mock server, etc.>` |
| sdk | `<yes/no>` | `<how — install-matrix, import/exports, native addon load>` |
| conformance | `<yes/no>` | `<how — bypass suite, fail-closed checks>` |
| docs | `<yes/no>` | `<how — correctness / readability review; see Docs verification>` |
| examples | `<yes/no>` | `<how — example smoke runs>` |
| CI | `<yes/no>` | `<how — verify-run profiles green>` |

**Notes on method:** `<free text — e.g. offline-first skip guards, env gates, what was NOT covered and why>`

---

## Results matrix

| Area | Result (pass/fail/skip) | Evidence (CI run URL, test counts) | Notes / known issues |
|---|---|---|---|
| runtime | `<pass/fail/skip>` | `<CI run URL — N passed / M skipped>` | `<...>` |
| sdk | `<pass/fail/skip>` | `<CI run URL — N passed / M skipped>` | `<...>` |
| conformance | `<pass/fail/skip>` | `<CI run URL — N passed / M skipped>` | `<...>` |
| docs | `<pass/fail/skip>` | `<see Docs verification section>` | `<...>` |
| examples | `<pass/fail/skip>` | `<CI run URL — N passed / M skipped>` | `<...>` |
| CI | `<pass/fail/skip>` | `<verify-run URL + conclusion>` | `<...>` |

---

## Docs verification

Per AAASM-3547, release docs are verified on three axes:

| Axis | Result (pass/fail) | Evidence / notes |
|---|---|---|
| Correctness | `<pass/fail>` | `<install commands, version pins, and code samples match the released artifacts>` |
| Human-readability | `<pass/fail>` | `<structure, navigation, clarity — a human can follow the docs end to end>` |
| LLM-readability | `<pass/fail>` | `<machine-parseable structure: clean headings, fenced code, stable links, no ambiguous prose>` |

**Docs notes:** `<free text — broken links, stale version strings, missing sections, etc.>`

---

## Defects found

| Jira key | Severity | Summary | Status |
|---|---|---|---|
| `<AAASM-XXXX>` | `<blocker/critical/major/minor>` | `<one-line summary>` | `<open/fixed/won't-fix/deferred>` |

> If no defects were found, state "None" explicitly here.

---

## CI evidence

Per-profile verify-run URLs and their conclusions.

| Profile | Verify-run URL | Conclusion |
|---|---|---|
| `<e.g. offline-public>` | `<https://github.com/.../actions/runs/NNN>` | `<success/failure>` |
| `<e.g. live-gateway>` | `<https://github.com/.../actions/runs/NNN>` | `<success/failure>` |
| `<e.g. install-matrix>` | `<https://github.com/.../actions/runs/NNN>` | `<success/failure>` |

---

## Sign-off

**Release-ready:** `<yes / no>`

**Caveats:** `<free text — release-gated xfails, deferred items with tracking tickets, environment-specific gaps. State "None" if clean.>`

Signed off by: `<name / handle>` — `<YYYY-MM-DD>`

---

## Reproducibility

Exact commands to re-run this verification from a clean checkout.

```bash
# 1. Clone at the exact release SHA
git clone https://github.com/<owner>/<repo>.git
cd <repo>
git checkout <full-or-short-sha>   # or: git checkout <version>

# 2. Set the release version under test
export AASM_RELEASE_VERSION=<version-without-leading-v>

# 3. Install and run the verification profiles
<install command, e.g. uv sync --frozen>
<verify command(s), e.g. uv run pytest tests/public -v>
<verify command(s), e.g. uv run pytest tests/live -v>
```
