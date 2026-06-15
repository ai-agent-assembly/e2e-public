# AAASM-2993 — Cross-SDK enforcement-mode parity (no live core)

## Summary

Added `tests/contract/test_enforcement_mode_parity.py` (+ `tests/contract/__init__.py`):
the cross-SDK half of the enforcement-mode contract Epic that needs **no live core**.
The suite reads the enforcement-mode contract straight out of each SDK's source /
built artifacts and asserts the three SDKs agree on the canonical posture vocabulary,
while pinning the known init/runtime-mode divergence as a documented finding.

## What the test asserts

### Check 1 — enforcement-mode parity (hard assertion)

Each SDK must expose **exactly** `{enforce, observe, disabled}`:

| SDK | Source of truth | How extracted |
|---|---|---|
| python | `agent_assembly/core/assembly.py` — `EnforcementMode = Literal[...]` | source-parse (no SDK install needed) |
| node | `@agent-assembly/sdk` `ENFORCEMENT_MODES` const | `node --input-type=module` import by **package name** so the `exports` map governs resolution (built `dist/` required) |
| go | `assembly/enforcement_mode.go` — `EnforcementMode*` consts | source-parse (no Go toolchain needed) |

Plus `test_enforcement_modes_match_across_sdks`: collects every present SDK's set and
asserts (a) each equals the canonical set and (b) all present sets are mutually equal.

**Result: all three SDKs match.** `{enforce, observe, disabled}` is identical across
python / node / go. No divergence on the enforcement-mode axis.

### Check 2 — init / runtime-mode divergence (pinned finding, NOT a fail)

The transport/runtime mode is a separate, SDK-local concept and the SDKs do **not**
agree on it today. The test pins current reality so the inconsistency is documented
and future drift is caught — it deliberately does not assert parity here.

| SDK | Init-mode vocabulary | Type |
|---|---|---|
| python | `auto`, `ebpf`, `proxy`, `sdk-only` | `RuntimeMode` Literal |
| node | `auto`, `sdk-only`, `grpc-sidecar`, `napi-inprocess` | `AssemblyMode` union |
| go | (none) | functional options (`WithXxx` in `options.go`); no init-mode enum |

- Shared subset between python and node: `{auto, sdk-only}` only.
- python-only tail: `{ebpf, proxy}` (names the interception layer).
- node-only tail: `{grpc-sidecar, napi-inprocess}` (names the transport mechanism).
- go: no `AssemblyMode` / `RuntimeMode` / `InitMode` enum at all — transport is
  configured purely through functional options.

`test_init_runtime_mode_divergence_is_pinned` asserts python != node, the exact shared
subset, and each SDK-specific tail. `test_go_has_no_init_mode_enum` asserts Go's
functional-options mechanism exists and no init-mode enum has appeared. Each carries a
clear comment that this is a finding for the parity Epic, not a parity claim.

## Skip behavior

Every SDK probe skips independently when that SDK's checkout or toolchain is absent
(`pytest.skip`), so the suite runs in partial environments (e.g. CI without Go, or a
node-sdk without a built `dist/`). The cross-SDK comparison runs over whichever SDKs
resolved.

## Validation

```
$ uv run pytest tests/contract -v
8 passed in 0.10s
$ uv run ruff check tests/contract/        # All checks passed!
$ uv run ruff format --check tests/contract/  # 2 files already formatted
```

All 8 tests passed locally with python-sdk, node-sdk (dist built), and go-sdk present
as siblings.

## File scope

Touched only `tests/contract/test_enforcement_mode_parity.py`,
`tests/contract/__init__.py`, and this report. No changes to `pyproject.toml`, other
test files, `tests/live/**`, or markers (reused the existing `sdk` marker).
