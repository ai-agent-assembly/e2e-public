// enforce_allow.mjs — Node SDK live allow-path driver (AAASM-3194).
//
// WHY this exists: the integration repo's live harness drives the *Python* SDK
// in-process via its importable `_core` extension, but the Node SDK is reached
// only through its own toolchain. This tiny driver is the Node analogue of the
// Python allow path in `test_e2e_python.py::test_python_allow_path_event_session`:
// it opens the genuine `@agent-assembly/sdk` native client over the live
// `aa-runtime` UDS and ships ONE allowed-action governance event — the real
// `SDK -> aa-ffi -> aa-runtime` transport, not a stub.
//
// Contract with the Python wrapper (`tests/live/sdk_drivers.py`):
//   * argv[2] = absolute path to the SDK's compiled native-client module
//     (`dist/esm/native/client.js`). The wrapper locates the SDK checkout and
//     passes it explicitly so this driver does not hard-code a layout; the
//     wrapper also runs us with cwd = the SDK root so the native binding
//     (`native/aa-ffi-node/index.cjs`) resolves the way the SDK loads it.
//   * argv[3] = the runtime UDS socket path to connect to.
//   * argv[4] = the allowed action name (informational; the runtime accepts the
//     event — server-side policy authority decides, the SDK is not a policy
//     authority).
//   * On success: print a single-line JSON object `{ "ok": true, ... }` to
//     stdout and exit 0.
//   * On a connect/transport failure: print `{ "ok": false, "error": ... }` and
//     exit 1 so the wrapper can surface it as a hard failure (a broken allow
//     path), distinct from a justified skip (which the wrapper decides *before*
//     ever spawning this driver).
//
// WHY no close(): the SDK's `close()` joins the IPC thread, which deadlocks
// against a real runtime today (AAASM-3000). The Python allow path deliberately
// does not assert clean close for the same reason; we mirror that here — connect
// + ship + confirm the session, then exit without close() so the allow path
// stays green where the transport is reachable.

function fail(error) {
  process.stdout.write(JSON.stringify({ ok: false, error: String(error) }) + "\n");
  process.exit(1);
}

async function main() {
  const nativeClientModule = process.argv[2];
  const socketPath = process.argv[3];
  const action = process.argv[4] ?? "tool.search";
  if (!nativeClientModule || !socketPath) {
    fail("usage: enforce_allow.mjs <native-client-module> <socket-path> <allowed-action>");
    return;
  }

  const { createNativeClient } = await import(nativeClientModule);

  // napi-inprocess mode is the only mode whose native client actually dials the
  // UDS; the default grpc-sidecar mode is a no-op shim. `gateway` carries the
  // UDS path for this mode (see the SDK's native/client.ts).
  const client = createNativeClient({ gateway: socketPath, mode: "napi-inprocess" });

  // Ship one permitted-action event. The native sendEvent is fire-and-forget and
  // connects lazily, so a transport error is not raised synchronously here.
  client.sendEvent({
    event_type: "ToolCallIntercepted",
    action,
    payload: JSON.stringify({ action, driver: "node-allow" }),
  });

  // queryPolicy awaits the connection handle, surfacing any connect error, then
  // resolves neutral without a runtime round-trip — so it confirms the genuine
  // session was established without triggering the close() deadlock.
  const decision = await client.queryPolicy({ action });

  process.stdout.write(
    JSON.stringify({
      ok: true,
      mode: client.mode,
      action,
      socketPath,
      denied: decision.denied === true,
    }) + "\n",
  );
  // Intentionally exit without close() — see the module header (AAASM-3000).
  process.exit(0);
}

main().catch(fail);
