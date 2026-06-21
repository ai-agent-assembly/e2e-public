// vercel-ai.mjs — real Vercel AI SDK agent live governance smoke driver (AAASM-3525).
//
// Builds a genuine Vercel AI SDK tool with `ai.tool(...)`, applies the SDK's
// `patchVercelAiSdk` governance hook (which wraps the `tool` factory so every
// tool's `execute` runs a pre-execution `gatewayClient.check()`), then executes
// an ALLOWED tool call. The gateway client is wired to the live aa-runtime, so
// the check is the genuine `SDK -> aa-ffi -> aa-runtime` round-trip and the tool
// only runs because the live core allowed it.
//
// Highlight functions exercised on the real path: pre-execution allow
// enforcement (the wrapped execute consults the live runtime first), event
// emission (the governance client ships a ToolCallIntercepted event over the
// UDS), and the tool actually executing under governance. Deny-path is out of
// scope here (AAASM-3000/3021 → strict xfail in the Python test, AAASM-3172).

import { pathToFileURL } from "node:url";
import { tool } from "ai";
import { z } from "zod";
import {
  ALLOWED_ACTION,
  buildLiveGatewayClient,
  fail,
  readArgs,
  succeed,
} from "../_governance.mjs";

async function main() {
  const args = readArgs("vercel-ai.mjs");
  if (!args) return;
  const { sdkNativeClientModule, socketPath } = args;

  // The SDK public surface sits at ../index.js relative to its native client.
  const sdkIndex = new URL("../index.js", pathToFileURL(sdkNativeClientModule)).href;
  const { patchVercelAiSdk } = await import(sdkIndex);

  const { gatewayClient, checks } = await buildLiveGatewayClient(
    sdkNativeClientModule,
    socketPath,
  );

  // A real Vercel AI SDK tool. Vercel tools have no `.name`; governance matches
  // by description (per the node-sdk README footgun), so the description is the
  // allowed action the live runtime evaluates.
  //
  // The live ESM namespace of `ai` is frozen (read-only `tool`), so the SDK hook
  // cannot reassign it in place. We hand it a mutable shim module carrying the
  // genuine `ai.tool` factory; the hook patches the shim's `tool`, and we build
  // the real tool through that patched factory — identical wrapping to patching
  // the module in a consumer that imports `tool` from a mutable binding.
  let executed = false;
  const aiModule = await import("ai");
  const shimModule = { tool: aiModule.tool };
  const patched = await patchVercelAiSdk({
    gatewayClient,
    fallbackRunId: "vercel-ai-smoke",
    loadModule: async () => shimModule,
  });
  if (!patched) {
    fail("patchVercelAiSdk did not patch the Vercel AI SDK module");
    return;
  }

  // Construct the tool *after* patching so the patched factory wraps its execute.
  const searchTool = shimModule.tool({
    description: ALLOWED_ACTION,
    inputSchema: z.object({ query: z.string() }),
    execute: async ({ query }) => {
      executed = true;
      return `results for ${query}`;
    },
  });

  // Run the allowed tool call through the framework's own execute path; the
  // governance wrapper runs check() against the live runtime first.
  const output = await searchTool.execute(
    { query: "agent governance" },
    { toolCallId: "call-1", messages: [] },
  );

  if (!executed) {
    fail("Vercel AI tool execute did not run after an allowed governance check");
    return;
  }
  if (checks.length === 0) {
    fail("no governance check ran on the live path for the Vercel AI tool call");
    return;
  }
  const denied = checks.some((c) => c.verdict.denied);

  succeed({
    framework: "vercel-ai",
    action: ALLOWED_ACTION,
    checks: checks.length,
    denied,
    executed,
    output: String(output),
  });
}

try {
  await main();
} catch (error) {
  fail(error);
}
