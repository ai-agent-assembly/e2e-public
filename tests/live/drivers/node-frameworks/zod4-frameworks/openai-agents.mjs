// openai-agents.mjs — real OpenAI Agents (Node) live governance smoke driver (AAASM-3525).
//
// Builds a genuine `@openai/agents` tool with `tool(...)` and wraps it with the
// public `withAssembly`, which performs TRUE pre-execution governance on the
// tool's `invoke` (OpenAI Agents tools expose `.name` + `.invoke`). It then runs
// an ALLOWED tool call via the tool's own `invoke`. The gateway client is wired
// to the live aa-runtime, so the pre-exec `check()` is the genuine
// `SDK -> aa-ffi -> aa-runtime` round-trip and the tool runs because the live
// core allowed it.
//
// We also attempt the framework-specific `patchOpenAIAgents` hook (which patches
// `Agent.prototype._runTool`) and REPORT whether it patched: in current
// `@openai/agents` the `_runTool` prototype method is absent, so that hook is a
// no-op on this version — surfaced in the result as `runToolHookPatched:false`
// rather than silently skipped (no silent gap). The enforcing path the live
// check actually runs through is the `withAssembly` tool wrapper above.
//
// Highlight functions on the real path: pre-execution allow enforcement on the
// OpenAI Agents tool + event emission over the UDS + the tool actually executing
// under governance. Deny-path is out of scope (AAASM-3000/3021 → strict xfail,
// AAASM-3172).

import { pathToFileURL } from "node:url";
import { tool } from "@openai/agents";
import { z } from "zod";
import {
  ALLOWED_ACTION,
  buildLiveGatewayClient,
  fail,
  readArgs,
  succeed,
} from "../_governance.mjs";

async function main() {
  const args = readArgs("openai-agents.mjs");
  if (!args) return;
  const { sdkNativeClientModule, socketPath } = args;

  const sdkIndex = new URL("../index.js", pathToFileURL(sdkNativeClientModule)).href;
  const { withAssembly, patchOpenAIAgents } = await import(sdkIndex);

  const { gatewayClient, checks } = await buildLiveGatewayClient(
    sdkNativeClientModule,
    socketPath,
  );

  // Attempt the framework-specific hook against the real module; report the
  // outcome instead of skipping. On builds without Agent.prototype._runTool this
  // returns false — surfaced, not hidden.
  const oaModule = await import("@openai/agents");
  let runToolHookPatched = false;
  try {
    runToolHookPatched = await patchOpenAIAgents({
      gatewayClient,
      loadAgentClass: async () => oaModule.Agent,
    });
  } catch {
    runToolHookPatched = false;
  }

  let executed = false;
  const searchTool = tool({
    name: ALLOWED_ACTION,
    description: "search the corpus",
    parameters: z.object({ query: z.string() }),
    execute: async ({ query }) => {
      executed = true;
      return `results for ${query}`;
    },
  });

  // withAssembly wraps the tool's invoke with the pre-exec governance chain.
  const governed = withAssembly({ [ALLOWED_ACTION]: searchTool }, { gatewayClient });
  const output = await governed[ALLOWED_ACTION].invoke(
    {},
    JSON.stringify({ query: "agent governance" }),
  );

  if (!executed) {
    fail("OpenAI Agents tool invoke did not run after an allowed governance check");
    return;
  }
  if (checks.length === 0) {
    fail("no governance check ran on the live path for the OpenAI Agents tool call");
    return;
  }
  const denied = checks.some((c) => c.verdict.denied);

  succeed({
    framework: "openai-agents",
    action: ALLOWED_ACTION,
    checks: checks.length,
    denied,
    executed,
    runToolHookPatched,
    output: String(output),
  });
}

try {
  await main();
} catch (error) {
  fail(error);
}
