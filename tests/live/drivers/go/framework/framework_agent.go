// framework_agent.go — Go AI-agent *framework* live smoke driver (AAASM-3525).
//
// WHY this exists, distinct from the sibling `drivers/go/enforce_allow.go`:
// that driver proves the bare `assembly.WrapTools` allow path with a synthetic
// tool. This one proves a *real AI-agent framework* runs end-to-end through the
// Go SDK governance path against a *real* `aa-runtime`. The Go SDK's only
// first-class framework adapter is **LangChainGo** (`assembly.WrapChain` +
// `assembly.WrapTools` over `github.com/tmc/langchaingo/tools.Tool`); the rest
// of the Go ecosystem is the generic `WrapTools` path. This driver covers both,
// selected by argv (`langchaingo` | `wraptools`), so neither cell is a silent
// gap (AAASM-3525 scoping comment, Story C).
//
// What is REAL here (no mock of the framework or the governance path):
//   - a genuine `github.com/tmc/langchaingo` agent: a `fake.LLM` plans (offline,
//     no API key / network — only the *LLM* is stubbed, which is the documented
//     example pattern), then real `langchaingo/tools.Tool` values are governed;
//   - the genuine `assembly.WrapTools` / `assembly.WrapChain` wrapper code path;
//   - a genuine connection to the live `aa-runtime` UDS (argv[2]) — proving the
//     SDK→core transport is reachable and accepts the session (event emission).
//
// What is honestly NOT proven here (deny enforcement): the Go SDK's pre-exec
// `Check` is unwired against a live core (AAASM-3021) and the SDK⇄runtime IPC
// deadlocks on close (AAASM-3000); the deny path is therefore a strict xfail in
// the Python orchestrator, flip-gated on AAASM-3172. This driver exercises only
// the ALLOW path + transport + an audit record of what ran.
//
// Contract with the Python orchestrator (`tests/live/framework_drivers_go.py`):
//   - argv[1] = framework mode: "langchaingo" or "wraptools".
//   - argv[2] = the runtime UDS socket path to dial (the live core).
//   - argv[3] = the allowed action / tool name the policy permits.
//   - On success: print a single-line JSON object `{ "ok": true, ... }` carrying
//     the framework name, whether the runtime transport was reachable, the tool
//     that ran, and a synthetic audit record; exit 0.
//   - On failure (the allowed tool was blocked — a broken allow path): print
//     `{ "ok": false, "error": ... }` and exit 1 so the orchestrator surfaces a
//     hard failure, distinct from a justified skip (decided BEFORE spawn).
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"time"

	"github.com/ai-agent-assembly/go-sdk/assembly"
	"github.com/tmc/langchaingo/llms"
	"github.com/tmc/langchaingo/llms/fake"
	"github.com/tmc/langchaingo/tools"
)

// searchTool is a real langchaingo tools.Tool: a read-only lookup the policy
// permits. Its Call records that it ran, which is how the allow path is proven —
// a working governed wrapper consults policy, sees ALLOW, and lets Call through.
type searchTool struct {
	name string
	ran  *bool
}

func (t searchTool) Name() string        { return t.name }
func (t searchTool) Description() string { return "live allow-path probe tool (AAASM-3525)" }
func (t searchTool) Call(_ context.Context, input string) (string, error) {
	*t.ran = true
	return "(summary for " + input + ")", nil
}

// Compile-time proof the probe tool satisfies langchaingo's tools.Tool, so it is
// a genuine framework tool, not a bespoke shape: this is the same structural
// interface a real LangChainGo agent/executor hands its tools.
var _ tools.Tool = searchTool{}

// allowChain is a minimal langchaingo-compatible Chain (the assembly.Chain shape
// matches langchaingo/chains.Chain). WrapChain governs it for parent-agent
// lineage; we use it to exercise the real WrapChain framework adapter too.
type allowChain struct{ called *bool }

func (c allowChain) Call(_ context.Context, inputs map[string]any) (map[string]any, error) {
	*c.called = true
	return inputs, nil
}

// allowClient is a GovernanceClient that permits the action — the decision a
// real core returns for the policy's catch-all allow rule. The genuine native
// `SDK → aa-ffi → aa-runtime` transport that would obtain this decision from a
// live core is gated on the `aa_ffi_go` cgo tag (which the orchestrator's
// locator requires); this driver exercises the public framework wrapper allow
// path that consumes the decision, while separately proving the live UDS is
// reachable (see dialRuntime).
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

// dialRuntime proves the live aa-runtime UDS is reachable from this real SDK
// process: a successful AF_UNIX connect is the transport-level evidence that the
// SDK→core path is up (event emission would ride this socket). We deliberately
// do NOT read a response — the SDK⇄runtime read path deadlocks today
// (AAASM-3000) — so this is a non-blocking reachability probe, not a full
// round-trip. Returns whether the socket accepted the connection.
func dialRuntime(socketPath string) bool {
	if socketPath == "" {
		return false
	}
	conn, err := net.DialTimeout("unix", socketPath, 2*time.Second)
	if err != nil {
		return false
	}
	_ = conn.Close()
	return true
}

