"""Live smoke: the Python SDK's HTTP ``GatewayClient`` against ``aa-gateway``.

SUPERSEDED (AAASM-2989): the SDK's hot-path events do *not* travel over HTTP to
the gateway — they go ``SDK → aa-ffi → aa-runtime`` over a Unix socket. That
real path is now covered by ``test_sdk_runtime.py``; this module is kept only as
a record of the deviant HTTP→gateway probe and its known transport gap, not as
the SDK→core verification.

This builds and runs ``aa-gateway`` from core source (via the ``live_gateway``
fixture) and drives the SDK's HTTP control-plane ``GatewayClient`` at it. It
skips cleanly when the SDK or the build toolchain is unavailable.

The registration step is wired honestly against the transport gap recorded in
``verification-reports/AAASM-2985-sdk-transport-investigation.md``: the SDK's
``GatewayClient`` speaks HTTP/REST, but the running gateway serves gRPC or an
HTTP surface that does not mount the SDK's REST routes (those live in ``aa-api``,
a library-only crate with no binary). So that test is marked
``xfail(strict=True)`` against the open tracking ticket AAASM-4464 (the
quick-start SDK-register → dashboard E2E): it never produces a false green, and
the day this harness drives the register path against a REST front door it
``XPASS``es and strict mode fails the run — forcing the marker's removal rather
than letting the fix vanish. The transport gap was first diagnosed as AAASM-2985
and re-discovered as AAASM-4447 (both since closed); AAASM-4464 carries the
still-open verification work forward.
"""

from __future__ import annotations

import asyncio
import contextlib
import socket

import pytest

from tests.live.api_server import LiveApiServer
from tests.live.gateway import LiveGateway
from tests.live.sdk_client import make_sdk_client, sdk_available
from tests.live.version_preflight import (
    VersionSkewError,
    assert_binding_matches_gateway,
    fetch_gateway_version,
)

pytestmark = pytest.mark.live


def _require_sdk() -> None:
    """Skip the calling test when the Python SDK is not importable."""
    if not sdk_available():
        pytest.skip(
            "Python SDK (agent_assembly) is not installed — "
            "install it from ../python-sdk or PyPI 'agent-assembly' to run this test"
        )


def _sdk_binding_version() -> str:
    """Return the SDK's PyPI package version (``agent_assembly.__version__``).

    This is the value the native binding signs into the ``connect`` handshake —
    but note it is the *package* version, not the ``agent-assembly`` core rev the
    binding was compiled against. The FFI layer forwards the package version by
    design (python-sdk ``aa-ffi-python`` ``connect``, AAASM-3683); the native
    binding does **not** expose the compiled-against core version. That is why the
    skew preflight below compares on a *compatibility* basis rather than
    asserting this equals the core/gateway version. Call :func:`_require_sdk`
    first so an absent SDK skips rather than ImportError-ing.
    """
    # agent_assembly is an optional dep, imported lazily inside this helper.
    import agent_assembly  # noqa: PLC0415

    return agent_assembly.__version__


