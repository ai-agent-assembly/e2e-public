"""Live framework smoke: a real **CrewAI** agent through the SDK + live core.

Part of AAASM-3525 (real, non-mock framework smoke tests). The SDK's CrewAI
adapter monkey-patches ``crewai.tools.BaseTool.run`` so a governed tool consults
``check_tool_start`` before its body executes — the entry point a CrewAI
``Agent`` uses every time it runs a tool. This test applies the real
``CrewAIPatch`` and drives a genuine governed ``BaseTool`` that is wired into a
**real** ``Agent`` / ``Task`` / ``Crew`` (constructed offline, no LLM call)
against a live ``aa-runtime`` — the production
``CrewAI → SDK adapter → aa-ffi → aa-runtime`` governance path.

Why drive ``BaseTool.run`` rather than ``Crew.kickoff()``: a full crew kickoff
requires a real LLM to *decide* to call the tool (CrewAI routes the agent loop
through litellm), which cannot run offline and is brittle to stub across CrewAI
versions. The governance hook the SDK installs is on ``BaseTool.run`` — the exact
call a CrewAI agent makes to execute a tool — so invoking the governed tool that
is registered on a real ``Agent``/``Crew`` exercises the identical production
path with the framework objects fully real and only the model absent. This
mirrors the LangChain / LangGraph cells, which invoke the real tool through the
real adapter without spinning a live LLM.

The **highlight governance functions** this exercises (per the AAASM-3525 plan):

* **Pre-execution allow enforcement** — the patched ``BaseTool.run`` asks the
  live runtime ``query_policy`` (via the production ``RuntimeQueryInterceptor``)
  whether the tool may run; an ``allow`` lets the real tool body execute
  (asserted by the tool's observable side effect + its real output, versus the
  adapter's ``[BLOCKED by governance policy]`` short-circuit string).
* **Event emission / audit capture** — the same native ``RuntimeClient`` ships a
  ``GovernanceEvent`` to the live runtime over the real UDS transport.

The **deny path** (a denied tool actually short-circuited end-to-end) is a
``strict=True`` xfail pinned on AAASM-3000 + AAASM-3021 (flip via AAASM-3172) —
see :data:`tests.live.framework_live.DENY_XFAIL_REASON`. Note the CrewAI adapter
expresses a deny by *returning* the ``[BLOCKED by governance policy]`` message
(so the agent can react) rather than raising, so the deny assertion checks the
tool body did not run and the blocked message was returned.
"""

from __future__ import annotations

import sys

import pytest

from tests.live.framework_live import (
    DENY_XFAIL_REASON,
    live_runtime_interceptor,
    require_framework,
    require_native_core,
)
from tests.live.runtime import LiveRuntime
from tests.live.runtime_client import import_native_core, make_audit_entry_payload

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

#: CrewAI's importable package name (the SDK adapter's ``get_framework_name``).
FRAMEWORK_IMPORT = "crewai"
FRAMEWORK_PACKAGE = "crewai"

#: Skip reason for the CrewAI cells when CrewAI's own transitive stack cannot
#: import on the active Python. CrewAI ``~=1.14`` pulls ``chromadb 1.1.1`` which
#: still defines its ``Settings`` on the legacy ``pydantic.v1`` shim; on
#: **Python 3.14** that shim raises
#: ``pydantic.v1.errors.ConfigError: unable to infer type for attribute
#: "chroma_server_nofile"`` the moment ``crewai`` (→ ``crewai.rag`` →
#: ``chromadb``) is imported or a ``BaseTool``/``Agent``/``Crew`` is built. The
#: failure is upstream's deps not supporting 3.14 — not our governance wiring
#: — so the cell skips with this concrete, justified reason and coverage resumes
#: automatically once CrewAI/chromadb ship a 3.14-compatible release. ``find_spec``
#: cannot detect this (the spec exists; only *importing* it fails), so the cell
#: must force the real import to surface the incompatibility.
CREWAI_PY314_SKIP_REASON = (
    "crewai + chromadb 1.1.1 (pydantic.v1) do not support "
    f"Python {sys.version_info.major}.{sys.version_info.minor}: importing crewai "
    "raises pydantic.v1.errors.ConfigError "
    '("unable to infer type for attribute chroma_server_nofile"). Install a '
    "crewai/chromadb release that supports this Python to run this cell "
    "(AAASM-3533)."
)


