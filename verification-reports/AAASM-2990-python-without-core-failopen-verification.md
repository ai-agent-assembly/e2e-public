# AAASM-2990 — python-sdk without-core behavioral: fail-open per enforcement mode

## Goal

Assert the python-sdk's **designed** behaviour when **no core / gateway is
reachable** — the fail-open security contract. No gateway is started; tests
SKIP cleanly when the SDK (`agent_assembly`) is not installed.

## What was added

- `tests/behavioral/__init__.py` — new behavioral test package.
- `tests/behavioral/test_python_without_core.py` — 4 tests (marker: `sdk`).

No other files touched (no `pyproject.toml`, no new marker, no `tests/live/**`).

## What fail-open behaviour was asserted, and how

The fail-open contract is "a governed action proceeds when governance is
unreachable". In the python-sdk that decision is made at the
`init_assembly(...)` boundary, not at the per-action RPC. So a **governed
session** is invoked via:

```python
init_assembly(
    gateway_url="http://127.0.0.1:<dead-port>",  # nothing listening
    agent_id="failopen-<mode>",
    mode="sdk-only",                              # hermetic, no eBPF/proxy
    enforcement_mode=<mode>,
)
```

The "no core" condition is made deterministic by binding an ephemeral port,
releasing it, and pointing the SDK at that valid-but-closed address (any
connect is refused). `AAASM_GATEWAY_URL` / `AAASM_API_KEY` are cleared so the
resolver cannot discover another endpoint.

| Cell | Test | Asserted behaviour |
|---|---|---|
| `enforce`, no gateway | `test_enforce_mode_proceeds_without_gateway` | `init_assembly` returns a live, non-shutdown `AssemblyContext` **without raising** → agent proceeds |
| `observe`, no gateway | `test_observe_mode_proceeds_without_gateway` | same — proceeds |
| `disabled`, no gateway | `test_disabled_mode_proceeds_without_gateway` | same — proceeds (no-op) |
| boundary doc | `test_explicit_policy_rpc_is_transport_not_failopen` | `GatewayClient.check_policy_compliance` against a dead gateway raises `GatewayError` (transport), asserted with `pytest.raises` |

Each fail-open test also asserts the requested posture is recorded on the
client (`context.client.enforcement_mode == <mode>`), proving the mode was
actually applied — not silently dropped.

## Honesty note (no faking)

`init_assembly(mode="sdk-only", gateway_url=…)` constructs a **lazy**
`GatewayClient` (no socket opened) and registers framework adapters; it makes
**no** registration network call, so it succeeds with no gateway — this *is*
the fail-open path, observed directly. The explicit per-action RPC
(`check_policy_compliance`) is a transport call and **does** raise against a
dead endpoint; rather than pretend it returns an allow, the 4th test documents
that boundary with a `pytest.raises(GatewayError)`. Nothing is mocked or
stubbed — the real installed SDK code path is exercised.

## Validation (local, macOS, Python 3.13)

- `uv run ruff check tests/behavioral` → **All checks passed**
- `uv run pytest tests/behavioral -v` **with SDK installed** (from `../python-sdk`, pure-Python) → **4 passed**
- `uv run pytest tests/behavioral -v` **with SDK absent** → **4 skipped** (clean skip path confirmed)

The native `_core` extension is not required for these tests — they use only
the pure-Python `init_assembly` / `GatewayClient` surface, so the pure-Python
install exercises the run path.

## Blockers

None.
