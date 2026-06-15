# Verification Report: AAASM-2992

**Story:** go-sdk without-core behavioral: fail-open default + WithFailClosed
**Date:** 2026-06-15
**Trigger:** Manual — end-of-implementation AC review

---

## Refs Verified

| Item | Value |
|---|---|
| Story | AAASM-2992 |
| Repo | `ai-agent-assembly/agent-assembly-integration-tests` |
| Branch | `v0.0.1/AAASM-2992/go_without_core` |
| Files touched | `tests/behavioral/__init__.py`, `tests/behavioral/test_go_without_core.py` |

---

## What was built

A new behavioral test module that asserts the Go SDK's **designed client-side
behavior when no governance gateway is reachable**, including the explicit
fail-closed opt-in. No gateway is started.

Each cell builds and runs a tiny Go consumer module (mirroring the
consumer-build pattern in `tests/public/test_go_sdk.py`) across two acquisition
paths — `proxy` (canonical published module from the Go module proxy) and
`source` (local checkout via `replace`). The consumer wraps a governed tool via
the public `assembly.WrapTools` / `GovernanceClient` surface with a client whose
`Check` returns a connection error — a faithful, deterministic stand-in for "no
gateway reachable" that exercises the exact branch in `assembly/tool_wrapper.go`
that keys off the check error.

| Test | Cell | Asserted outcome |
|---|---|---|
| `test_enforce_no_gateway_default_fails_open` | enforce, no gateway, **default** | Governed action **proceeds, no error** (output `ran:payload`). Fail-open default. |
| `test_enforce_no_gateway_fail_closed_denies` | enforce, no gateway, **`WithFailClosed(true)`** | Governed action **errors / denied**; the tool does NOT execute. |
| `test_non_enforce_no_gateway_proceeds` (observe) | observe, no gateway | Governed action **proceeds**. |
| `test_non_enforce_no_gateway_proceeds` (disabled) | disabled, no gateway | Governed action **proceeds**. |

Each is parametrized over `["source", "proxy"]` (and the non-enforce test also
over `["observe", "disabled"]`), for 8 collected tests total. All use the
existing `@pytest.mark.sdk` marker — no new marker was introduced.

---

## Source-of-truth: where the behavior is defined

Read directly from the go-sdk `assembly` package:

- `defaults.go` — `defaultRuntimeOptions()` sets `failClosed: false` → fail-open
  is the default.
- `options.go` — `WithFailClosed(true)` is the single explicit opt-in that flips
  the switch; doc-comment states the default proceeds even if the check fails.
- `tool_wrapper.go` — `AssemblyTool.Call`: when `client.Check` returns `err != nil`,
  `if t.opts.failClosed { return "", … }` (deny) **else** falls through and runs
  `t.inner.Call` (proceed). This is the decisive branch an unreachable gateway hits.
- `enforcement_mode.go` / `init_bridge.go` — `WithEnforcementMode` (enforce /
  observe / disabled) is a **registration-time wire field** (`enforcement_mode`
  JSON) only; it does **not** gate the local tool-wrapper loop. Consequently
  observe/disabled share the same fail-open default path with no gateway, which
  is why those cells assert "proceeds".

---

## Acceptance Criteria Results

| AC | Result |
|---|---|
| `enforce` + no gateway + default → proceeds, no error | PASS (`ran:payload`, no error) — both source & proxy |
| `enforce` + no gateway + `WithFailClosed(true)` → errors/denied | PASS (error, tool not executed) — both source & proxy |
| `observe` / `disabled` + no gateway → proceeds | PASS — both source & proxy |
| Consumer shells out to `go`, builds a tiny consumer | PASS — `go run` per cell |
| SKIP when `go` absent | PASS — verified with stripped `PATH` (8 skipped) |
| No gateway started | PASS — no gateway process anywhere in the suite |

---

## Test run

```
uv run pytest tests/behavioral -v
8 passed in 8.16s
```

`go` present (go1.26.3 darwin/arm64). With `PATH` stripped of `go`: 8 skipped,
confirming the `skip_if_binary_missing("go")` gate.

`uv run ruff check tests/behavioral/` → All checks passed.
`uv run ruff format tests/behavioral/` → clean.

---

## Stale-fork notes

- The local `../go-sdk` checkout is a **stale fork**: its `go.mod` declares the
  **capitalized** module path `github.com/AI-agent-assembly/go-sdk` (and
  `go 1.26.0`). The canonical published module on the Go module proxy is
  **lowercase** `github.com/ai-agent-assembly/go-sdk`, currently
  `v0.0.1-beta.2`.
- The test honours each checkout's declared module path (reads the `module`
  directive from `go.mod`) for the `replace` directive, and uses the canonical
  lowercase path for the proxy acquisition — matching the approach already used
  in `tests/public/test_go_sdk.py`.
- Both acquisition paths produce **identical** behavior across all four cells,
  so the stale-fork capitalization does not affect the asserted governance
  semantics.

---

## Notes / honest caveats

- The "no gateway reachable" condition is modelled by a `GovernanceClient.Check`
  that returns a connection error rather than by booting and then killing a real
  gateway. This is deterministic and exercises the same `tool_wrapper.go` branch
  an unreachable gateway triggers; it is the achievable, faithful level given the
  public API surface (`WrapTools(tools, client, options...)` takes the client
  directly). The branch under test is purely client-side and depends only on the
  check returning an error, which an unreachable gateway always produces.

---

## Conclusion

All acceptance criteria are met. The Go SDK's fail-open default and its single
explicit `WithFailClosed(true)` fail-closed opt-in are asserted against both the
canonical proxy module and the local source fork, with clean SKIP when `go` is
absent and no gateway started.
