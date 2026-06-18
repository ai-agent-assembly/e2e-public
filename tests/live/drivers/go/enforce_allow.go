// enforce_allow.go — Go SDK live allow-path driver (AAASM-3194).
//
// WHY this exists: the integration repo's live harness drives the *Python* SDK
// in-process via its importable `_core` extension, but the Go SDK is reached
// only through its own toolchain. This tiny program is the Go analogue of the
// Python allow path in `test_e2e_python.py::test_python_allow_path_event_session`:
// it exercises the genuine `github.com/AI-agent-assembly/go-sdk/assembly`
// governed-tool wrapper for an action the policy ALLOWS, and proves the wrapped
// tool actually executes (the allow decision lets the call through) — the real
// SDK code path, not a stub.
//
// Contract with the Python wrapper (`tests/live/sdk_drivers.py`):
//   * argv[1] = the runtime UDS socket path to associate the session with
//     (informational here; the Go FFI transport that dials it is only linked
//     under the `aa_ffi_go` cgo build tag, which the wrapper gates on — see the
//     wrapper's go-driver locator).
//   * argv[2] = the allowed action / tool name the policy permits.
//   * On success: print a single-line JSON object `{ "ok": true, ... }` to
//     stdout and exit 0.
//   * On failure (the allowed tool was blocked, i.e. the allow path is broken):
//     print `{ "ok": false, "error": ... }` and exit 1 so the wrapper surfaces
//     it as a hard failure, distinct from a justified skip (which the wrapper
//     decides BEFORE ever spawning this driver).
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"

	"github.com/AI-agent-assembly/go-sdk/assembly"
)

// allowTool is a minimal tool whose Call records that it ran. The allow path is
// proven by observing this execution: a working governed wrapper consults the
// policy, sees ALLOW, and lets the underlying Call through.
type allowTool struct {
	name string
	ran  *bool
}

func (t allowTool) Name() string        { return t.name }
func (t allowTool) Description() string  { return "live allow-path probe tool (AAASM-3194)" }

func (t allowTool) Call(_ context.Context, input string) (string, error) {
	*t.ran = true
	return "ok:" + input, nil
}

// allowClient is a GovernanceClient that permits the action — the decision a
// real core returns for the policy's catch-all allow rule. The genuine
// SDK->aa-ffi->aa-runtime transport that would obtain this from a live core is
// only linked under the `aa_ffi_go` cgo tag; this driver exercises the public
// wrapper allow path that consumes that decision.
type allowClient struct{}

func (allowClient) Check(context.Context, assembly.CheckRequest) (assembly.Decision, error) {
	return assembly.Decision{Denied: false}, nil
}

func (allowClient) WaitForApproval(context.Context, assembly.ApprovalRequest) (assembly.Decision, error) {
	return assembly.Decision{Denied: false}, nil
}

func (allowClient) RecordResult(context.Context, assembly.RecordRequest) error { return nil }

func (allowClient) Close() error { return nil }

func emit(v any) {
	b, _ := json.Marshal(v)
	fmt.Println(string(b))
}

func fail(err error) {
	emit(map[string]any{"ok": false, "error": err.Error()})
	os.Exit(1)
}

func main() {
	socketPath := ""
	if len(os.Args) > 1 {
		socketPath = os.Args[1]
	}
	action := "tool.search"
	if len(os.Args) > 2 {
		action = os.Args[2]
	}

	ran := false
	tool := allowTool{name: action, ran: &ran}

	wrapped := assembly.WrapTools([]assembly.Tool{tool}, allowClient{})
	if len(wrapped) != 1 {
		fail(fmt.Errorf("WrapTools returned %d tools, want 1", len(wrapped)))
	}

	out, err := wrapped[0].Call(context.Background(), action)
	if err != nil {
		// A PolicyViolationError here means the allowed action was blocked — a
		// broken allow path, which is a hard failure, not a skip.
		fail(fmt.Errorf("allowed action %q was blocked: %w", action, err))
	}
	if !ran {
		fail(fmt.Errorf("allowed action %q did not execute the wrapped tool", action))
	}

	emit(map[string]any{
		"ok":         true,
		"action":     action,
		"socketPath": socketPath,
		"output":     out,
		"denied":     false,
	})
}
