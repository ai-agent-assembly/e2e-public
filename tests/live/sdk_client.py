"""Point an installed Python SDK at a running ``LiveGateway``.

The Python SDK (`agent-assembly` / `agent_assembly`) is an *optional*
dependency of this verification repo — it is not in our dependency tree.
This helper imports it lazily so that, when it is absent, the live SDK
test skips cleanly instead of erroring at collection.

It also bridges the transport mismatch documented in
``verification-reports/AAASM-2985-sdk-transport-investigation.md``: the
SDK speaks HTTP/REST and resolves its endpoint from
``AAASM_GATEWAY_URL`` / a ``gateway_url`` argument, while the
``live_gateway`` fixture exposes a bare ``host:port`` gRPC endpoint. We
turn the fixture endpoint into the ``http://host:port`` URL shape the
SDK's resolver expects and hand back a configured ``GatewayClient``.
"""

from __future__ import annotations

import importlib.util
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tests.live.gateway import LiveGateway

#: Env var the SDK resolver reads for its gateway URL
#: (``agent_assembly.core.gateway_resolver.ENV_GATEWAY_URL``).
SDK_GATEWAY_URL_ENV = "AAASM_GATEWAY_URL"


def sdk_available() -> bool:
    """Return True when the Python SDK package can be imported.

    Probes for the ``agent_assembly`` module without importing it, so a
    caller can skip cleanly when the SDK / its toolchain is not installed.
    """
    return importlib.util.find_spec("agent_assembly") is not None


def gateway_http_url(gateway: LiveGateway) -> str:
    """Render a ``LiveGateway`` endpoint as the ``http://host:port`` URL.

    The fixture's :pyattr:`LiveGateway.endpoint` is a bare ``host:port``
    (its listener is gRPC). The SDK resolver expects a URL with a scheme;
    we prefix ``http://`` so the value flows through
    ``resolve_gateway_url`` and ``httpx`` unchanged. Reachability of the
    SDK's REST routes at this URL is the open gap (see the investigation
    note) — this helper only produces the address the SDK would dial.
    """
    # Plain http:// is intentional and safe here: ``gateway.endpoint`` is a
    # 127.0.0.1 loopback host:port spun up by the live-test fixture in-process,
    # never a remote endpoint, so there is no transport to secure (S5332).
    return f"http://{gateway.endpoint}"


def make_sdk_client(gateway: LiveGateway, *, agent_id: str = "live-smoke-agent"):  # noqa: ANN201
    """Build an SDK ``GatewayClient`` pointed at *gateway*.

    Imports ``agent_assembly`` lazily (call :func:`sdk_available` first to
    decide whether to skip). The returned client is the real SDK type, so
    a test exercises the genuine SDK code path — not a stub.

    :param agent_id: agent identifier to register under.
    :returns: a configured ``agent_assembly.client.gateway.GatewayClient``.
    """
    from agent_assembly.client.gateway import GatewayClient  # noqa: PLC0415 — optional dep

    return GatewayClient(gateway_url=gateway_http_url(gateway), agent_id=agent_id)
