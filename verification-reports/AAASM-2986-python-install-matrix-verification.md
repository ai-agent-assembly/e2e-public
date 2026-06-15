# Verification Report: AAASM-2986

**Story:** python-sdk install matrix — native binding loads + functional install
**Date:** 2026-06-15
**Trigger:** End-of-implementation AC review

---

## Refs Verified

| Item | Value |
|---|---|
| Story | AAASM-2986 |
| Repo | `ai-agent-assembly/agent-assembly-integration-tests` |
| Branch | `v0.0.1/AAASM-2986/python_install_matrix` |
| File scope | `tests/public/test_python_sdk.py` (extended), `verification-reports/` |

---

## What was built

Two new `@pytest.mark.sdk` tests added to `tests/public/test_python_sdk.py`,
plus a small skip helper:

1. **`test_python_sdk_native_binding_loads`** — proves the install is
   native-accelerated, not pure-Python. Imports the PyO3 extension submodule
   `agent_assembly._core` and asserts its `__file__` ends in a compiled-artifact
   suffix (`.so` / `.pyd` / `.dylib`) and that it exposes its native-backed
   symbols (`RuntimeClient`, `GovernanceEvent`).
2. **`test_python_sdk_functional_install`** — asserts `init_assembly` is
   callable and `AssemblyError` is a raisable/catchable `Exception` subclass —
   functional usability beyond mere `hasattr` presence.
3. **`_require_native_module()` helper** + `NATIVE_MODULE` constant — imports
   `_core` when present, skips cleanly on a pure-Python install so both install
   flavours stay green. Keeps platform/version expansion trivial later (single
   guarded entry point).

The native extension module name is sourced from the SDK's own packaging config
(`module-name = "agent_assembly._core"` in `python-sdk/pyproject.toml`).

---

## Validation

### Skip path (no SDK installed) — confirmed

```
uv run pytest tests/public/test_python_sdk.py -v
# 5 skipped (importable, version_string, public_exports,
#            native_binding_loads, functional_install)
```

### Run path (native SDK installed) — confirmed

A native wheel was built for the worktree interpreter (CPython 3.13) via
`maturin build --release` against `python-sdk/native/aa-ffi-python` and installed
into the venv:

```
agent_assembly/_core.cpython-313-darwin.so
RuntimeClient present: True   GovernanceEvent present: True

uv run pytest tests/public/test_python_sdk.py -v
# 5 passed — including test_python_sdk_native_binding_loads and
#            test_python_sdk_functional_install
```

The native-binding test was exercised against a real installed, compiled SDK
(`.so` loaded), not merely the skip branch. The SDK was uninstalled afterward to
restore the default skip state.

### Lint — clean

```
uv run ruff check tests/public/test_python_sdk.py   # All checks passed!
```

---

## Notes / Blockers

- The package publishes to PyPI as `agent-assembly`, imports as `agent_assembly`;
  the native ext is `agent_assembly._core`.
- No prebuilt `.so` ships in the `../python-sdk` source tree — the native test
  skips unless a native wheel is installed (CI install-matrix or local maturin
  build). Both run and skip paths verified locally.
- File scope respected: only `tests/public/test_python_sdk.py` and
  `verification-reports/` touched.
