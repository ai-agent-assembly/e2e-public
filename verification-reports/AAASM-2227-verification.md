# Verification Report: AAASM-2227

**Story:** Public tests: Implement verification CLI and ref/version resolver  
**Verified by:** AAASM-2271  
**Date:** 2026-05-30  
**Repo:** agent-assembly-integration-tests  
**Branch stack:** AAASM-2263 → AAASM-2265 → AAASM-2266 → AAASM-2269

---

## Acceptance Criteria Verification

### AC1 — `pyproject.toml` defines a Python CLI package managed by `uv`

**Status: PASS**

- `pyproject.toml` is present with `requires = ["hatchling"]` build backend
- `[project.scripts]` section defines `aasm-verify = "aasm_verify.cli:main"`
- `requires-python = ">=3.12"` is set
- `[dependency-groups] dev` includes `pytest>=8.0`, `pytest-xdist>=3.0`, `ruff>=0.4`
- `uv sync` and `uv run aasm-verify` both succeed

---

### AC2 — `aasm-verify` CLI validates required args and prints a target matrix before running tests

**Status: PASS**

```
$ uv run aasm-verify public --mode latest --dry-run
┌─ Verification Target Matrix ─────────────────────────────┐
│  mode:              latest                                │
│  agent-assembly:    master                                │
│  python-sdk:        master                                │
│  node-sdk:          master                                │
│  go-sdk:            master                                │
│  examples:          master                                │
└──────────────────────────────────────────────────────────┘
[dry-run] No cloning or installing performed.
```

```
$ uv run aasm-verify public --mode tag --agent-assembly-ref v0.0.1 --dry-run
┌─ Verification Target Matrix ─────────────────────────────┐
│  mode:              tag                                   │
│  agent-assembly:    v0.0.1                                │
│  ...                                                      │
└──────────────────────────────────────────────────────────┘
```

---

### AC3 — `verify-public-stack.sh` delegates to the Python CLI

**Status: PASS**

`scripts/verify-public-stack.sh` contains `exec uv run aasm-verify public "$@"` and performs no argument logic of its own. All validation happens in the Python CLI.

---

### AC4 — Resolver supports `agent-assembly`, `python-sdk`, `node-sdk`, `go-sdk`, and `agent-assembly-examples`

**Status: PASS**

`PUBLIC_REPOS` in `src/aasm_verify/refs.py`:

```python
PUBLIC_REPOS: tuple[str, ...] = (
    "agent-assembly",
    "python-sdk",
    "node-sdk",
    "go-sdk",
    "agent-assembly-examples",
)
```

Assertion `set(PUBLIC_REPOS) == expected_5_repos` passes.

---

### AC5 — Unsupported mode/ref combinations fail fast with clear errors

**Status: PASS**

| Scenario | Error message |
|---|---|
| `--mode release` (no `--version`) | `error: Mode 'release' requires --version (e.g. --version 0.0.1).` |
| `--mode latest --agent-assembly-ref v1` | `error: Mode 'latest' uses master branches … Do not pass per-repo refs …` |
| `--mode tag` (no refs) | `error: Mode 'tag' requires at least one per-repo ref …` |

All exit with code 1.

---

### AC6 — `--dry-run` prints planned actions without cloning/installing

**Status: PASS**

Running any command with `--dry-run` prints the target matrix and outputs `[dry-run] No cloning or installing performed.` then exits 0 without any network or filesystem side effects.

---

### AC7 — `docs/verification-modes.md` documents all modes and examples

**Status: PASS**

`docs/verification-modes.md` contains sections:
- `### \`latest\`` with usage example and CI workflow reference
- `### \`tag\`` with per-repo ref examples
- `### \`sha\`` with SHA usage
- `### \`release\`` with registry install examples

---

### AC8 — No private repo names or private endpoints are referenced

**Status: PASS**

Grep for `agent-assembly-cloud`, `agent-assembly-enterprise`, `agent-assembly-private`, `saas`, `internal.` across `src/`, `scripts/`, `docs/` returns no matches.

---

## Summary

| AC | Status |
|---|---|
| pyproject.toml with uv CLI package | ✅ PASS |
| CLI arg validation + target matrix | ✅ PASS |
| verify-public-stack.sh delegates to CLI | ✅ PASS |
| Resolver supports all 5 repos | ✅ PASS |
| Fail-fast on unsupported mode/ref combos | ✅ PASS |
| `--dry-run` no-op | ✅ PASS |
| verification-modes.md complete | ✅ PASS |
| No private names/endpoints | ✅ PASS |

**All 8 acceptance criteria: PASS. AAASM-2227 is complete.**
