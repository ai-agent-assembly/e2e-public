// langchain.mjs — real LangChain.js agent live governance smoke driver (AAASM-3525).
//
// Builds a genuine LangChain tool with `@langchain/core/tools` `tool(...)`, wraps
// it with the SDK's public `withAssembly` — the wrapper layer that performs TRUE
// pre-execution governance on a tool's `invoke` (the SDK's callback layer only
// redacts post-hoc; the wrapper is the enforcing path per the README's two-layer
// model) — and then invokes an ALLOWED tool call. The gateway client is wired to
// the live aa-runtime, so `withAssembly`'s pre-exec `check()` is the genuine
// `SDK -> aa-ffi -> aa-runtime` round-trip and the tool runs because the live
// core allowed it.
//
// Highlight functions on the real path: pre-execution allow enforcement, event
// emission over the UDS, and the LangChain tool actually executing under
// governance. Deny-path is out of scope (AAASM-3000/3021 → strict xfail,
// AAASM-3172).

import { pathToFileURL } from "node:url";
import { tool } from "@langchain/core/tools";
import { z } from "zod";
import {
  ALLOWED_ACTION,
  buildLiveGatewayClient,
  fail,
  readArgs,
  succeed,
} from "../_governance.mjs";

async function main() {
  const args = readArgs("langchain.mjs");
  if (!args) return;
  const { sdkNativeClientModule, socketPath } = args;

  const sdkIndex = new URL("../index.js", pathToFileURL(sdkNativeClientModule)).href;
  const { withAssembly } = await import(sdkIndex);

  const { gatewayClient, checks } = await buildLiveGatewayClient(
    sdkNativeClientModule,
    socketPath,
  );

  let executed = false;
  const searchTool = tool(
    async ({ query }) => {
      executed = true;
      return `results for ${query}`;
    },
    {
      name: ALLOWED_ACTION,
      description: "search the corpus",
      schema: z.object({ query: z.string() }),
    },
  );

  // withAssembly wraps each tool's `invoke` with the pre-exec governance chain.
  // LangChain's `invoke` is a prototype method that reads `this`; withAssembly
  // captures and calls the original unbound, so we hand it a thin proxy whose
  // `invoke` is bound to the real tool. The wrapper then governs the bound
  // invoke and the genuine LangChain tool runs with its own `this`.
  const proxy = { invoke: searchTool.invoke.bind(searchTool) };
  const governed = withAssembly({ [ALLOWED_ACTION]: proxy }, { gatewayClient });
  const output = await governed[ALLOWED_ACTION].invoke({ query: "agent governance" });

  if (!executed) {
    fail("LangChain tool invoke did not run after an allowed governance check");
    return;
  }
  if (checks.length === 0) {
    fail("no governance check ran on the live path for the LangChain tool call");
    return;
  }
  const denied = checks.some((c) => c.verdict.denied);

  succeed({
    framework: "langchain",
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