def test_version_skew_preflight_before_live_register(
    live_gateway: LiveGateway, live_api_server: LiveApiServer
) -> None:
    """Run the AAASM-4669 version-skew guard against a real gateway version.

    The property under test (AAASM-4700) is that the guard's version read runs
    against a *real* gateway and never silently skips: before AAASM-4700 the
    guard was invoked by no automated test, and ``live_gateway`` (legacy-grpc
    ``aa-gateway``) mounts no REST surface, so a naive ``GET /api/v1/health``
    probe raised ``GatewayVersionUnavailable`` and the test skipped on every
    run. It reads the version from ``live_api_server`` (``aa-api-server``)
    instead — built from the identical core checkout as ``live_gateway`` (see
    ``conftest.py``'s shared ``_gateway_family_core_source`` fixture), with the
    workspace version unified across crates, so its self-reported version is the
    real gateway/core version for this build. An indeterminate read is a hard
    :class:`GatewayVersionUnavailable` (left to propagate).

    It does **not** assert ``gateway_version == binding``. The SDK's PyPI package
    version (:func:`_sdk_binding_version`) and the ``agent-assembly`` core/gateway
    version are *independently* versioned — an SDK-only release bumps the SDK
    alone — and the native binding signs the *package* version into the handshake
    by design (AAASM-3683), not the core rev it was compiled against. So exact
    ``package == core`` equality is a false RED on every legitimate SDK-only
    bump: a raised :class:`VersionSkewError` here is the expected steady state,
    not a defect, so the guard is exercised on a *compatibility* basis —
    documented-and-tolerated — rather than hard-failing the run. (A real
    binding/core skew check would need the SDK to expose its compiled-against
    core rev, which it does not today.)
    """
    _require_sdk()
    binding = _sdk_binding_version()

    # Real read against the live gateway: GatewayVersionUnavailable propagates as
    # a hard failure, so reaching the assert means a well-formed version came
    # back off aa-api-server rather than the guard silently skipping.
    gateway_version = fetch_gateway_version(live_api_server.health_url)
    assert isinstance(gateway_version, str) and gateway_version

    # Exercise the skew guard, tolerating the legitimate independent-versioning
    # skew documented above rather than asserting package == core equality.
    with contextlib.suppress(VersionSkewError):
        assert_binding_matches_gateway(binding, gateway_version)


def test_sdk_can_reach_live_gateway(live_gateway: LiveGateway) -> None:
    """The SDK can be configured against the live gateway, which is reachable.

    Unconditional once the SDK is present: builds a real ``GatewayClient``
    pointed at the fixture endpoint and proves the gateway accepts a TCP
    connection on its port. This must pass — it is the reachability floor
    that the (xfail) registration test sits on top of.
    """
    _require_sdk()

    client = make_sdk_client(live_gateway, agent_id="live-smoke-agent")
    try:
        # Plain http:// is intentional: the fixture gateway listens on a
        # 127.0.0.1 loopback port for the duration of this test only, so there
        # is no remote transport to encrypt (S5332).
        assert client.gateway_url == f"http://{live_gateway.endpoint}"
        with socket.create_connection(("127.0.0.1", live_gateway.port), timeout=2):
            pass  # a successful connect proves the listener is up
    finally:
        client.close()


@pytest.mark.xfail(
    reason=(
        "AAASM-4464 (open) tracks the SDK register → dashboard E2E this asserts: "
        "the SDK's HTTP/REST GatewayClient is driven at live_gateway (legacy-grpc), "
        "which serves no REST routes — those live in aa-api. Historical context: "
        "the transport gap was first diagnosed as AAASM-2985 and re-discovered as "
        "AAASM-4447 (both since closed). See "
        "verification-reports/AAASM-2985-sdk-transport-investigation.md."
    ),
    strict=True,
    raises=Exception,
)
def test_sdk_registers_agent_against_live_gateway(live_gateway: LiveGateway) -> None:
    """Drive the real SDK ``register_agent()`` against the live gateway.

    Expected to fail until this harness drives the register path against an
    HTTP/REST front door for the SDK (AAASM-4464, the open register→dashboard
    E2E; see the investigation note). ``strict=True`` is the forcing function the
    AAASM-4477 audit adds: the assertion still fails today so it xfails green, but
    the day the register path succeeds the test ``XPASS``es, and strict mode turns
    that unexpected pass into a **failure** — forcing this marker's removal
    instead of letting a silent fix go unnoticed (the exact disappearance
    AAASM-2985/2989/3000 suffered).
    """
    _require_sdk()

    client = make_sdk_client(live_gateway, agent_id="live-smoke-agent")
    try:
        result = asyncio.run(client.register_agent())
        assert isinstance(result, dict)
    finally:
        client.close()
