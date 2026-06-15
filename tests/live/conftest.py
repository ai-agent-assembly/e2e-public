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

from tests.live.build import build_gateway, missing_build_tools
from tests.live.core_source import DEFAULT_REF, resolve_core_source
from tests.live.gateway import LiveGateway


@pytest.fixture(scope="session")
def core_gateway_binary() -> Path:
    """Build ``aa-gateway`` from the core source and return the binary.

    Skips the session's live tests when the build toolchain is
    incomplete. Honours ``AASM_CORE_REF`` for the git ref to clone and
    ``AASM_CORE_SOURCE_DIR`` to reuse an existing checkout.
    """
    missing = missing_build_tools()
    if missing:
        pytest.skip(
            f"live gateway build needs: {', '.join(missing)} — "
            "install them to run the live-core tests"
        )

    ref = os.environ.get("AASM_CORE_REF", DEFAULT_REF)
    # Not a context-managed tempdir: when we clone, the built binary lives
    # under this directory and must survive for the whole test session.
    # pytest's tmp_path_factory would also work, but a plain mkdtemp keeps
    # this fixture independent of the temp-path plugin.
    clone_dir = Path(tempfile.mkdtemp(prefix="aa-core-src-"))
    source = resolve_core_source(clone_dir / "agent-assembly", ref=ref)
    return build_gateway(source)


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
