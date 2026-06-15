# Verification Report: AAASM-2989

**Bug / task:** [AAASM-2989](https://lightning-dust-mite.atlassian.net/browse/AAASM-2989) — Re-target SDK⇄core verification at the FFI→aa-runtime path (HTTP→gateway path was a deviation)
**Verified by:** AAASM-2999
**Date:** 2026-06-15
**Status:** ✅ Re-orientation complete — and it surfaced a real product bug ([AAASM-3000](https://lightning-dust-mite.atlassian.net/browse/AAASM-3000))

---

## What changed

The with-core live harness previously built and ran **aa-gateway** and pointed the SDK's HTTP
`GatewayClient` at its gRPC port — the deviant `SDK → gateway (HTTP)` path. This work re-orients it at
the **real** path: `SDK → aa-ffi → aa-runtime` over the Unix domain socket
`/tmp/aa-runtime-<agent_id>.sock`.

| Subtask | Deliverable |
|---|---|
| AAASM-2994 | `build_runtime()` — `cargo build -p aa-runtime` |
| AAASM-2995 | `LiveRuntime` — launches aa-runtime (env-driven), awaits UDS readiness, tears down |
| AAASM-2996 | `core_runtime_binary` + `live_runtime` pytest fixtures |
| AAASM-2997 | `test_live_runtime.py` — UDS reachability floor |
| AAASM-2998 | `runtime_client.py` connector + `test_sdk_runtime.py` — real native `_core` FFI |
| AAASM-2999 | this report |

## Launch contract (verified empirically on macOS)

`aa-runtime` is configured purely by environment (no CLI flags):

| Var | Value used | Effect |
|---|---|---|
| `AA_AGENT_ID` | unique `aaitest-<uuid8>` | names the UDS `/tmp/aa-runtime-<id>.sock` (per-test isolation) |
| `AA_POLICY_PATH` | `""` | policy disabled — this fixture verifies transport, not policy |
| `AA_METRICS_ADDR` | `127.0.0.1:<free>` | avoids the default `:8080` collision between instances |

The runtime binds the socket (`srw-------`), accepts an `AF_UNIX` connect, and `remove_file`s it on
SIGTERM. The real SDK path is `agent_assembly._core.RuntimeClient.connect(socket_path)` → `send_event`
→ `close` (thin pyo3 shim over `aa-sdk-client`).

## Acceptance criteria

### AC 1 — Harness builds + runs the real aa-runtime and proves UDS reachability

**Status:** ✅ PASS — `pytest -m live tests/live/test_live_runtime.py` → **2 passed** against a real
`aa-runtime` built from canonical master. The socket binds, matches the
`/tmp/aa-runtime-<id>.sock` convention, accepts a connect, and is removed on stop.

### AC 2 — Real SDK native FFI drives a session against the live runtime

**Status:** ✅ PASS (test wired + executed end-to-end). Built the compiled `agent_assembly._core`
extension and ran `RuntimeClient.connect → send_event ×5 → close` against the live runtime.
`connect` and `send_event` return; the test exercises the genuine FFI path. Skips cleanly when the
toolchain or the `_core` extension is absent.

### AC 3 — The deviant SDK→gateway-HTTP probe is superseded, not the verification

**Status:** ✅ PASS — `test_sdk_register.py` is re-framed as a record of the deviant HTTP probe;
`test_sdk_runtime.py` is now the SDK→core verification. `pytest -m live` collects all 7 live tests; the
default suite stays green (82 passed / 21 skipped / live deselected).

## Finding — a real product bug (AAASM-3000)

Running the **real** SDK against the **real** runtime end-to-end **deadlocks**: `aa-sdk-client`'s IPC
loop blocks on a heartbeat/event `Ack` that `aa-runtime` never sends (`pipeline/mod.rs:137` — heartbeats
ignored; clean events get no ack). The background IPC thread never drains the command channel, so
`close()` hangs and **no events are delivered**. Both sides' own tests pass only because the SDK tests
use a **mock that acks** — a protocol the real runtime does not implement. Shared `aa-sdk-client` ⇒ all
three SDKs affected.

This is exactly the cross-component gap the integration-tests repo exists to catch. `test_sdk_runtime.py`
encodes it as `xfail(strict=False)` with a `close()` watchdog (never hangs CI; flips to `XPASS` when
fixed). Filed as **AAASM-3000** (High), linked to this ticket.

## Notes

- No PR-gating lint/unit CI exists in this repo (all workflows are schedule / `workflow_dispatch`).
  Validation here is local: `ruff check tests/live/` clean, default suite green, live suite executed.
- Two pre-existing `ruff` import-order errors in `tests/public/` are untouched (out of scope).
