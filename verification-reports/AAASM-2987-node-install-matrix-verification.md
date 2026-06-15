# Verification Report: AAASM-2987

**Story:** node-sdk install matrix: napi addon loads + functional install
**Date:** 2026-06-15
**Trigger:** Manual — end-of-implementation AC review

---

## Refs Verified

| Item | Value |
|---|---|
| Story | AAASM-2987 |
| Repo | `ai-agent-assembly/agent-assembly-integration-tests` |
| Branch | `v0.0.1/AAASM-2987/node_install_matrix` |
| File touched | `tests/public/test_node_sdk.py` |

---

## What was built

Extended the existing public node-sdk smoke (`tests/public/test_node_sdk.py`)
with two install-matrix tests that exercise the **installed** `@agent-assembly/sdk`
package beyond a JS-only import:

| Test | Responsibility |
|---|---|
| `test_node_sdk_functional_install` | Asserts `initAssembly` is a callable function and `ENFORCEMENT_MODES` is exactly the canonical `["enforce", "observe", "disabled"]` set, imported from the installed package. |
| `test_node_sdk_native_addon_loads` | Resolves the package root via the exports map, requires the shipped native loader (`native/aa-ffi-node/index.cjs`), and asserts the napi binding actually loaded — `connect`/`sendEvent`/`disconnect` are functions. |

Both follow the established `skip_if_binary_missing('node')` + `_node_has_package()`
gating pattern, so they SKIP cleanly when `node` or the npm package is absent and
RUN when the package is installed (from registry or source).

### Respecting the exports-map reality (AAASM-2968)

The package `exports` map exposes only `.` and `./hooks`; it does **not** expose
`./package.json` or `./native/...`. The native-addon test therefore does not
`import '@agent-assembly/sdk/native/...'` nor `require('@agent-assembly/sdk/package.json')`.
Instead it resolves the package main entry via `import.meta.resolve` (which honours
the exports map), walks up to the directory whose `package.json` declares the package
name, and requires `native/aa-ffi-node/index.cjs` from disk — mirroring how the SDK's
own loader (`src/native/client.ts`) reaches the addon. `index.cjs` resolves the
platform `*.node` binary (`index.node` or `index.<platform>.node`), so a successful
`require` means the native binary loaded into the process.

---

## Acceptance Criteria Results

| # | Acceptance Criterion | Status | Evidence |
|---|---|---|---|
| 1 | napi addon actually resolves/loads after install (not just JS) | PASS | `test_node_sdk_native_addon_loads` requires `native/aa-ffi-node/index.cjs`, which loads the `*.node` addon, then asserts `connect`/`sendEvent`/`disconnect` are functions. |
| 2 | Functional install: `initAssembly` is a function, `ENFORCEMENT_MODES` is the expected object | PASS | `test_node_sdk_functional_install` asserts `typeof initAssembly === 'function'` and `ENFORCEMENT_MODES === ["enforce","observe","disabled"]`. |
| 3 | Respect exports-map reality (no `./package.json` / `./native` subpath import) | PASS | Tests resolve the package root from disk via `import.meta.resolve` + walk-up; no unexposed subpath is imported. |
| 4 | Skip path preserved when node / package absent | PASS | Both tests gate on `skip_if_binary_missing('node')` and `_node_has_package()`. |

---

## Validation performed

Run path — `@agent-assembly/sdk` installed from source (`../node-sdk`, `pnpm build`
to refresh `dist/`), `node_modules` resolvable from the worktree:

```
tests/public/test_node_sdk.py::test_node_sdk_importable PASSED
tests/public/test_node_sdk.py::test_node_sdk_public_exports PASSED
tests/public/test_node_sdk.py::test_node_sdk_functional_install PASSED
tests/public/test_node_sdk.py::test_node_sdk_native_addon_loads PASSED
4 passed
```

Skip path — package not installed:

```
tests/public/test_node_sdk.py::test_node_sdk_importable SKIPPED
tests/public/test_node_sdk.py::test_node_sdk_public_exports SKIPPED
tests/public/test_node_sdk.py::test_node_sdk_functional_install SKIPPED
tests/public/test_node_sdk.py::test_node_sdk_native_addon_loads SKIPPED
4 skipped
```

Lint:

```
uv run ruff check tests/public/test_node_sdk.py
All checks passed!
```

---

## Notes / findings

- `ENFORCEMENT_MODES` is a readonly **array** (`["enforce", "observe", "disabled"]`),
  not a keyed object; the existing `typeof === 'object'` smoke passes for arrays,
  and the new functional test pins the exact canonical value.
- The committed `dist/` in the source checkout was stale (missing the `ENFORCEMENT_MODES`
  re-export); `pnpm build` in `../node-sdk` was required to exercise the run path
  from source. A registry install ships an already-built `dist/`.
- An incidental pre-existing `ruff I001` import-sort finding on the file (blank line
  between the third-party and first-party import groups) was corrected so the file
  lints clean per the task gate.
