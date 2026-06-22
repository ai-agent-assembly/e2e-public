"""Coverage manifest for the Python AI-agent framework live smokes (AAASM-3525).

Every framework adapter the Python SDK ships under ``agent_assembly.adapters`` now
has its own real allow-path + deny-``xfail`` live module:

    langchain · langgraph · pydantic_ai · crewai · google_adk · haystack · mcp · openai_agents
    · smolagents · agno · microsoft_agent_framework

This module is the **no-silent-gaps guard**: it asserts that each supported SDK
framework adapter imports *and* has a matching ``test_framework_python_<framework>.py``
module, and that the SDK has not added a framework adapter that lacks one — so a
newly-supported framework without a live smoke is a visible failure here rather
than a quiet omission. (OpenAI Agents became coverable once AAASM-3528 realigned
its adapter to the shipped ``agents`` API.)
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: Both cells below import the Python SDK (``agent_assembly`` adapters) directly,
#: so without it installed there is nothing to assert — skip cleanly with a
#: justified reason rather than erroring, exactly as the per-framework smokes do.
pytest.importorskip(
    "agent_assembly",
    reason="agent_assembly (the Python SDK) is not installed — install it from "
    "../python-sdk or PyPI to run the framework coverage manifest (AAASM-3525)",
)

#: (framework id, SDK adapter import path) for every supported Python framework.
#: Each MUST have a real allow-path live module ``test_framework_python_<id>.py``.
_SUPPORTED = [
    ("langchain", "agent_assembly.adapters.langchain.adapter"),
    ("langgraph", "agent_assembly.adapters.langgraph.adapter"),
    ("pydantic_ai", "agent_assembly.adapters.pydantic_ai.adapter"),
    ("crewai", "agent_assembly.adapters.crewai.adapter"),
    ("google_adk", "agent_assembly.adapters.google_adk.adapter"),
    ("haystack", "agent_assembly.adapters.haystack.adapter"),
    ("mcp", "agent_assembly.adapters.mcp.adapter"),
    ("openai_agents", "agent_assembly.adapters.openai_agents.adapter"),
    ("smolagents", "agent_assembly.adapters.smolagents.adapter"),
    ("agno", "agent_assembly.adapters.agno.adapter"),
    ("microsoft_agent_framework", "agent_assembly.adapters.microsoft_agent_framework.adapter"),
]

_HERE = Path(__file__).parent


@pytest.mark.parametrize(
    ("framework", "adapter_module"),
    _SUPPORTED,
    ids=[fw for fw, _ in _SUPPORTED],
)
def test_supported_framework_has_live_smoke(framework: str, adapter_module: str) -> None:
    """Every supported Python framework adapter imports and has a live smoke module.

    Catches a regression in the SDK adapter (import failure) and a missing live
    smoke for a supported framework — either is a visible failure, not a silent gap.
    """
    importlib.import_module(adapter_module)
    module = _HERE / f"test_framework_python_{framework}.py"
    assert module.exists(), (
        f"{framework}: the SDK ships adapter `{adapter_module}` but there is no "
        f"`{module.name}` live smoke — add one (real allow-path + deny `strict` "
        f"xfail on AAASM-3172)."
    )


def test_no_unmapped_framework_adapters() -> None:
    """Fail if the SDK adds a framework adapter that this manifest does not map.

    Enumerates the SDK's adapter subpackages (a directory with an ``adapter.py``)
    and asserts each one is in ``_SUPPORTED`` — so a newly-shipped framework adapter
    cannot land without a corresponding live smoke being demanded above.
    """
    import agent_assembly.adapters as adapters_pkg

    pkg_dir = Path(adapters_pkg.__file__).parent
    found = {p.name for p in pkg_dir.iterdir() if p.is_dir() and (p / "adapter.py").exists()}
    mapped = {fw for fw, _ in _SUPPORTED}
    unmapped = found - mapped
    assert not unmapped, (
        f"the SDK ships framework adapter(s) {sorted(unmapped)} with no entry in "
        f"this coverage manifest — add them and a live smoke (AAASM-3525)."
    )
