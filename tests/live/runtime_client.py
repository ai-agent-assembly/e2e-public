"""Drive the real SDK native FFI (``agent_assembly._core``) over a UDS.

The Python SDK reaches the local core through its native ``_core`` extension
(a thin pyo3 shim over ``aa-sdk-client``): ``RuntimeClient.connect(socket_path)``
opens the Unix-socket session, ``send_event`` ships a captured
``GovernanceEvent``, and ``close`` joins the background IPC thread. This is the
real ``SDK → aa-ffi → aa-runtime`` path.

The ``_core`` extension is an *optional, compiled* part of the SDK that may not
be present (e.g. a pure-Python install, or the SDK not installed at all), so
:func:`native_core_available` lets callers skip cleanly. The
``GovernanceEvent`` payload shape mirrors the SDK's own native-core test
(``python-sdk`` ``test/integration/test_native_core_runtime.py``): a serialized
``aa_core::AuditEntry`` JSON.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
from pathlib import Path
from types import ModuleType

#: The SDK's native extension module exposing ``RuntimeClient`` / ``GovernanceEvent``.
NATIVE_CORE_MODULE = "agent_assembly._core"


def native_core_available() -> bool:
    """Return True when the SDK's native ``_core`` extension can be imported.

    Probes for the module without importing it, so a caller can skip cleanly
    when the SDK or its compiled extension is absent.
    """
    try:
        return importlib.util.find_spec(NATIVE_CORE_MODULE) is not None
    except (ModuleNotFoundError, ValueError):
        return False


def import_native_core() -> ModuleType:
    """Import and return the SDK's native ``_core`` module.

    Call :func:`native_core_available` first to decide whether to skip.
    """
    return importlib.import_module(NATIVE_CORE_MODULE)


def make_audit_entry_payload(seq: int) -> str:
    """Return a serialized ``aa_core::AuditEntry`` JSON for a GovernanceEvent.

    Mirrors the payload the SDK's own native-core test builds so the event is
    accepted by ``GovernanceEvent(...)`` (which validates the JSON against
    ``aa_core::AuditEntry``). The byte-array fields are fixed-width as the
    wire type requires (16-byte ids, 32-byte hashes).
    """
    return json.dumps(
        {
            "seq": seq,
            "timestamp_ns": 1_700_000_000_000_000_000 + seq,
            "event_type": "ToolCallIntercepted",
            "agent_id": [0] * 16,
            "session_id": [seq % 255] * 16,
            "payload": json.dumps({"index": seq}),
            "previous_hash": [0] * 32,
            "entry_hash": [0] * 32,
        }
    )


def connect_runtime_client(socket_path: Path):  # noqa: ANN201 — returns native RuntimeClient
    """Connect a real native ``RuntimeClient`` to *socket_path*.

    Returns the SDK's genuine ``RuntimeClient`` so a test exercises the real
    FFI code path — not a stub. Call :func:`native_core_available` first.
    """
    core = import_native_core()
    return core.RuntimeClient.connect(str(socket_path))
