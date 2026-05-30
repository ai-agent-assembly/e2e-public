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
    verification-modes.md      # how to use each verification mode
    evidence-template.md       # template for Jira / release report evidence
  .github/workflows/
    verify-latest.yml          # scheduled + manual: verify latest base branches
    verify-tag.yml             # manual: verify exact git tags
    verify-release.yml         # on release publish + manual: verify artifacts
```

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
  --agent-assembly v0.1.0 \
  --python-sdk v0.1.0 \
  --node-sdk v0.1.0 \
  --go-sdk v0.1.0 \
  --examples v0.1.0

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
| `agent-assembly-examples` | https://github.com/ai-agent-assembly/agent-assembly-examples |

## CI

| Workflow | Trigger | Purpose |
|---|---|---|
| `verify-latest.yml` | Weekly schedule + `workflow_dispatch` | Integration health check on latest base branches |
| `verify-tag.yml` | `workflow_dispatch` with tag inputs | Reproducibility check on exact source snapshots |
| `verify-release.yml` | GitHub release publish + `workflow_dispatch` | Verify public install paths |

## Related tickets

- [AAASM-2220](https://lightning-dust-mite.atlassian.net/browse/AAASM-2220) — Cross-repo integration and E2E verification infrastructure (Epic)
- [AAASM-2221](https://lightning-dust-mite.atlassian.net/browse/AAASM-2221) — Bootstrap public cross-repo integration test repository (Story)
