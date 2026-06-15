"""Live smoke: the real SDK native FFI drives a session against ``aa-runtime``.

This builds and runs ``aa-runtime`` from core source (via the ``live_runtime``
fixture) and drives the *real* SDK native extension (``agent_assembly._core``)
at it — the genuine ``SDK → aa-ffi → aa-runtime`` path. It replaces the deviant
SDK→gateway-HTTP probe (``test_sdk_register.py``): the SDK never spoke HTTP to
the gateway for its hot-path events; it ships them over the runtime's Unix
socket.

It skips cleanly when the build toolchain is unavailable (no ``aa-runtime``) or
when the SDK's compiled ``_core`` extension is not installed (pure-Python
install / SDK absent).

*Known failure (AAASM-3000):* a real ``RuntimeClient`` against a real runtime
currently deadlocks — ``aa-sdk-client``'s IPC loop blocks on a heartbeat/event
``Ack`` that the runtime never sends (``aa-runtime`` ignores heartbeats and only
responds to violations/policy-queries), so the background thread never drains
the command channel and ``close()`` hangs. This test marks that ``xfail`` with a
``close()`` watchdog so it exposes the deadlock without hanging CI; it will
``XPASS`` the day the contract is fixed — the cue to drop the marker.
"""

from __future__ import annotations

import threading

import pytest

from tests.live.runtime import LiveRuntime
from tests.live.runtime_client import (
    connect_runtime_client,
    import_native_core,
    make_audit_entry_payload,
    native_core_available,
)

pytestmark = pytest.mark.live

#: How long to wait for ``RuntimeClient.close()`` before declaring a deadlock.
CLOSE_WATCHDOG_SECONDS = 8.0


def _require_native_core() -> None:
    """Skip the calling test when the SDK's native ``_core`` ext is absent."""
    if not native_core_available():
        pytest.skip(
            "agent_assembly._core native extension is not built — install the SDK "
            "wheel (with the compiled _core) from ../python-sdk or PyPI to run this"
        )


def _close_returns_within(client, timeout: float) -> bool:  # noqa: ANN001 — native RuntimeClient
    """Call ``client.close()`` on a watchdog thread; return True iff it returns.

    ``close()`` joins the SDK's background IPC thread, which deadlocks against a
    real runtime (AAASM-3000). Running it on a daemon thread keeps the test from
    hanging: if the join does not complete within *timeout*, we report the
    deadlock rather than blocking the suite. The abandoned thread unwinds when
    the ``live_runtime`` fixture later terminates the runtime (the socket EOF
    releases the IPC loop).
    """
    done = threading.Event()

    def _close() -> None:
        client.close()
        done.set()

    threading.Thread(target=_close, daemon=True).start()
    return done.wait(timeout)


@pytest.mark.xfail(
    reason=(
        "SDK⇄aa-runtime IPC deadlock (AAASM-3000): aa-sdk-client blocks on a "
        "heartbeat/event Ack that aa-runtime never sends, so close() hangs and "
        "no events are delivered. XPASS is the signal the contract is fixed."
    ),
    strict=False,
    raises=AssertionError,
)
def test_sdk_native_ffi_session_against_runtime(live_runtime: LiveRuntime) -> None:
    """The real native ``RuntimeClient`` runs a clean session against the live runtime.

    Opens a genuine ``RuntimeClient`` over the runtime's UDS, ships several
    captured ``GovernanceEvent``s, and closes cleanly — the full SDK→aa-ffi→
    aa-runtime contract. Currently xfails on the clean-close step (AAASM-3000).
    """
    _require_native_core()
    core = import_native_core()

    client = connect_runtime_client(live_runtime.socket_path)
    assert client.socket_path == str(live_runtime.socket_path)
    for seq in range(5):
        client.send_event(core.GovernanceEvent(make_audit_entry_payload(seq)))

    assert _close_returns_within(client, CLOSE_WATCHDOG_SECONDS), (
        "RuntimeClient.close() did not return within "
        f"{CLOSE_WATCHDOG_SECONDS:.0f}s — SDK⇄runtime IPC deadlock (AAASM-3000)"
    )
