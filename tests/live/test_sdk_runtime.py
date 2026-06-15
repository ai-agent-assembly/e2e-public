"""Live smoke: the real SDK native FFI reaches ``aa-runtime`` over the UDS.

This builds and runs ``aa-runtime`` from core source (via the ``live_runtime``
fixture) and drives the *real* SDK native extension (``agent_assembly._core``)
at it — the genuine ``SDK → aa-ffi → aa-runtime`` path. It replaces the deviant
SDK→gateway-HTTP probe (``test_sdk_register.py``): the SDK never spoke HTTP to
the gateway for its hot-path events; it ships them over the runtime's Unix
socket.

It skips cleanly when the build toolchain is unavailable (no ``aa-runtime``) or
when the SDK's compiled ``_core`` extension is not installed (pure-Python
install / SDK absent).
"""

from __future__ import annotations

import pytest

from tests.live.runtime import LiveRuntime
from tests.live.runtime_client import (
    connect_runtime_client,
    import_native_core,
    make_audit_entry_payload,
    native_core_available,
)

pytestmark = pytest.mark.live


def _require_native_core() -> None:
    """Skip the calling test when the SDK's native ``_core`` ext is absent."""
    if not native_core_available():
        pytest.skip(
            "agent_assembly._core native extension is not built — install the SDK "
            "wheel (with the compiled _core) from ../python-sdk or PyPI to run this"
        )


def test_sdk_native_ffi_reaches_runtime(live_runtime: LiveRuntime) -> None:
    """The real native ``RuntimeClient`` connects to the live runtime and ships events.

    Opens a genuine ``RuntimeClient`` over the runtime's UDS (which performs the
    real IPC heartbeat handshake against the live ``aa-runtime``), confirms it
    bound the expected socket, ships several captured ``GovernanceEvent``s, and
    closes cleanly — proving the SDK→aa-ffi→aa-runtime transport end to end.
    """
    _require_native_core()
    core = import_native_core()

    client = connect_runtime_client(live_runtime.socket_path)
    try:
        assert client.socket_path == str(live_runtime.socket_path)
        for seq in range(5):
            client.send_event(core.GovernanceEvent(make_audit_entry_payload(seq)))
    finally:
        client.close()