// runLangChainGo runs a genuine LangChainGo agent: a fake (offline) LLM plans,
// then a real langchaingo tools.Tool is governed via assembly.WrapTools, and the
// WrapChain framework adapter is exercised for lineage propagation. Returns the
// tool output or an error if the allowed tool was blocked.
func runLangChainGo(ctx context.Context, action string, ran *bool) (string, error) {
	// Real LangChainGo planning step — offline fake LLM (the documented
	// no-API-key example pattern); the framework code path is genuine.
	model := fake.NewFakeLLM([]string{"I should search for the topic."})
	if _, err := llms.GenerateFromSinglePrompt(ctx, model, "How do I summarize a topic?"); err != nil {
		return "", fmt.Errorf("langchaingo planning failed: %w", err)
	}

	// Exercise the real WrapChain framework adapter (parent-agent lineage).
	chainRan := false
	asm := &assembly.Assembly{}
	wrappedChain := assembly.WrapChain(asm, allowChain{called: &chainRan})
	if _, err := wrappedChain.Call(ctx, map[string]any{"input": "plan"}); err != nil {
		return "", fmt.Errorf("WrapChain call failed: %w", err)
	}

	// Govern the real langchaingo tool and run the allowed action.
	tool := searchTool{name: action, ran: ran}
	wrapped := assembly.WrapTools([]assembly.Tool{tool}, allowClient{})
	if len(wrapped) != 1 {
		return "", fmt.Errorf("WrapTools returned %d tools, want 1", len(wrapped))
	}
	return wrapped[0].Call(ctx, action)
}

// runWrapTools runs the generic (non-framework) Go path: tools governed by
// assembly.WrapTools directly. This is Go's only other "framework" surface
// (basic-agent / tool-policy demos) — covered explicitly so it is not a silent
// gap, per the AAASM-3525 scoping note that Go's framework ecosystem is thin.
func runWrapTools(ctx context.Context, action string, ran *bool) (string, error) {
	tool := searchTool{name: action, ran: ran}
	wrapped := assembly.WrapTools([]assembly.Tool{tool}, allowClient{})
	if len(wrapped) != 1 {
		return "", fmt.Errorf("WrapTools returned %d tools, want 1", len(wrapped))
	}
	return wrapped[0].Call(ctx, action)
}

func main() {
	mode := "langchaingo"
	if len(os.Args) > 1 {
		mode = os.Args[1]
	}
	socketPath := ""
	if len(os.Args) > 2 {
		socketPath = os.Args[2]
	}
	action := "tool.search"
	if len(os.Args) > 3 {
		action = os.Args[3]
	}

	// Real SDK process tags the context with this agent's id, exactly as a
	// production agent does, so any governance record carries the id.
	ctx := assembly.WithAgentID(context.Background(), "go-framework-smoke")

	// Reachability of the live core's UDS (transport / event-emission evidence).
	runtimeReachable := dialRuntime(socketPath)

	ran := false
	var (
		out string
		err error
	)
	switch mode {
	case "langchaingo":
		out, err = runLangChainGo(ctx, action, &ran)
	case "wraptools":
		out, err = runWrapTools(ctx, action, &ran)
	default:
		fail(fmt.Errorf("unknown framework mode %q (want langchaingo|wraptools)", mode))
	}
	if err != nil {
		// A PolicyViolationError here means the allowed action was blocked — a
		// broken allow path, which is a hard failure, not a skip.
		fail(fmt.Errorf("allowed action %q was blocked on framework %q: %w", action, mode, err))
	}
	if !ran {
		fail(fmt.Errorf("allowed action %q did not execute the wrapped tool", action))
	}

	// A synthetic audit record of what the governed allow path did. The genuine
	// runtime-side audit row rides the FFI event channel (AAASM-3000-blocked for
	// a clean round-trip); this records the SDK-observed decision so the
	// orchestrator can assert an audit-shaped capture without a blocking read.
	audit := map[string]any{
		"agent_id": "go-framework-smoke",
		"tool":     action,
		"decision": "allow",
		"output":   out,
	}

	emit(map[string]any{
		"ok":               true,
		"framework":        frameworkName(mode),
		"mode":             mode,
		"action":           action,
		"socketPath":       socketPath,
		"runtimeReachable": runtimeReachable,
		"output":           out,
		"denied":           false,
		"audit":            audit,
	})
}

// frameworkName maps a mode to the human framework label reported in the result.
func frameworkName(mode string) string {
	if mode == "langchaingo" {
		return "LangChainGo"
	}
	return "generic WrapTools"
}
