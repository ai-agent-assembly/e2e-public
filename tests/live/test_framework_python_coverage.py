"""Live framework smoke coverage status for the remaining Python cells (AAASM-3525).

The AAASM-3525 plan enumerates these SDK framework adapters for Python: LangChain,
LangGraph, CrewAI, OpenAI Agents, Pydantic AI, Google ADK, and MCP. The first
three runnable cells have their own real allow-path + deny-xfail smoke modules:

* ``test_framework_python_langchain.py``   — LangChain   (real allow-path, live)
* ``test_framework_python_langgraph.py``   — LangGraph   (real allow-path, live)
* ``test_framework_python_pydantic_ai.py`` — Pydantic AI (real allow-path, live)

This module is the **explicit, no-silent-gaps record** for the cells that cannot
run a real governed agent in this offline harness today. Each is a parametrized
test that **skips with a concrete, justified reason** (never a silent pass), and
the offline guard below asserts the SDK adapter for every cell still imports — so
a cell that *becomes* coverable (framework published with a matching API, an
example added) is a visible, intentional change rather than a quiet omission.

The reasons are real, verified against the SDK adapter source and this
environment — they are not placeholders:

* **CrewAI** — the SDK ships a real ``crewai`` adapter, but ``crewai`` is not
  installable in this offline harness (heavyweight transitive deps, no offline
  wheel cache). Coverable by installing ``crewai`` alongside the SDK; the adapter
  patches CrewAI's tool execution onto the same ``check_tool_start`` governance
  contract the runnable cells use.
* **OpenAI Agents** — adapter/framework **version skew**: the SDK adapter targets
  the ``openai.agents`` module and a ``FunctionTool.__call__`` hook, but the
  current OpenAI Agents SDK ships as the top-level ``agents`` package whose
  ``FunctionTool`` exposes ``on_invoke_tool`` (no ``__call__`` hook). ``patch.apply()``
  returns ``False`` here, so there is no real governed path to exercise until the
  adapter is realigned to the shipped API (a product gap to file under Epic 3198).
* **Google ADK** — the SDK ships a real ``google_adk`` adapter, but
  ``google-adk`` is not installable in this offline harness. Coverable by
  installing it alongside the SDK.
* **MCP** — the SDK ships a real ``mcp`` adapter (it patches
  ``ClientSession.call_tool``), and ``mcp`` is importable, but a live governed
  smoke needs a **running MCP server + a real ``ClientSession``**, and there is
  **no MCP example** in ``agent-assembly-examples`` to drive (flagged in the
  AAASM-3525 plan). A real MCP server harness is its own follow-up; without it a
  governed-tool smoke would be a fabricated path, so this cell is recorded rather
  than faked.

When a cell here becomes coverable, promote it to its own
``test_framework_python_<framework>.py`` mirroring the runnable modules (real
allow-path live + deny-path ``strict=True`` xfail on AAASM-3172).
"""

from __future__ import annotations

import importlib

import pytest

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: Each not-yet-runnable cell: (label, SDK adapter import path, skip reason).
#: The adapter import path is asserted importable offline so the SDK adapter for
#: every supported framework is proven present even when the framework itself or
#: a live harness for it is not.
_UNCOVERED_CELLS = [
    pytest.param(
        "agent_assembly.adapters.crewai.adapter",
        "CrewAI adapter ships in the SDK, but `crewai` is not installable in this "
        "offline harness — install crewai alongside the SDK to cover this cell "
        "(AAASM-3525).",
        id="crewai",
    ),
    pytest.param(
        "agent_assembly.adapters.openai_agents.adapter",
        "OpenAI Agents adapter targets the `openai.agents` module + a "
        "FunctionTool.__call__ hook, but the shipped OpenAI Agents SDK is the "
        "top-level `agents` package (on_invoke_tool, no __call__); patch.apply() "
        "is a no-op here. Realign the adapter to the shipped API to cover this "
        "cell (AAASM-3525 / Epic 3198).",
        id="openai_agents",
    ),
    pytest.param(
        "agent_assembly.adapters.google_adk.adapter",
        "Google ADK adapter ships in the SDK, but `google-adk` is not installable "
        "in this offline harness — install google-adk alongside the SDK to cover "
        "this cell (AAASM-3525).",
        id="google_adk",
    ),
    pytest.param(
        "agent_assembly.adapters.mcp.adapter",
        "MCP adapter ships in the SDK (patches ClientSession.call_tool), but a "
        "live governed smoke needs a running MCP server + real ClientSession and "
        "there is no MCP example to drive (AAASM-3525 plan gap) — a real MCP "
        "server harness is a follow-up.",
        id="mcp",
    ),
]


@pytest.mark.parametrize(("adapter_module", "reason"), _UNCOVERED_CELLS)
def test_uncovered_framework_cell_is_recorded(adapter_module: str, reason: str) -> None:
    """Record a not-yet-coverable framework cell as a justified skip, not a gap.

    Asserts the SDK adapter for the cell imports (so the supported-framework
    surface stays visible and a future regression in the adapter is caught), then
    skips with the concrete reason the cell cannot run a real governed agent here.
    """
    importlib.import_module(adapter_module)
    pytest.skip(reason)
