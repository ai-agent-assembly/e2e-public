# agent-assembly-integration-tests

Public integration tests for verifying Agent Assembly runtime, SDKs, installers, release artifacts, and examples across branches, tags, and published versions.

## Purpose

This repository verifies **cross-repo behavior** that no single product repo can prove on its own. It covers:

- Runtime × SDK compatibility across public repos
- Install paths for branches, tags, SHAs, and published registry packages
- Example repo flows
- Conformance against the Agent Assembly protocol

This repo does **not** replace unit or integration tests inside each product repo.

## Repository layout

```text
agent-assembly-integration-tests/
  scripts/
    verify-public-stack.sh     # entry point: verify all repos at given refs
    summarize-run.sh           # produce sanitized summary.json from pytest report
    report-failure.sh          # create/update GitHub Issues from summary.json
    install-from-branch.sh     # clone and build from a named branch
    install-from-tag.sh        # checkout exact git tags
    install-from-release.sh    # install from public registries / release artifacts
  tests/
    install/                   # smoke tests for install paths
    sdk/                       # SDK compatibility smoke tests
    examples/                  # example repo flow tests
    conformance/               # protocol conformance tests
  fixtures/
    policies/                  # sample policy files for test inputs
    expected-output/           # expected output snapshots for assertions
  docs/
    production-validation-runbook.md  # how to run this repo as the production validation harness
    verification-modes.md      # how to use each verification mode
    evidence-template.md       # template for Jira / release report evidence
  .github/workflows/
    verify-latest.yml              # scheduled + manual: verify latest base branches
    verify-tag.yml                 # manual: verify exact git tags
    verify-release.yml             # on release publish + manual: verify artifacts
    verify-public-manual.yml       # manual: verify selected mode/area with ref inputs
    verify-public-scheduled.yml    # scheduled (1st/15th): full public stack health check
```

## Documentation

| Doc | Purpose |
|---|---|
| [`docs/production-validation-runbook.md`](docs/production-validation-runbook.md) | Practical runbook: prerequisites, how to run each validation area, strict-vs-smoke, skip/xfail interpretation, QA-environment troubleshooting, and Jira evidence |
| [`docs/verification-modes.md`](docs/verification-modes.md) | Which ref/mode to target (`latest` / `tag` / `sha` / `release`) |
| [`docs/evidence-template.md`](docs/evidence-template.md) | Template for Jira / release verification evidence |

## Verification modes

| Mode | Input | When to use |
|---|---|---|
| `latest` | Branch names (default: `master`) | PR/dev integration and scheduled health checks |
| `tag` | Git tags (e.g. `v0.1.0`) | Release verification and regression reproduction |
| `sha` | Exact commit SHAs | Incident / debug reproduction |
| `release` | Registry version strings (e.g. `0.1.0`) | Verify what public users can install |

## Quickstart

```bash
# Verify latest base branches (default mode)
bash scripts/verify-public-stack.sh

# Verify a specific tag across all repos
bash scripts/verify-public-stack.sh \
  --mode tag \
  --agent-assembly-ref v0.1.0 \
  --python-sdk-ref v0.1.0 \
  --node-sdk-ref v0.1.0 \
  --go-sdk-ref v0.1.0 \
  --examples-ref v0.1.0

# Install from a named branch and smoke-test
bash scripts/install-from-branch.sh --repo agent-assembly --ref feat/my-branch

# Install from a published release version
bash scripts/install-from-release.sh --python-sdk 0.1.0 --node-sdk 0.1.0
```

## Covered repositories

| Repo | GitHub URL |
|---|---|
| `agent-assembly` | https://github.com/ai-agent-assembly/agent-assembly |
| `python-sdk` | https://github.com/ai-agent-assembly/python-sdk |
| `node-sdk` | https://github.com/ai-agent-assembly/node-sdk |
| `go-sdk` | https://github.com/ai-agent-assembly/go-sdk |
| `agent-assembly-examples` | https://github.com/ai-agent-assembly/examples |

## CI

| Workflow | Trigger | Purpose |
|---|---|---|
| `verify-latest.yml` | Weekly schedule + `workflow_dispatch` | Integration health check on latest base branches |
| `verify-tag.yml` | `workflow_dispatch` with tag inputs | Reproducibility check on exact source snapshots |
| `verify-release.yml` | GitHub release publish + `workflow_dispatch` | Verify public install paths |
| `verify-public-manual.yml` | `workflow_dispatch` | Manual public stack check with mode/area/ref selection |
| `verify-public-scheduled.yml` | Schedule (1st/15th monthly) + `workflow_dispatch` | Scheduled public health check; creates failure issues |
| `harness-metadata-check.yml` | PR + `push` to `master` (paths-filtered) | Guard shared metadata (`metadata/harness.yaml`) against drift; validate shell syntax |

