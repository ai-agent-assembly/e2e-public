"""Shared plumbing for the per-framework live-core smoke tests (AAASM-3525).

These smoke tests prove a *real agent on a real AI-agent framework* runs through
the Python SDK's framework adapter and a **live ``aa-runtime``** — the genuine
``framework → SDK adapter → aa-ffi → aa-runtime`` governance path, with no mocked
gateway/core. The only thing stubbed is the LLM (an offline test model or a
directly-invoked tool); the framework and the governance path are real.

This module owns the half that is identical across every framework cell so each
per-framework test stays small and only carries its own framework wiring:

* **A real governance interceptor against the live runtime** —
  :func:`live_runtime_interceptor` connects the SDK's native ``RuntimeClient`` to
  the runtime's UDS and wraps it in the production
  :class:`~agent_assembly.core.runtime_interceptor.RuntimeQueryInterceptor` in
  ``enforce`` posture. This is the exact object the SDK hands its framework
  adapters in production: its ``check_tool_start`` asks the live runtime
  ``query_policy`` whether a tool may run. The allow path is provable today
  (``query_policy`` is a synchronous request/response that does **not** hit the
  AAASM-3000 ``close()``/event-Ack deadlock — verified live).

* **The native-core availability probe** — :func:`require_native_core` lets a
  test skip cleanly (justified env requirement) when the SDK's compiled ``_core``
  extension is absent, mirroring ``test_e2e_python.py``.

* **Per-framework availability probes** — :func:`require_framework` skips a cell
  with a concrete reason when its framework package is not importable, so an
  optional framework that is not installed offline is a *visible, justified* skip
  rather than a silent gap (AC: "no silent gaps").

* **The shared deny-path xfail reason** — :data:`DENY_XFAIL_REASON`. Every
  framework's deny assertion is a ``strict=True`` xfail pinned on the same two
  open product gaps (AAASM-3000 + AAASM-3021, flip-gated on AAASM-3172) as the
  existing live E2E, so the "enforcement actually blocks" half of the AC never
  yields a false green until a fixed SDK release ships.

The interceptor's ``client`` slot (the wrapped ``GatewayClient`` in production)
is irrelevant to these smoke tests: they exercise ``check_tool_start``, which
``RuntimeQueryInterceptor`` defines itself and answers from the live runtime — it
never delegates to the wrapped client for the pre-execution decision. A
:class:`_InertGatewayClient` stands in so the rare delegated attribute lookup
(e.g. ``on_tool_end``) is a harmless no-op rather than a network call.
"""

from __future__ import annotations

import importlib.util
from typing import Any

import pytest

from tests.live.runtime import LiveRuntime
from tests.live.runtime_client import import_native_core, native_core_available

#: The shared xfail reason for every framework's deny-path assertion. The deny
#: side of "enforcement actually takes effect" is unprovable end-to-end today:
#:
#: * AAASM-3000 — SDK⇄aa-runtime IPC deadlock: ``aa-sdk-client``'s event/close
#:   path blocks on an Ack the runtime never sends.
#: * AAASM-3021 — the SDK's full pre-execution enforcement wiring (a denied tool
#:   blocked end-to-end through ``init_assembly``) is not yet shipped.
#:
#: AAASM-3172 flips these from xfail to a hard assert once a fixed SDK release
#: ships. Until then a deny assertion is a ``strict=True`` xfail so it can never
#: silently pass.
DENY_XFAIL_REASON = (
    "SDK→runtime deny enforcement is unprovable end-to-end today: AAASM-3000 "
    "(SDK⇄aa-runtime IPC deadlock) + AAASM-3021 (SDK pre-execution enforcement "
    "not fully wired). Flip to a hard assert via AAASM-3172 once a fixed SDK "
    "release ships."
)

#: The agent id every framework cell registers under against the live runtime.
LIVE_AGENT_ID = "aaitest-framework"


class _InertGatewayClient:
    """A no-op stand-in for the ``GatewayClient`` the interceptor wraps.

    ``RuntimeQueryInterceptor`` delegates any attribute it does not define
    (event reporting, ``on_tool_end`` hooks, approval-timeout providers) to the
    wrapped client. These framework smoke tests assert only the pre-execution
    ``check_tool_start`` decision, which the interceptor answers from the live
    runtime itself — so a delegated lookup here is incidental. Returning an inert
    callable keeps such a lookup from raising or making a network call, without
    pretending to be a real gateway.
    """

    def __getattr__(self, name: str) -> Any:
        def _noop(*_args: Any, **_kwargs: Any) -> None:
            return None

        return _noop


def require_native_core() -> None:
    """Skip the calling test when the SDK's native ``_core`` ext is absent.

    The framework smoke tests need the compiled native extension to reach the
    live runtime; a pure-Python install (or no SDK at all) cannot, so the test
    skips with a justified reason exactly as the existing live E2E does.
    """
    if not native_core_available():
        pytest.skip(
            "agent_assembly._core native extension is not built — install the SDK "
            "wheel (with the compiled _core) from ../python-sdk or PyPI to run this"
        )


def require_framework(import_name: str, package_hint: str) -> None:
    """Skip the calling cell when *import_name* is not importable.

    A supported framework that cannot be installed offline (or is simply not
    present in this environment) must be a *visible* skip with a concrete reason,
    never a silent gap (AC). *package_hint* names the pip distribution so the skip
    message tells a reader exactly what to install to cover the cell.

    For a dotted *import_name* (e.g. ``google.adk``) ``find_spec`` *raises*
    ``ModuleNotFoundError`` when an ancestor package (here ``google``) is itself
    absent, rather than returning ``None`` — so that, too, is a clean justified
    skip, not a test error.
    """
    try:
        spec = importlib.util.find_spec(import_name)
    except ModuleNotFoundError:
        spec = None
    if spec is None:
        pytest.skip(
            f"{import_name} not importable — install {package_hint} to run this "
            "framework's live governance smoke test"
        )


def live_runtime_interceptor(runtime: LiveRuntime, *, agent_id: str = LIVE_AGENT_ID) -> Any:
    """Return the production governance interceptor wired to *runtime*.

    Connects the SDK's genuine native ``RuntimeClient`` to the live runtime's
    UDS and wraps it in :class:`RuntimeQueryInterceptor` in ``enforce`` posture —
    the exact interceptor the SDK hands a framework adapter in production. Its
    ``check_tool_start`` consults the live runtime via ``query_policy``; this is
    what makes each framework's allow path *real* rather than mocked.

    Call :func:`require_native_core` first so the import here cannot fail.
    """
    core = import_native_core()
    runtime_client = core.RuntimeClient.connect(str(runtime.socket_path))

    from agent_assembly.core.runtime_interceptor import RuntimeQueryInterceptor

    return RuntimeQueryInterceptor(
        client=_InertGatewayClient(),
        runtime_client=runtime_client,
        agent_id=agent_id,
        enforce=True,
    )
