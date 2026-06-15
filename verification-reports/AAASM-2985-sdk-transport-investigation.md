# AAASM-2985 — Transport investigation: wiring a Python SDK to the live core

**Date:** 2026-06-15
**Branch:** `v0.0.1/AAASM-2985/sdk_transport_wiring`
**Repo:** `agent-assembly-integration-tests`

## Question

Story AAASM-2976 added a `live_gateway` fixture that builds and runs `aa-gateway`
from source and yields a `LiveGateway` handle (`tests/live/`). This story asks:
can a real Python SDK register an agent against that live gateway, and make such
live tests opt-in?

## TL;DR — there is a real transport gap; registration cannot succeed today

A Python SDK **cannot** register an agent against a running `aa-gateway` as the
pieces stand today. The SDK speaks **HTTP/REST**; the runnable gateway either
speaks **gRPC only** (the mode the fixture uses) or serves an **HTTP surface that
does not mount the SDK's REST routes**. The REST routes the SDK calls live in a
**library-only crate with no binary**. No process exists that the Python SDK can
talk to for `/agents/{id}/register`.

This note records the evidence so the gap is documented rather than faked. The
smoke test added by this story (`tests/live/test_sdk_register.py`) **xfails /
skips** on the registration step instead of pretending it passes.

## Evidence

### 1. The Python SDK speaks HTTP/REST only

`python-sdk/agent_assembly/client/gateway.py` — `GatewayClient` is built on
`httpx.Client` and registers by POSTing to a REST path:

```python
self._client = httpx.Client(base_url=self.gateway_url, ...)
...
response = self.client.post(f"/agents/{self.agent_id}/register", json=body)
```

The resolver (`python-sdk/agent_assembly/core/gateway_resolver.py`) defaults to
`DEFAULT_GATEWAY_URL = "http://localhost:7391"`, honours env `AAASM_GATEWAY_URL`
(and `AAASM_API_KEY`), and probes readiness with `GET {url}/healthz`. There is no
gRPC client anywhere in the Python SDK.

### 2. The `live_gateway` fixture runs `aa-gateway` in `legacy-grpc` mode — gRPC only

`tests/live/gateway.py` launches the binary as
`aa-gateway --policy <p> --listen 127.0.0.1:<port> --audit-dir <d>`. With no
`AA_MODE` set, `aa-gateway/src/main.rs` defaults to `Mode::LegacyGrpc`, whose
`serve_tcp` builds a **tonic** `Server` and adds only gRPC services
(`PolicyServiceServer`, `AuditServiceServer`, `AgentLifecycleServiceServer`,
`TopologyServiceServer`, …). There is **no HTTP listener** in this mode, so the
fixture's port answers gRPC, not REST. The fixture's readiness check is a raw TCP
`connect`, which a gRPC listener satisfies — it does not prove an HTTP server.

### 3. The gateway's HTTP mode (`local`) does not mount the SDK's REST routes

`aa-gateway` also has a `local` mode (`aa-gateway/src/local_mode.rs`) that runs an
**axum** HTTP server on port 7391 (the SDK default). But its router mounts only:

- `GET /healthz`
- `GET /api/v1/admin/status` (when storage is present)
- the dashboard SPA (when `dashboard/dist/` exists)

It does **not** mount `/agents/{id}/register`, `/agents/{id}/policy/check`,
`/dispatch_tool`, or `/topology/edges` — the endpoints the SDK actually calls.
So even pointing the SDK at a `local`-mode gateway, `register_agent()` would
404.

### 4. The SDK's REST routes live in `aa-api`, which has no binary

The REST endpoints the SDK targets are implemented in the **`aa-api`** crate
(`aa-api/src/routes/`). `aa-api/Cargo.toml` declares **zero `[[bin]]` targets**
(its only bins are codegen helpers: `generate_openapi.rs`,
`generate_policy_rbac_doc.rs`). `aa-api` is a **library** — nothing in the
shipped product starts an HTTP server that mounts these routes. There is no
runnable HTTP+REST front door for the SDK to reach.

## Why I did not "minimally extend the fixture" to close this

The fixture extension the task allows is meant for the case where the gateway can
serve HTTP with a flag. It can't: the SDK's REST routes are not served by **any**
runnable gateway binary. Closing the gap would require either:

- giving `aa-api` a runnable binary (or having `aa-gateway` mount `aa-api`'s
  router) — a **core change in `../agent-assembly`**, out of scope for this
  test repo and outside this story's file scope; or
- adding a gRPC client to the Python SDK — a **`../python-sdk` change**, also
  out of scope.

Faking a passing registration (e.g. stubbing an HTTP server in the test) was
explicitly disallowed and would hide the gap, so I did not.

### Empirical confirmation

Installing the real Python SDK from `../python-sdk` and running the live smoke
test against the running fixture gateway reproduces the gap concretely:

- `test_sdk_can_reach_live_gateway` — **PASSED**: the real SDK `GatewayClient`
  is configured at `http://127.0.0.1:<port>` and the gateway accepts the TCP
  connection.
- `test_sdk_registers_agent_against_live_gateway` — **XFAIL**: the SDK's HTTP/1.1
  `POST /agents/{id}/register` against the gRPC (HTTP/2) listener fails with
  `httpcore.RemoteProtocolError: illegal request line` (wrapped by the SDK as
  `GatewayError`). The gRPC server rejects the HTTP/1.1 request line — a direct,
  observable symptom of the transport mismatch, not a contrived failure.

## What this story delivers

1. This investigation note (the documented gap).
2. `tests/live/sdk_client.py` — a helper that installs/points the Python SDK at a
   `LiveGateway` (sets `AAASM_GATEWAY_URL` to the fixture endpoint, builds a
   `GatewayClient`). Ready to use the moment a REST front door exists.
3. `tests/live/test_sdk_register.py` — a `live`-marked smoke test that:
   - skips cleanly if the Python SDK / toolchain is unavailable;
   - proves the live gateway is reachable on its port;
   - attempts a real SDK registration and **`xfail`s** it against the documented
     transport gap (never a false green).
4. `pyproject.toml` `addopts = "-m 'not live'"` so `live` tests are opt-in.

## Follow-up needed to make real registration pass (core/SDK work, separate tickets)

- **Option A (core):** ship a runnable HTTP server that mounts `aa-api`'s router
  (either an `aa-api` binary, or have `aa-gateway` `local` mode merge the
  `aa-api` router). Then the fixture launches that mode and the SDK's existing
  HTTP path works unchanged.
- **Option B (SDK):** add a gRPC transport to the Python SDK so it can talk to
  the `legacy-grpc` gateway the fixture already runs.

Once either lands, flip the `xfail` in `test_sdk_register.py` to a hard assert.