## Shared metadata

The install and verification shell scripts under `scripts/` share a small
set of drift-prone constants (GitHub org, package identifiers per registry,
the `aasm-verify public` CLI entrypoint). These are pinned in a single
source of truth at `metadata/harness.yaml` and rendered into each script by
`scripts/generate_harness_metadata.py`.

Sentinel blocks in each affected script mark generated regions:

```sh
# BEGIN GENERATED: <id>
KEY="value"
# END GENERATED: <id>
```

**Do not edit generated blocks by hand.** Edit `metadata/harness.yaml`
and re-run the generator:

```bash
python scripts/generate_harness_metadata.py
```

The `harness-metadata-check.yml` workflow re-runs the generator on every
PR touching the SoT or a target script and fails on drift
(`git diff --exit-code`), then runs `bash -n` on each affected script.

Current sentinel blocks:

| Block id | Owning scripts | Purpose |
|---|---|---|
| `install-defaults-github-org` | `install-from-branch.sh`, `install-from-tag.sh` | Pin the GitHub org that hosts every clone URL |
| `install-defaults-package-ids` | `install-from-release.sh` | Pin the PyPI dist / npm scope / Go module path |
| `harness-verify-command` | `resolve-refs.sh`, `verify-public-stack.sh` | Pin the `aasm-verify public` CLI entrypoint |

Adding a new sentinel block requires two changes: extend `metadata/harness.yaml`
with the underlying fields, then register a `render_*` function in
`scripts/generate_harness_metadata.py`'s `RENDERERS` dict.

## Scheduled verification

`verify-public-scheduled.yml` runs automatically on the **1st and 15th of each month at 02:00 UTC**.

It verifies all five public test areas — `runtime`, `sdk`, `examples`, `install`, `conformance` — in parallel matrix jobs using `latest` mode (base branches).

### Manual ad-hoc run

To trigger a scheduled-style run without waiting for the cron:

1. Open the [Actions tab](../../actions/workflows/verify-public-scheduled.yml)
2. Click **Run workflow** → **Run workflow**

### Selective manual run

To run a specific mode or area:

1. Open [Verify Public Stack (Manual)](../../actions/workflows/verify-public-manual.yml)
2. Click **Run workflow**
3. Fill in `mode`, `test_group`, and any ref overrides
4. Click **Run workflow**

Example inputs:

| Field | Value | Description |
|---|---|---|
| `mode` | `latest` | Verify against base branches |
| `test_group` | `sdk` | Run only the SDK test area |
| `agent_assembly_ref` | `v0.1.0` | Pin agent-assembly to a tag |

## Failure issue policy

When a scheduled or manual run fails, `report-failure.sh` automatically creates or updates a GitHub Issue in this repository.

**One issue per failing area** (e.g. `runtime`, `sdk`), not one per run:

| Condition | Action |
|---|---|
| Open issue exists for the area | Append a comment with the new run URL and summary |
| Closed issue exists for the area | Reopen the issue and add a regression comment |
| No issue exists | Create a new issue |

**Issue labels:**

- `test-failure`
- `scheduled-run`
- `needs-triage`
- `area: <area>` — e.g. `area: runtime`, `area: sdk`, `area: examples`

**Issue body includes:**

- Test area and verification mode
- GitHub Actions run URL
- Short sanitized summary (test counts, failed test names)
- No log dumps, no private data, no internal endpoints

**Successful runs** produce no issues.

## Related tickets

- [AAASM-2220](https://lightning-dust-mite.atlassian.net/browse/AAASM-2220) — Cross-repo integration and E2E verification infrastructure (Epic)
- [AAASM-2221](https://lightning-dust-mite.atlassian.net/browse/AAASM-2221) — Bootstrap public cross-repo integration test repository (Story)
- [AAASM-2225](https://lightning-dust-mite.atlassian.net/browse/AAASM-2225) — Public integration verification for Agent Assembly OSS and release paths (Epic)
- [AAASM-2229](https://lightning-dust-mite.atlassian.net/browse/AAASM-2229) — Add scheduled workflows and failure issue reporting (Story)
- [AAASM-4335](https://lightning-dust-mite.atlassian.net/browse/AAASM-4335) — Extend shared-metadata drift prevention to test/example repos (Epic)
- [AAASM-4337](https://lightning-dust-mite.atlassian.net/browse/AAASM-4337) — Generate install-script metadata to prevent harness drift (Story)