def require_crewai_runtime() -> None:
    """Skip the calling cell when CrewAI's runtime deps fail to import here.

    ``require_framework`` only proves the ``crewai`` *spec* exists; it does not
    import it. On Python 3.14 the import itself (and any ``BaseTool``/``Agent``/
    ``Crew`` construction that pulls in ``crewai.rag`` → ``chromadb`` →
    ``pydantic.v1``) raises ``pydantic.v1.errors.ConfigError`` — CrewAI's own
    transitive stack not supporting 3.14, not a defect in our governance path.
    Force the real imports the cells use and turn that upstream incompatibility
    into a clean, justified skip (:data:`CREWAI_PY314_SKIP_REASON`) so the suite
    never hard-fails on it and coverage resumes once upstream supports 3.14.

    The ``ConfigError`` is *not* an ``ImportError``, so it is matched by name
    (avoiding a hard import of ``pydantic.v1`` internals just to reference the
    type): any error raised while importing CrewAI's stack named ``ConfigError``
    is the chromadb/pydantic-v1 incompatibility this guards.
    """
    try:
        import crewai  # noqa: F401
        import crewai.tools  # noqa: F401
    except ImportError:
        pytest.skip(CREWAI_PY314_SKIP_REASON)
    except Exception as exc:  # noqa: BLE001 — narrowed to the chromadb/pydantic-v1 ConfigError
        if type(exc).__name__ == "ConfigError":
            pytest.skip(CREWAI_PY314_SKIP_REASON)
        raise


#: The adapter's deny short-circuit marker (``_format_blocked_message``). CrewAI's
#: tool-run patch *returns* this string on a deny rather than raising, so the
#: agent loop can react — the deny assertions key off it instead of an exception.
BLOCKED_MARKER = "[BLOCKED by governance policy]"


def _build_governed_tool():  # noqa: ANN202 — returns a crewai BaseTool subclass instance
    """Return a real CrewAI ``BaseTool`` whose execution we can observe.

    The tool appends to a list it closes over, so a test can assert it actually
    *ran* (the allow decision let it through ``BaseTool.run``) versus was
    short-circuited by the adapter's deny branch.
    """
    from crewai.tools import BaseTool
    from pydantic import BaseModel

    calls: list[str] = []

    class _SearchArgs(BaseModel):
        query: str

    class SearchTool(BaseTool):
        name: str = "search"
        description: str = "Search the web for a query."
        args_schema: type = _SearchArgs

        def _run(self, query: str) -> str:
            calls.append(query)
            return f"results for {query}"

    return SearchTool(), calls


def _build_real_crew(tool):  # noqa: ANN001, ANN202 — returns the constructed Crew
    """Wire *tool* into a real CrewAI ``Agent`` / ``Task`` / ``Crew`` (offline).

    Constructs genuine framework objects so the governed tool is exercised as an
    agent's registered tool, not in isolation. Construction alone makes no LLM
    call (the offline ``api_key`` is never used because ``kickoff`` is not run),
    so this stays hermetic; the returned crew proves the tool is a real member of
    a real agent before its governed ``run`` is driven.
    """
    from crewai import LLM, Agent, Crew, Task

    # An offline LLM handle: only needed to construct the Agent; never invoked
    # because the test drives the governed tool directly rather than kicking off.
    llm = LLM(model="gpt-4o-mini", api_key="sk-offline-stub")
    agent = Agent(
        role="researcher",
        goal="answer questions",
        backstory="a test agent",
        tools=[tool],
        llm=llm,
        verbose=False,
    )
    task = Task(description="search the web", expected_output="results", agent=agent, tools=[tool])
    return Crew(agents=[agent], tasks=[task])


def test_crewai_governance_path_is_wired() -> None:
    """Offline: the SDK's CrewAI adapter patches ``BaseTool.run`` and honours deny.

    The floor under the live path: the real ``CrewAIPatch`` routes a tool run
    through an interceptor's ``check_tool_start`` and short-circuits on a
    ``deny`` (returning the blocked message, not running the body). A stub
    enforce-posture interceptor proves the patch honours the decision contract
    with no live runtime, so this stays green in a bare ``-m e2e`` run.
    """
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    require_crewai_runtime()
    from agent_assembly.adapters.crewai.patch import CrewAIPatch

    class _DenyInterceptor:
        _enforce = True

        def check_tool_start(self, **_kwargs: object) -> dict[str, str]:
            return {"status": "deny", "reason": "blocked by test policy"}

    tool, calls = _build_governed_tool()
    patch = CrewAIPatch(_DenyInterceptor())
    assert patch.apply() is True, "CrewAI tool hook did not install"
    try:
        result = tool.run(query="weather")
        assert calls == [], "deny path let the CrewAI tool body execute"
        assert BLOCKED_MARKER in str(result)
    finally:
        patch.revert()


