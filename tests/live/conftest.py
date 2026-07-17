"""Pytest fixtures for the live-core gateway tests.

The ``live_gateway`` fixture composes the three helpers — obtain the
core source, build ``aa-gateway``, then launch it — and yields a ready
:class:`LiveGateway` handle. It is session-scoped so the (expensive)
clone + cargo build happen once per test session.

It skips cleanly when ``cargo`` / ``protoc`` are absent, mirroring the
``skip_if_binary_missing`` pattern used by the public SDK tests.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.live.api_server import LiveApiServer
from tests.live.build import build_api_server, build_gateway, build_runtime, missing_build_tools
from tests.live.core_source import DEFAULT_REF, resolve_core_source
from tests.live.gateway import LiveGateway
from tests.live.runtime import LiveRuntime


@pytest.fixture(scope="session")
def _gateway_family_core_source() -> Path:
    """Resolve (clone or reuse) the core source ``aa-gateway``-family binaries build from.

    Session-scoped and shared by :func:`core_gateway_binary` and
    :func:`core_api_server_binary` so both binaries compile from the identical
    commit — the AAASM-4792 version-skew preflight relies on this to source a
    genuinely comparable version from the companion ``aa-api-server`` process
    (see ``api_server.py``) instead of ``aa-gateway``'s own (REST-less)
    surface.
    """
    ref = os.environ.get("AASM_CORE_REF", DEFAULT_REF)
    # Not a context-managed tempdir: when we clone, the built binaries live
    # under this directory and must survive for the whole test session.
    clone_dir = Path(tempfile.mkdtemp(prefix="aa-core-src-"))
    return resolve_core_source(clone_dir / "agent-assembly", ref=ref)


@pytest.fixture(scope="session")
def core_gateway_binary(_gateway_family_core_source: Path) -> Path:
    """Build ``aa-gateway`` from the shared core source and return the binary.

    Skips the session's live tests when the build toolchain is incomplete.
    """
    missing = missing_build_tools()
    if missing:
        pytest.skip(
            f"live gateway build needs: {', '.join(missing)} — "
            "install them to run the live-core tests"
        )
    return build_gateway(_gateway_family_core_source)


@pytest.fixture(scope="session")
def core_api_server_binary(_gateway_family_core_source: Path) -> Path:
    """Build ``aa-api-server`` from the shared core source and return the binary.

    Skips the session's live tests when the build toolchain is incomplete.
    Built from the same checkout as :func:`core_gateway_binary` so its
    self-reported version is a valid stand-in for the gateway's (AAASM-4792) —
    see ``api_server.py``.
    """
    missing = missing_build_tools()
    if missing:
        pytest.skip(
            f"live api-server build needs: {', '.join(missing)} — "
            "install them to run the live-core tests"
        )
    return build_api_server(_gateway_family_core_source)


@pytest.fixture(scope="session")
def core_runtime_binary() -> Path:
    """Build ``aa-runtime`` from the core source and return the binary.

    The runtime sidecar is the real SDK→core endpoint (UDS). Skips the
    session's live tests when the build toolchain is incomplete. Honours
    ``AASM_CORE_REF`` for the git ref and ``AASM_CORE_SOURCE_DIR`` to reuse an
    existing checkout, mirroring :func:`core_gateway_binary`.
    """
    missing = missing_build_tools()
    if missing:
        pytest.skip(
            f"live runtime build needs: {', '.join(missing)} — "
            "install them to run the live-core tests"
        )

    ref = os.environ.get("AASM_CORE_REF", DEFAULT_REF)
    clone_dir = Path(tempfile.mkdtemp(prefix="aa-core-src-"))
    source = resolve_core_source(clone_dir / "agent-assembly", ref=ref)
    return build_runtime(source)


@pytest.fixture
def live_gateway(core_gateway_binary: Path) -> Iterator[LiveGateway]:
    """Yield a started, readiness-confirmed ``aa-gateway`` handle.

    Tears the gateway down (terminate + temp cleanup) on test exit.
    """
    gateway = LiveGateway(core_gateway_binary)
    gateway.start()
    try:
        gateway.await_ready()
        yield gateway
    finally:
        gateway.stop()


@pytest.fixture
def live_api_server(core_api_server_binary: Path) -> Iterator[LiveApiServer]:
    """Yield a started, readiness-confirmed ``aa-api-server`` handle.

    Spawned solely so :func:`tests.live.version_preflight.fetch_gateway_version`
    has a real ``GET /api/v1/health`` to read (AAASM-4792) — see
    ``api_server.py`` for why this stands in for ``aa-gateway``'s version.
    """
    server = LiveApiServer(core_api_server_binary)
    server.start()
    try:
        server.await_ready()
        yield server
    finally:
        server.stop()


@pytest.fixture
def live_runtime(core_runtime_binary: Path) -> Iterator[LiveRuntime]:
    """Yield a started, readiness-confirmed ``aa-runtime`` sidecar handle.

    Launches the runtime on a unique UDS, waits until the socket accepts a
    connection, and tears it down (terminate + socket/temp cleanup) on test
    exit.
    """
    runtime = LiveRuntime(core_runtime_binary)
    runtime.start()
    try:
        runtime.await_ready()
        yield runtime
    finally:
        runtime.stop()
