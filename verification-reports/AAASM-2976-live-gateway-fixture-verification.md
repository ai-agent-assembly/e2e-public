# Verification Report: AAASM-2976

**Story:** Live-core fixture: build + run aa-gateway from source with teardown
**Verified by:** AAASM-2982
**Date:** 2026-06-15
**Trigger:** Manual — end-of-implementation AC review

---

## Refs Verified

| Item | Value |
|---|---|
| Story | AAASM-2976 |
| Subtasks | AAASM-2977, AAASM-2978, AAASM-2979, AAASM-2980, AAASM-2981, AAASM-2982 |
| Repo | `ai-agent-assembly/agent-assembly-integration-tests` |
| Branch | `v0.0.1/AAASM-2976/live_gateway_fixture` |

---

## What was built

A new `tests/live/` package providing a `live_gateway` pytest fixture that
builds and runs a real `aa-gateway` from the `agent-assembly` core monorepo:

| Unit | File | Responsibility |
|---|---|---|
| AAASM-2977 | `tests/live/core_source.py` | Shallow-clone `agent-assembly` at a git ref (default `master`); `AASM_CORE_SOURCE_DIR` reuses an existing checkout |
| AAASM-2978 | `tests/live/build.py` | Ensure `cargo`/`protoc` present, run `cargo build -p aa-gateway`, return binary path |
| AAASM-2979 | `tests/live/gateway.py`, `tests/live/fixtures/policies/minimal.yaml` | Launch `aa-gateway --policy <minimal> --listen 127.0.0.1:<free port>` with isolated `$HOME`/audit dir |
| AAASM-2980 | `tests/live/gateway.py` | TCP readiness probe + terminate/cleanup teardown (context manager) |
| AAASM-2981 | `tests/live/conftest.py` | `live_gateway` fixture composing clone → build → launch → ready |
| AAASM-2982 | `tests/live/test_live_gateway.py` | Tests asserting readiness + clean teardown; skip when `cargo`/`protoc` absent |

---

## Acceptance Criteria Results

| # | Acceptance Criterion | Status | Evidence |
|---|---|---|---|
| 1 | Fixture builds `aa-gateway` from source | PASS | `cargo build -p aa-gateway` runs inside the resolved source tree; 26s wall incl. build |
| 2 | Gateway starts and becomes ready | PASS | `test_live_gateway_is_ready` connects to `127.0.0.1:<port>` |
| 3 | Teardown is clean (process reaped, port freed) | PASS | `test_live_gateway_tears_down_cleanly` re-binds the freed port after `stop()` |
| 4 | Skips gracefully without `cargo`/`protoc` | PASS | `missing_build_tools()` returns `['cargo','protoc']` under empty `PATH` → `pytest.skip` |
| 5 | Isolated `$HOME`/temp dir | PASS | `LiveGateway.start()` pins `HOME` to a `TemporaryDirectory` + per-run `--audit-dir` |

---

## Local validation

```
AASM_CORE_SOURCE_DIR=<sibling agent-assembly> uv run pytest tests/live -v
...
tests/live/test_live_gateway.py::test_live_gateway_is_ready PASSED       [ 50%]
tests/live/test_live_gateway.py::test_live_gateway_tears_down_cleanly PASSED [100%]
============================== 2 passed in 26.17s ==============================
```

`uv run ruff check tests/live/` — All checks passed.

Toolchain: `cargo 1.95.0`, `libprotoc 34.1`, `uv 0.7.6`, Python 3.13.

---

## Decisions / follow-ups

- The gateway listens on the gRPC port (`127.0.0.1:<free port>`, mirroring the
  monorepo default `:50051`). The Python SDK's default endpoint is `:7391`.
  Wiring an SDK to actually reach *this* live gateway (endpoint override) is
  deferred to the follow-up Story (A2) — out of scope for this foundation fixture.
- The clone is performed into a non-context-managed `mkdtemp` so the built
  binary survives for the whole (session-scoped) test session; `AASM_CORE_REF`
  selects the ref, `AASM_CORE_SOURCE_DIR` reuses a local checkout.