def test_crewai_allow_path_runs_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Allow path: a real CrewAI tool runs governed by a live runtime decision.

    Builds the production governance interceptor against the live runtime, applies
    the real ``CrewAIPatch``, wires the governed tool into a genuine
    ``Agent``/``Task``/``Crew``, then runs the tool through the patched
    ``BaseTool.run`` — the real ``CrewAI → SDK adapter → aa-ffi → aa-runtime``
    path. The live runtime answers ``query_policy`` with ``allow`` (the fixture
    runtime runs policy-disabled), so the tool executes: we assert its observable
    side effect (the tool ran) and its real output (not the adapter's blocked
    message), proving enforcement let an allowed call through rather than the call
    merely not being intercepted.
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    require_crewai_runtime()
    from agent_assembly.adapters.crewai.patch import CrewAIPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = CrewAIPatch(interceptor)
    assert patch.apply() is True, "CrewAI tool hook did not install"
    tool, calls = _build_governed_tool()
    crew = _build_real_crew(tool)
    registered = [t.name for t in crew.agents[0].tools]
    assert "search" in registered, "governed tool not registered on the real CrewAI agent"
    try:
        output = tool.run(query="weather")

        assert calls == ["weather"], "allowed CrewAI tool did not execute under live governance"
        assert output == "results for weather"
        assert BLOCKED_MARKER not in str(output)
    finally:
        patch.revert()


def test_crewai_allow_path_emits_audit_event(live_runtime: LiveRuntime) -> None:
    """Allow path: the SDK ships a governance/audit event to the live runtime.

    Audit capture and event emission travel the same native ``send_event``
    transport the SDK uses to record what an agent did. Shipping a captured
    ``GovernanceEvent`` over the real UDS to the live runtime without rejection
    is the in-scope, provable-today half of the "audit capture" highlight
    function (full audit-store read-back is covered by the gateway-side tests).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    core = import_native_core()

    client = core.RuntimeClient.connect(str(live_runtime.socket_path))
    # A raise here would mean event emission is broken at the transport — which is
    # exactly what this guards. close() is intentionally not asserted (AAASM-3000).
    client.send_event(core.GovernanceEvent(make_audit_entry_payload(0)))


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), drop this strict xfail and assert the denied tool is short-circuited.
@pytest.mark.xfail(strict=True, reason=DENY_XFAIL_REASON)  # AAASM-3172
def test_crewai_deny_path_blocks_tool_through_live_runtime(
    live_runtime: LiveRuntime,
) -> None:
    """Deny path: a denied CrewAI tool is short-circuited end-to-end (strict-xfail).

    The load-bearing enforcement assertion for CrewAI: with a policy that denies
    the tool, running it through the real patched ``BaseTool.run`` against the
    live runtime must return the adapter's ``[BLOCKED by governance policy]``
    message *before* the tool body runs (CrewAI's adapter signals a deny by
    returning that message, not by raising). It cannot pass today — the fixture
    runtime runs policy-disabled and the SDK's full deny wiring is unshipped
    (AAASM-3021), so the runtime answers ``allow`` and the tool runs. Pinned
    ``strict=True`` so the day enforcement works it XPASSes and the strict marker
    fails the suite — the cue to flip (AAASM-3172).
    """
    require_native_core()
    require_framework(FRAMEWORK_IMPORT, FRAMEWORK_PACKAGE)
    from agent_assembly.adapters.crewai.patch import CrewAIPatch

    interceptor = live_runtime_interceptor(live_runtime)
    patch = CrewAIPatch(interceptor)
    assert patch.apply() is True, "CrewAI tool hook did not install"
    tool, calls = _build_governed_tool()
    try:
        output = tool.run(query="secret")
        assert calls == [], "deny path let the tool body execute"
        assert BLOCKED_MARKER in str(output), "deny path did not short-circuit the tool"
    finally:
        patch.revert()
