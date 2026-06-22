// mastra.mjs — real Mastra agent live governance smoke driver (AAASM-3525).
//
// Builds a genuine Mastra tool with `@mastra/core/tools` `createTool(...)` and
// wraps it with the public `withAssembly` — which performs TRUE pre-execution
// governance on the tool's `execute` (the SDK's `patchMastra` hook only adds
// lineage on `Agent.generate`/`Workflow.execute`, not tool-level deny; the
// enforcing path for a Mastra tool is the wrapper). It then runs an ALLOWED tool
// call. The gateway client is wired to the live aa-runtime, so the pre-exec
// `check()` is the genuine `SDK -> aa-ffi -> aa-runtime` round-trip and the tool
// runs because the live core allowed it. `patchMastra` is also applied to
// exercise the framework-specific lineage hook.
//
// Highlight functions on the real path: pre-execution allow enforcement on the
// Mastra tool + event emission over the UDS + the tool actually executing under
// governance. Deny-path is out of scope (AAASM-3000/3021 → strict xfail,
// AAASM-3172).

import { pathToFileURL } from "node:url";
import { createTool } from "@mastra/core/tools";
import { z } from "zod";
import {
  ALLOWED_ACTION,
  buildLiveGatewayClient,
  fail,
  readArgs,
  succeed,
} from "../_governance.mjs";

async function main() {
  const args = readArgs("mastra.mjs");
  if (!args) return;
  const { sdkNativeClientModule, socketPath } = args;

  const sdkIndex = new URL("../index.js", pathToFileURL(sdkNativeClientModule)).href;
  const { withAssembly, patchMastra } = await import(sdkIndex);

  const { gatewayClient, checks } = await buildLiveGatewayClient(
    sdkNativeClientModule,
    socketPath,
  );

  // Apply the Mastra-specific lineage hook against the real module. It returns
  // false if Agent.generate is absent in this build; that does not gate the
  // tool-level governance the wrapper provides, so we proceed either way and
  // report whether it patched.
  const mastraCore = await import("@mastra/core");
  const lineagePatched = await patchMastra({
    agentId: "mastra-smoke",
    loadModule: async () => mastraCore,
  });

  let executed = false;
  const searchTool = createTool({
    id: ALLOWED_ACTION,
    description: "search the corpus",
    inputSchema: z.object({ query: z.string() }),
    execute: async ({ context }) => {
      executed = true;
      return `results for ${context.query}`;
    },
  });

  const governed = withAssembly({ [ALLOWED_ACTION]: searchTool }, { gatewayClient });
  const output = await governed[ALLOWED_ACTION].execute({
    context: { query: "agent governance" },
  });

  if (!executed) {
    fail("Mastra tool execute did not run after an allowed governance check");
    return;
  }
  if (checks.length === 0) {
    fail("no governance check ran on the live path for the Mastra tool call");
    return;
  }
  const denied = checks.some((c) => c.verdict.denied);

  succeed({
    framework: "mastra",
    action: ALLOWED_ACTION,
    checks: checks.length,
    denied,
    executed,
    lineagePatched,
    output: String(output),
  });
}

try {
  await main();
} catch (error) {
  fail(error);
}
