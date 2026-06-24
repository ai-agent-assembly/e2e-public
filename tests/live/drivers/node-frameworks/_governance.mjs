// _governance.mjs — shared real-governance harness for the Node framework
// smoke drivers (AAASM-3525).
//
// WHY this exists: each per-framework driver (langchain.mjs, vercel-ai.mjs, …)
// builds a *genuine* agent on its framework, but they all need the same thing —
// a real `@agent-assembly/sdk` governance client wired to the *live* `aa-runtime`
// over its UDS, exercising the production `SDK -> aa-ffi -> aa-runtime` path
// rather than a stub. This module supplies that one piece so the drivers stay
// framework-only.
//
// Contract with the Python orchestrator (`tests/live/node_frameworks.py`):
//   * The orchestrator runs a driver with `cwd = this fixture dir` so the
//     framework packages resolve from the fixture's own `node_modules` AND the
//     SDK native binding resolves via the fixture's `native/aa-ffi-node` symlink
//     (the loader's `${cwd}/native/aa-ffi-node/index.cjs` candidate).
//   * argv[2] = absolute path to the SDK's compiled native-client module
//     (`dist/esm/native/client.js`) — the genuine SDK native client.
//   * argv[3] = the live runtime UDS socket path.
//   * On success a driver prints ONE line of JSON `{ "ok": true, ... }` and
//     exits 0; on any failure `{ "ok": false, "error": ... }` and exits 1 so the
//     orchestrator surfaces it as a hard failure (a broken allow path), distinct
//     from a justified skip the orchestrator decides *before* spawning a driver.
//
// WHY a local GatewayClient adapter instead of the SDK's `createNativeGatewayClient`:
// the node-sdk checkout is read-only for this work and its *published/built* dist
// exposes only the native client primitive (`queryPolicy`/`sendEvent`) — the
// `createNativeGatewayClient` mapper lives in `src/` and is not in every built
// dist. So we replicate that thin map here over the dist's native client, which
// is the genuine UDS transport. `queryPolicy` connects to the live runtime
// (surfacing any transport error) before resolving — i.e. the real session is
// established — and `sendEvent` ships a real governance event over the socket.
//
// WHY allow-path only here: the live deny/block path is unprovable today
// (AAASM-3000 IPC deadlock + AAASM-3021 pre-exec check() unwired); the SDK's
// native client fails open / defers the decision server-side, so a denied action
// is not refused at the SDK layer. The deny assertion is a strict xfail in the
// Python test, pinned on AAASM-3172. These drivers therefore drive an ALLOWED
// tool call and assert the real governance path RAN against the live core (a
// connected session + an emitted event + the pre-exec check) and the tool
// executed — never that a deny was enforced.

/** The allowed action name the live runtime evaluates (policy-disabled runtime → allow). */
export const ALLOWED_ACTION = "tool.search";

/**
 * Build a `GatewayClient`-shaped governance client wired to the live runtime.
 *
 * Loads the SDK's compiled native client (by the absolute path the orchestrator
 * passes) in `napi-inprocess` mode — the only mode whose native client actually
 * dials the runtime UDS — then adapts its `queryPolicy`/`sendEvent` primitives
 * onto the `{ check, record }` surface the framework hooks consume, mapping a
 * verdict exactly as the SDK's own `createNativeGatewayClient` does
 * (deny→denied, pending→pending, else allow; fail-open on a local fault). A
 * framework hook's `gatewayClient.check()` therefore runs the genuine
 * connect-and-query round-trip to the live core.
 *
 * @param {string} sdkNativeClientModule absolute path to dist/esm/native/client.js
 * @param {string} socketPath live aa-runtime UDS path
 * @returns {Promise<{ gatewayClient: object, nativeClient: object, checks: Array<object> }>}
 *   `checks` records every governance verdict observed, so a driver can assert
 *   the pre-execution check actually ran on the live path.
 */
export async function buildLiveGatewayClient(sdkNativeClientModule, socketPath) {
  const nativeMod = await import(sdkNativeClientModule);
  const nativeClient = nativeMod.createNativeClient({
    gateway: socketPath,
    mode: "napi-inprocess",
  });

  const checks = [];

  const gatewayClient = {
    mode: "sdk-only",
    start: async () => undefined,
    // Do NOT close(): close() joins the IPC thread which deadlocks against a
    // real runtime today (AAASM-3000), exactly as the repo's existing
    // enforce_allow.mjs allow path documents. The driver connects, runs, reports
    // and exits without close().
    close: async () => undefined,
    check: async (request) => {
      // Emit a real governance event for this tool call over the live UDS, then
      // run the genuine queryPolicy round-trip. Any transport fault fails open
      // (the SDK is advisory, not a security boundary) — mirrors the SDK source.
      let verdict;
      try {
        nativeClient.sendEvent({
          event_type: "ToolCallIntercepted",
          action: request.action ?? "tool_call",
          payload: JSON.stringify({
            tool_name: request.toolName,
            args: request.args,
            run_id: request.runId,
          }),
        });
        const raw = await nativeClient.queryPolicy({
          agent_id: "",
          action_type: request.action ?? "tool_call",
          ...(request.toolName === undefined ? {} : { tool_name: request.toolName }),
          ...(request.args === undefined ? {} : { args: request.args }),
        });
        verdict = {
          denied: raw.denied ?? false,
          pending: raw.pending ?? false,
          ...(raw.reason === undefined ? {} : { reason: raw.reason }),
        };
      } catch {
        verdict = { denied: false, pending: false };
      }
      checks.push({ toolName: request.toolName, verdict });
      return verdict;
    },
    waitForApproval: async () => ({ denied: false }),
    record: async () => undefined,
    recordResult: async () => undefined,
    scanPrompts: async () => undefined,
  };

  return { gatewayClient, nativeClient, checks };
}

/**
 * Emit the single-line success result and exit 0.
 *
 * @param {object} extra framework-specific fields merged into the result
 */
export function succeed(extra) {
  process.stdout.write(JSON.stringify({ ok: true, ...extra }) + "\n");
  // See buildLiveGatewayClient: intentionally exit without close() (AAASM-3000).
  process.exit(0);
}

/** Emit the single-line failure result and exit 1 (a broken allow path). */
export function fail(error) {
  process.stdout.write(
    JSON.stringify({ ok: false, error: String(error?.stack ?? error) }) + "\n",
  );
  process.exit(1);
}

/** Read the two required argv positions, or fail with a usage message. */
export function readArgs(driverName) {
  const sdkNativeClientModule = process.argv[2];
  const socketPath = process.argv[3];
  if (!sdkNativeClientModule || !socketPath) {
    fail(`usage: ${driverName} <sdk-native-client-module> <socket-path>`);
    return undefined;
  }
  return { sdkNativeClientModule, socketPath };
}
