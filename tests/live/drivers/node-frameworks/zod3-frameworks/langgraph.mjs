// langgraph.mjs — real LangGraph.js agent live governance smoke driver (AAASM-3525).
//
// Builds a genuine LangGraph `StateGraph` with a node that calls a tool, applies
// BOTH LangGraph governance surfaces: the framework-specific `patchLangGraph`
// hook (the SDK's LangGraph lineage patch on `StateGraph.prototype.compile`) and
// the public `withAssembly` wrapper that performs TRUE pre-execution governance
// on the tool the node invokes. It then runs the compiled graph on an ALLOWED
// input. The gateway client is wired to the live aa-runtime, so the tool's
// pre-exec `check()` is the genuine `SDK -> aa-ffi -> aa-runtime` round-trip and
// the node's tool runs because the live core allowed it.
//
// Highlight functions on the real path: LangGraph compile-time lineage patch +
// pre-execution allow enforcement on the node's tool + event emission over the
// UDS + the graph node actually executing under governance. Deny-path is out of
// scope (AAASM-3000/3021 → strict xfail, AAASM-3172).

import { pathToFileURL } from "node:url";
import { StateGraph, START, END, Annotation } from "@langchain/langgraph";
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
  const args = readArgs("langgraph.mjs");
  if (!args) return;
  const { sdkNativeClientModule, socketPath } = args;

  const sdkIndex = new URL("../index.js", pathToFileURL(sdkNativeClientModule)).href;
  const { withAssembly, patchLangGraph } = await import(sdkIndex);

  const { gatewayClient, checks } = await buildLiveGatewayClient(
    sdkNativeClientModule,
    socketPath,
  );

  // Apply the LangGraph-specific governance hook (lineage on compile). Load the
  // real module explicitly so the hook patches the same StateGraph we use.
  const langgraphModule = await import("@langchain/langgraph");
  const patched = await patchLangGraph({
    agentId: "langgraph-smoke",
    loadModule: async () => langgraphModule,
  });
  if (!patched) {
    fail("patchLangGraph did not patch the LangGraph module");
    return;
  }

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
  // Bind invoke to the real tool: withAssembly calls the captured original
  // unbound, and LangChain's invoke reads `this` (see the langchain driver).
  const proxy = { invoke: searchTool.invoke.bind(searchTool) };
  const governed = withAssembly({ [ALLOWED_ACTION]: proxy }, { gatewayClient });

  const State = Annotation.Root({
    query: Annotation,
    result: Annotation,
  });

  const graph = new StateGraph(State)
    .addNode("search", async (state) => {
      const result = await governed[ALLOWED_ACTION].invoke({ query: state.query });
      return { result };
    })
    .addEdge(START, "search")
    .addEdge("search", END)
    .compile();

  const finalState = await graph.invoke({ query: "agent governance" });

  if (!executed) {
    fail("LangGraph node's tool did not run after an allowed governance check");
    return;
  }
  if (checks.length === 0) {
    fail("no governance check ran on the live path for the LangGraph tool call");
    return;
  }
  const denied = checks.some((c) => c.verdict.denied);

  succeed({
    framework: "langgraph",
    action: ALLOWED_ACTION,
    checks: checks.length,
    denied,
    executed,
    output: String(finalState.result),
  });
}

try {
  await main();
} catch (error) {
  fail(error);
}
