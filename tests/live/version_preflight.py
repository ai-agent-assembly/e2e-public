"""Preflight guard: SDK binding version vs live gateway version (AAASM-4669).

Follow-up to AAASM-4667. When an SDK's native binding is built against a
different ``agent-assembly`` revision than the live gateway it registers with,
the gateway's post-AAASM-3866 registration handshake rejects the mismatched
``Register`` call with a cryptic ``missing registration_nonce — call
RequestChallenge before Register`` — a *version skew* masquerading as an interop
break. That exact confusion is what AAASM-4667 spent effort chasing down: a
skewed binding, not a broken protocol.

This module turns that skew into an explicit, fail-fast diagnostic to run
*before* driving a real ``register`` against a live gateway. It reads the
gateway's self-reported version from ``GET /api/v1/health``
(``HealthResponse.version`` — the gateway crate's ``CARGO_PKG_VERSION``),
compares it to the SDK binding version the driver signs into the native
``connect``, and raises :class:`VersionSkewError` naming both versions and the
remedy — instead of letting the confusing nonce error surface downstream.

It is a diagnostic guard, not a product behaviour change: on a matched pair it
does nothing. Stdlib-only (``urllib``) so it adds no dependency to the zero-dep
harness, and every failure it raises is a *hard* error (never a silent skip),
consistent with this harness's "a diagnosed defect stays red" policy.
"""

from __future__ import annotations

import json
import urllib.request

#: REST path the gateway serves its self-reported version on. The JSON body is
#: wire-compatible with ``aa_api::routes::health::HealthResponse``; its
#: ``version`` field is the gateway crate's ``CARGO_PKG_VERSION``. Served by the
#: gateway's local/REST surface — a gRPC-only ``legacy-grpc`` listener does not
#: mount it, which is why the caller supplies the HTTP origin explicitly.
HEALTH_PATH = "/api/v1/health"


class VersionSkewError(RuntimeError):
    """The SDK binding and the live gateway report different versions.

    Raised by :func:`assert_binding_matches_gateway`. Its message names both
    versions and the remedy (rebuild the native binding from the pinned rev), so
    a live-register failure reads as the version skew it is rather than the
    gateway's downstream ``missing registration_nonce`` error.
    """


class GatewayVersionUnavailable(RuntimeError):
    """The gateway's ``/api/v1/health`` version could not be determined.

    Distinct from :class:`VersionSkewError`: the preflight could not *read* the
    gateway version (endpoint unreachable, non-200, malformed body, or missing
    ``version`` field), so it cannot make a match/skew judgement. Kept separate
    so an indeterminate probe never masquerades as a matched version — the
    caller decides whether that is fatal or a justified skip.
    """


def fetch_gateway_version(base_url: str, *, timeout: float = 5.0) -> str:
    """Return the gateway's self-reported version from ``GET /api/v1/health``.

    *base_url* is the gateway's HTTP origin (e.g. ``http://127.0.0.1:7391``);
    :data:`HEALTH_PATH` is appended. Raises :class:`GatewayVersionUnavailable`
    when the endpoint is unreachable, errors, or the JSON body lacks a non-empty
    string ``version`` — so an indeterminate probe never passes as a matched
    version.
    """
    url = base_url.rstrip("/") + HEALTH_PATH
    try:
        # http:// to a loopback test gateway is intentional (no remote transport
        # to encrypt); S310 is not applicable to this local health probe.
        with urllib.request.urlopen(url, timeout=timeout) as resp:  # noqa: S310
            payload = resp.read()
    except OSError as exc:
        raise GatewayVersionUnavailable(
            f"could not reach gateway health endpoint {url}: {exc}"
        ) from exc
    try:
        body = json.loads(payload)
    except ValueError as exc:
        raise GatewayVersionUnavailable(
            f"gateway health endpoint {url} returned a non-JSON body"
        ) from exc
    version = body.get("version") if isinstance(body, dict) else None
    if not isinstance(version, str) or not version:
        raise GatewayVersionUnavailable(
            f"gateway health endpoint {url} returned no 'version' field"
        )
    return version


def assert_binding_matches_gateway(binding_version: str, gateway_version: str) -> None:
    """Raise :class:`VersionSkewError` when the two versions differ.

    Compares the SDK binding version (what the driver signs into the native
    ``connect``) against the gateway's ``/api/v1/health`` version. On a mismatch
    the error names both and points at the fix; a match returns ``None``.
    """
    if binding_version != gateway_version:
        raise VersionSkewError(
            f"SDK binding {binding_version} != gateway {gateway_version}; "
            "rebuild the native binding from the pinned agent-assembly rev before "
            "running a live register. A skewed binding is rejected by the "
            "post-AAASM-3866 handshake as a cryptic 'missing registration_nonce' "
            "error (AAASM-4667), not an obvious version mismatch."
        )


def preflight_live_register(
    binding_version: str, gateway_base_url: str, *, timeout: float = 5.0
) -> str:
    """Fail fast before a live register when the binding and gateway skew.

    Convenience composition of :func:`fetch_gateway_version` and
    :func:`assert_binding_matches_gateway`: read the gateway version from
    *gateway_base_url*'s ``/api/v1/health`` and assert it matches
    *binding_version*. Returns the agreed version on success; raises
    :class:`VersionSkewError` on skew or :class:`GatewayVersionUnavailable` when
    the gateway version is indeterminate.
    """
    gateway_version = fetch_gateway_version(gateway_base_url, timeout=timeout)
    assert_binding_matches_gateway(binding_version, gateway_version)
    return gateway_version
