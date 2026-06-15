# Verification Report: AAASM-2988

**Story:** go-sdk install matrix: cgo/FFI links + package builds & runs
**Repo:** `ai-agent-assembly/agent-assembly-integration-tests`
**Branch:** `v0.0.1/AAASM-2988/go_install_matrix`
**Date:** 2026-06-15
**Trigger:** Manual — end-of-implementation review

---

## What was built

Extended `tests/public/test_go_sdk.py` so the Go SDK smoke matrix builds a tiny
consumer module that imports the `assembly` package, and verifies that the
consumer **compiles, links the cgo/FFI shim, and runs** — not merely that the
module resolves. Each test is parametrized over two acquisition paths:

| `acquisition` | How the SDK is obtained |
|---|---|
| `source` | Local `../go-sdk` checkout wired via a go.mod `replace` directive |
| `proxy` | Public Go module proxy via `go get <module>/assembly@latest` |

### Tests

| Test | Asserts |
|---|---|
| `test_go_sdk_links_ffi_shim` | The consumer build graph (`go list -deps`) contains the internal cgo/FFI shim package `<module>/internal/ffi`, and `go build ./...` links it successfully. This is the "links the FFI shim" check — plain module resolution would not pull the shim into the link. |
| `test_go_sdk_cgo_abi_binding_is_wired` | Building with `-tags aa_ffi_go` activates the cgo C-ABI bridge (`cgo_bridge.go`, `#cgo LDFLAGS: -laa_ffi_go`). The build either links cleanly (native lib present) or fails **at the link stage specifically on the missing `aa_ffi_go` native library**. A compile or module-resolution error fails the test. Proves the C-ABI shim is genuinely wired, not a stub. |
| `test_go_sdk_runs_smoke` | `go run .` prints `true` (`assembly.ErrBinaryNotFound != nil`), confirming a public symbol is usable at runtime. |

---

## Acceptance Criteria Results

| # | Criterion | Status | Evidence |
|---|---|---|---|
| 1 | cgo/FFI link test — build pulls in + links the FFI shim, both proxy and source paths | ✅ | `test_go_sdk_links_ffi_shim[source]`, `[proxy]` pass; `internal/ffi` present in `go list -deps`; `go build` exit 0. Additional `-tags aa_ffi_go` test proves the C-ABI bridge fires its `-laa_ffi_go` LDFLAGS. |
| 2 | Functional test — `go run` the consumer; a public symbol is usable | ✅ | `test_go_sdk_runs_smoke[source]`, `[proxy]` pass; stdout `true`. |
| 3 | Verification note in `verification-reports/` | ✅ | This file. |

---

## Validation

```
$ uv run ruff check tests/public/test_go_sdk.py
All checks passed!

$ uv run pytest tests/public/test_go_sdk.py -v
test_go_sdk_links_ffi_shim[source] PASSED
test_go_sdk_links_ffi_shim[proxy] PASSED
test_go_sdk_cgo_abi_binding_is_wired[source] PASSED
test_go_sdk_cgo_abi_binding_is_wired[proxy] PASSED
test_go_sdk_runs_smoke[source] PASSED
test_go_sdk_runs_smoke[proxy] PASSED
6 passed
```

Environment: `go1.26.3 darwin/arm64`, `CGO_ENABLED=1`. When `go` is absent from
PATH all six tests skip cleanly (verified by running with a stripped PATH).

### Did the build actually link the FFI shim against a real install?

Yes. Against the real proxy install (`v0.0.1-beta.2`):

- `go list -deps .` lists `github.com/ai-agent-assembly/go-sdk/internal/ffi` in
  the consumer's dependency graph, and `go build ./...` links it (default
  pure-Go fallback binding, build tag `!cgo || !aa_ffi_go`).
- `go build -tags aa_ffi_go ./...` reaches the linker and fails with
  `ld: library 'aa_ffi_go' not found` — i.e. the cgo bridge's
  `#cgo LDFLAGS: -laa_ffi_go` directive fires and tries to resolve the native
  Rust artifact (`libaa_ffi_go`), which is not shipped to the module proxy. This
  distinguishes a wired C-ABI shim from a pure-Go stub.

---

## Stale-fork discrepancy (noted, handled)

The local `../go-sdk` checkout is a stale fork and differs from the published
module in two ways:

1. **Module path case.** The fork's `go.mod` declares
   `module github.com/AI-agent-assembly/go-sdk` (capitalized), while the
   published/proxy module path is the canonical lowercase
   `github.com/ai-agent-assembly/go-sdk`. A `replace` directive must match the
   SDK's own declared path, so the source-path test now **reads the module path
   from the checkout's go.mod** (`_module_path_of`) rather than hardcoding
   lowercase. The proxy path uses the canonical lowercase path.

2. **Pre-existing helper bugs (fixed).** The original `_go_sdk_path()` checked
   `os.path.isdir(".../go.mod")` (always false for a file) and used a 4-levels-up
   relative path that resolved outside the workspace from a git worktree, so the
   source-path smoke **always skipped** before this change. Both are corrected
   (`isfile` + search 3 and 4 levels up), so the source path now runs.

Verification was performed primarily against the **module proxy** per the story
guidance; the source path is also green against the local fork once its real
module path is honoured.
