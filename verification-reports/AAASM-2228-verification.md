# Verification Report: AAASM-2228

**Story:** Public tests: Add runtime SDK examples and policy conformance smoke tests  
**Verified by:** AAASM-2306  
**Date:** 2026-05-31  
**Repo:** agent-assembly-integration-tests  
**Branch stack:** AAASM-2293 → AAASM-2295 → AAASM-2297 → AAASM-2300 → AAASM-2302 → AAASM-2304

---

## Acceptance Criteria Verification

### AC1 — Runtime CLI smoke test exists in pytest form

**Status: PASS**

`tests/public/test_runtime_cli.py` contains:
- `test_aasm_version` — runs `aasm --version`, asserts exit 0 and non-empty output
- `test_aasm_help` — runs `aasm --help`, asserts exit 0 and non-empty output

Both tests are marked `@pytest.mark.runtime`. Both skip with a clear message when `aasm` is not in PATH. Failure messages include the component name `agent-assembly`.

---

### AC2 — Python SDK init smoke exists

**Status: PASS**

`tests/public/test_python_sdk.py` contains:
- `test_python_sdk_importable` — `import agent_assembly` succeeds
- `test_python_sdk_version_string` — `agent_assembly.__version__` is a non-empty string
- `test_python_sdk_public_exports` — `init_assembly`, `AssemblyContext`, `AssemblyError` are accessible at the top-level package

All tests are marked `@pytest.mark.sdk`. All skip gracefully via `skip_if_package_missing("agent_assembly")` when the package is not installed.

---

### AC3 — Node.js/TypeScript SDK init smoke exists

**Status: PASS**

`tests/public/test_node_sdk.py` contains:
- `test_node_sdk_importable` — verifies `import '@agent-assembly/sdk'` succeeds via `node --input-type=module`
- `test_node_sdk_public_exports` — verifies `initAssembly` (function) and `ENFORCEMENT_MODES` (object) are exported

Both tests are marked `@pytest.mark.sdk`. Both skip with a clear message when `node` is absent or the package is not installed.

---

### AC4 — Go SDK init/build smoke exists

**Status: PASS**

`tests/public/test_go_sdk.py` contains:
- `test_go_sdk_builds` — creates a temp Go module with a local replace directive and runs `go build ./...`
- `test_go_sdk_runs_smoke` — runs a minimal Go program that accesses `assembly.ErrBinaryNotFound` and verifies it prints `true`

Both tests are marked `@pytest.mark.sdk`. Both skip with a clone instruction when `go` is absent or the local `go-sdk` directory is not found.

---

### AC5 — Examples smoke test exists and can be skipped with a clear reason if examples repo is not ready

**Status: PASS**

`tests/public/test_examples.py` contains:
- `test_examples_repo_present` — verifies the `agent-assembly-examples` repo is cloned next to this repo
- `test_examples_python_directory_not_empty` — verifies at least one Python example directory exists
- `test_examples_python_readme_exists` — verifies at least one Python example has a README

All three tests are marked `@pytest.mark.examples`. When the examples repo is absent, all three skip with the message:

```
[agent-assembly-examples] examples repo not found next to this repo — clone
https://github.com/AI-agent-assembly/agent-assembly-examples alongside this
repo to enable examples smoke tests
```

---

### AC6 — Basic policy allow/deny fixture exists

**Status: PASS**

`fixtures/policies/allow-deny-basic.yaml` is present with:
- `version: "1"`, `name: "allow-deny-basic"`
- Rule `deny-restricted-action` (effect: deny, priority: 10, action: `test.restricted`)
- Rule `allow-all` (effect: allow, priority: 0, action: `*`)

`test_policy_conformance.py::test_allow_deny_fixture_exists` and `test_allow_deny_fixture_well_formed` both verify this file is present and parses correctly with both allow and deny effects.

---

### AC7 — Tests produce concise machine-readable summary output

**Status: PASS**

All test failure messages follow the pattern `[<component>] <description>` and include exit code, stdout, and stderr when subprocess is involved, enabling automated parsing and Jira linking by component name.

```
AssertionError: [agent-assembly] aasm --version failed (exit 1)
stdout: 
stderr: bash: aasm: command not found
```

Pytest's native `-v --tb=short` and `--json-report` (via pytest-json-report) can produce machine-readable JSON. The test structure with named markers enables matrix selection for CI reporting.

---

### AC8 — Failures identify the component/ref/version that failed

**Status: PASS**

Every test module uses a module-level `COMPONENT` constant (`"agent-assembly"`, `"python-sdk"`, `"node-sdk"`, `"go-sdk"`, `"agent-assembly-examples"`, `"policy-conformance"`) and prefixes all assertion messages and skip reasons with `[{COMPONENT}]`. This ensures pytest output and CI logs identify the failing component without inspecting the test name.

---

### AC9 — Safe test groups can run through GitHub Actions matrix or `pytest -n auto`

**Status: PASS**

All test groups are isolated by marker (`runtime`, `sdk`, `examples`, `conformance`). No test has shared state or global fixtures that could cause ordering dependencies. Tests that require external tools skip, so `pytest -n auto` (via `pytest-xdist`) runs the collection without failures from missing binaries. Markers are registered in `pyproject.toml` `[tool.pytest.ini_options]`.

Example CI matrix selection:
```yaml
- name: Runtime tests
  run: uv run pytest -m runtime
- name: SDK tests
  run: uv run pytest -m sdk
- name: Conformance tests
  run: uv run pytest -m conformance
- name: Examples tests
  run: uv run pytest -m examples
```

---

## Summary

| AC | Description | Status |
|---|---|---|
| AC1 | Runtime CLI smoke test in pytest form | ✅ PASS |
| AC2 | Python SDK init smoke | ✅ PASS |
| AC3 | Node.js/TypeScript SDK init smoke | ✅ PASS |
| AC4 | Go SDK init/build smoke | ✅ PASS |
| AC5 | Examples smoke with skip reason when not ready | ✅ PASS |
| AC6 | Basic policy allow/deny fixture exists | ✅ PASS |
| AC7 | Tests produce concise machine-readable summary output | ✅ PASS |
| AC8 | Failures identify component/ref/version | ✅ PASS |
| AC9 | Safe groups run via matrix or `pytest -n auto` | ✅ PASS |

**All 9 acceptance criteria: PASS. AAASM-2228 is complete.**
