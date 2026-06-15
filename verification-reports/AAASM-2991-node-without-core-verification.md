# Verification Report: AAASM-2991

**Story:** node-sdk without-core behavioral: fail-open per enforcement mode
**Date:** 2026-06-15
**Trigger:** Manual — end-of-implementation AC review

---

## Refs Verified

| Item | Value |
|---|---|
| Story | AAASM-2991 |
| Repo | `ai-agent-assembly/agent-assembly-integration-tests` |
| Branch | `v0.0.1/AAASM-2991/node_without_core` |
| Files touched | `tests/behavioral/__init__.py` (new), `tests/behavioral/test_node_without_core.py` (new) |

---

## What was built

New behavioral test module `tests/behavioral/test_node_without_core.py` that
asserts the **designed fail-open behavior** of `@agent-assembly/sdk` when no
gateway (aa-core) is reachable. No gateway is ever started.

| Test | Responsibility |
|---|---|
| `test_node_fail_open_per_enforcement_mode` | For `enforce`, `observe`, and `disabled`, with the gateway unreachable, `initAssembly` resolves without throwing and the governed `check()` resolves to `denied: false`. |
| `test_node_auto_mode_boots_without_gateway` | In the default (`auto`) mode — which additionally fires a native registration event at boot — `initAssembly` and `shutdown` complete cleanly with no gateway, preserving the configured `enforcementMode`. |

Both reuse the established `skip_if_binary_missing(...)` gating from
`tests/public/conftest.py`, so they SKIP cleanly when `node`/`npm` are absent
and RUN when present.

## Why this is the right assertion (design read)

Reading `node-sdk/src/core/init-assembly.ts` and `node-sdk/src/gateway/client.ts`:

- `createClient(config)` returns `createNoopGatewayClient(mode)` whenever no
  gateway client is injected (the default path). The no-op client's
  `check()` returns `{ denied: false, pending: false }` **regardless of
  enforcement mode** — this is the SDK's fail-open contract.
- The SDK is explicitly *not* a security boundary (the runtime/proxy/eBPF
  layers are); a down gateway must never block a governed action from the
  SDK's perspective. The test locks that in per mode.
- In `auto` mode the only gateway interaction at boot is a fire-and-forget
  native `sendEvent`, so an unreachable gateway does not raise — verified by
  the second test.

The tests assert directly on the no-op client's `check()` decision (the unit
that encodes fail-open) plus the boot/shutdown lifecycle, which is the cleanest
demonstrable level of the designed behavior.

## Test harness

- Builds the sibling `../node-sdk` checkout via `pnpm build` (committed `dist/`
  may be stale), then `npm install`s the local package into an isolated
  temporary ESM project and shells out to `node` — mirroring
  `tests/public/test_node_sdk.py`.
- SKIPs (not fails) when `node`/`npm`/the node-sdk checkout are absent, or when
  the build/install fails in this environment.

## File scope

Touched only `tests/behavioral/__init__.py`, `tests/behavioral/test_node_without_core.py`,
and `verification-reports/`. No changes to `pyproject.toml`, other SDK tests,
`tests/live/**`, or any pytest marker (reused the existing `sdk` marker).

---

## Validation

```
$ uv run ruff check tests/behavioral
All checks passed!

$ uv run pytest tests/behavioral -v
tests/behavioral/test_node_without_core.py::test_node_fail_open_per_enforcement_mode PASSED
tests/behavioral/test_node_without_core.py::test_node_auto_mode_boots_without_gateway PASSED
2 passed
```

## Acceptance criteria

| Criterion | Status |
|---|---|
| `enforce`, no gateway → action proceeds, no error | Met — `denied=false`, init OK |
| `observe`, no gateway → proceeds | Met — `denied=false`, init OK |
| `disabled`, no gateway → proceeds | Met — `denied=false`, init OK |
| Shells out to `node`; installs `@agent-assembly/sdk` from `../node-sdk` | Met |
| SKIP when node/package absent | Met |
| No gateway started | Met |
| File scope respected | Met |
