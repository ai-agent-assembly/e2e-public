# AAASM-2985 — Verification: Wire an SDK to the live core + make live tests opt-in

**Date:** 2026-06-15
**Branch:** `v0.0.1/AAASM-2985/sdk_transport_wiring`
**Repo:** `agent-assembly-integration-tests`

## Scope

Wire a real Python SDK at the `live_gateway` fixture (AAASM-2976), add a
`live`-marked registration smoke test, and make all `live` tests opt-in. Touched
only `tests/live/**`, the `[tool.pytest.ini_options]` block of `pyproject.toml`,
and `verification-reports/`.

## Transport resolution (the crux)

A Python SDK **cannot** register against a running `aa-gateway` today — this is a
real product gap, documented in
`verification-reports/AAASM-2985-sdk-transport-investigation.md` and confirmed
empirically:

- The Python SDK speaks **HTTP/REST** (`httpx`), POSTing `/agents/{id}/register`,
  resolving its URL from `AAASM_GATEWAY_URL` / default `http://localhost:7391`.
- The runnable `aa-gateway` either serves **gRPC only** (`legacy-grpc` mode — what
  the fixture launches) or an **HTTP surface that mounts only `/healthz`,
  `/api/v1/admin/status`, and the dashboard** (`local` mode) — never the SDK's
  REST routes.
- Those REST routes live in **`aa-api`, a library crate with no binary**.

Running the real SDK against the fixture gateway: reachability **PASSES**, but the
HTTP/1.1 register POST against the gRPC (HTTP/2) listener fails with
`httpcore.RemoteProtocolError: illegal request line`. No false green — the
registration test is `xfail(strict=False)`.

**To make real registration pass** (separate core/SDK tickets): either give the
SDK's REST routes a runnable HTTP front door (an `aa-api` binary, or have
`aa-gateway` `local` mode mount `aa-api`'s router), or add a gRPC transport to the
Python SDK. Then flip the `xfail` to a hard assert.

## What was delivered

| Item | File |
|---|---|
| Transport investigation note | `verification-reports/AAASM-2985-sdk-transport-investigation.md` |
| SDK config helper | `tests/live/sdk_client.py` |
| `live` registration smoke test | `tests/live/test_sdk_register.py` |
| Opt-in `addopts` | `pyproject.toml` `[tool.pytest.ini_options]` |

## Acceptance evidence

### Live tests are opt-in

```
$ uv run pytest --collect-only -q
73/77 tests collected (4 deselected)        # all 4 live tests deselected by default

$ uv run pytest -m live --collect-only -q
4/77 tests collected (73 deselected)        # exactly the 4 live tests
  tests/live/test_live_gateway.py::test_live_gateway_is_ready
  tests/live/test_live_gateway.py::test_live_gateway_tears_down_cleanly
  tests/live/test_sdk_register.py::test_sdk_can_reach_live_gateway
  tests/live/test_sdk_register.py::test_sdk_registers_agent_against_live_gateway
```

`grep -c tests/live` on the default collection returns **0**.

### Live smoke test — SDK absent (CI default): clean skip

```
$ uv run pytest -m live tests/live/test_sdk_register.py -v
test_sdk_can_reach_live_gateway                SKIPPED
test_sdk_registers_agent_against_live_gateway  SKIPPED
2 skipped
```

### Live smoke test — SDK installed from ../python-sdk: real exercise

```
$ uv pip install /Users/.../python-sdk            # pure-Python install
$ uv run pytest -m live tests/live/test_sdk_register.py -v -rxX
test_sdk_can_reach_live_gateway                PASSED
test_sdk_registers_agent_against_live_gateway  XFAIL
  (Transport gap … see AAASM-2985-sdk-transport-investigation.md)
1 passed, 1 xfailed
```

This builds `aa-gateway` from core source, runs it, configures the **real** SDK
`GatewayClient` at the fixture endpoint, and drives the genuine async
`register_agent()` — proving both the reachability floor and the transport gap.

### Default suite unaffected

```
$ uv run pytest -q
49 passed, 24 skipped, 4 deselected         # SDK uninstalled; clean env
```

### Lint

```
$ uv run ruff check tests/live/
All checks passed!
```

## Notes / caveats

- The SDK is an **optional** dependency of this repo (not in its tree); the helper
  imports it lazily and the test skips when absent — so CI without the SDK stays
  green by skipping, exactly as intended.
- Installing the SDK into the venv ships an `aasm` console script that shadows the
  runtime `aasm` expected by `tests/public/test_runtime_cli.py::test_aasm_version`
  (out of scope). The SDK was uninstalled after verification so the default test
  environment is clean.

## Conclusion

All five tasks complete. The transport gap is honestly documented and empirically
demonstrated (PASS reachability + XFAIL register), the helper and smoke test are in
place, and `live` tests are opt-in. Real SDK↔gateway registration is **blocked by a
core/SDK transport gap** — out of scope to close here, with the exact remediation
options recorded.
