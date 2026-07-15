"""Offline tests for the live-register version-skew preflight (AAASM-4669).

These exercise the preflight guard in :mod:`tests.live.version_preflight`
without a live gateway or any toolchain — the HTTP probe is stubbed — so they
run in a bare ``-m live`` selection with nothing built, mirroring the offline
locator tests in :mod:`tests.live.test_sdk_drivers`.

They pin the load-bearing contract AAASM-4667 asked for: a binding/gateway
version mismatch must fail *fast and legibly* (naming both versions and the
rebuild remedy) rather than deferring to the gateway's cryptic
``missing registration_nonce`` error, and an indeterminate gateway version must
be a distinct, explicit failure rather than a false "matched" pass.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from tests.live import version_preflight
from tests.live.version_preflight import (
    GatewayVersionUnavailable,
    VersionSkewError,
    assert_binding_matches_gateway,
    fetch_gateway_version,
    preflight_live_register,
)

pytestmark = [pytest.mark.live, pytest.mark.sdk]


class _FakeResponse(io.BytesIO):
    """Minimal ``urlopen`` stand-in: a context manager whose ``read()`` returns
    the stubbed body."""

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _stub_urlopen(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    """Point the preflight's ``urlopen`` at a fixed JSON body."""
    monkeypatch.setattr(
        version_preflight.urllib.request,
        "urlopen",
        lambda _url, timeout=0: _FakeResponse(body),
    )


def test_matched_versions_pass() -> None:
    """A binding that matches the gateway version raises nothing."""
    assert assert_binding_matches_gateway("0.0.1", "0.0.1") is None


def test_skew_raises_with_actionable_message() -> None:
    """A mismatch raises VersionSkewError naming both versions and the remedy."""
    with pytest.raises(VersionSkewError) as exc:
        assert_binding_matches_gateway("0.0.2", "0.0.1")
    message = str(exc.value)
    assert "0.0.2" in message and "0.0.1" in message
    # The whole point of AAASM-4669: surface the skew and the fix, and name the
    # cryptic error it would otherwise masquerade as.
    assert "rebuild" in message.lower()
    assert "registration_nonce" in message


def test_fetch_parses_health_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """``fetch_gateway_version`` returns the ``version`` field from the body."""
    _stub_urlopen(monkeypatch, json.dumps({"status": "ok", "version": "1.2.3"}).encode())
    assert fetch_gateway_version("http://127.0.0.1:7391") == "1.2.3"


def test_fetch_unreachable_is_indeterminate(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable endpoint is GatewayVersionUnavailable, not a false match."""

    def _boom(_url: str, timeout: float = 0) -> None:
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(version_preflight.urllib.request, "urlopen", _boom)
    with pytest.raises(GatewayVersionUnavailable):
        fetch_gateway_version("http://127.0.0.1:7391")


def test_fetch_missing_version_field_is_indeterminate(monkeypatch: pytest.MonkeyPatch) -> None:
    """A health body without a ``version`` field never passes as a match."""
    _stub_urlopen(monkeypatch, json.dumps({"status": "ok"}).encode())
    with pytest.raises(GatewayVersionUnavailable):
        fetch_gateway_version("http://127.0.0.1:7391")


def test_preflight_end_to_end_skew(monkeypatch: pytest.MonkeyPatch) -> None:
    """The composed preflight fetches then fails fast on a skewed binding."""
    _stub_urlopen(monkeypatch, json.dumps({"version": "0.0.1"}).encode())
    with pytest.raises(VersionSkewError):
        preflight_live_register("0.0.2", "http://127.0.0.1:7391")


def test_preflight_end_to_end_match_returns_version(monkeypatch: pytest.MonkeyPatch) -> None:
    """On a matched pair the preflight returns the agreed version."""
    _stub_urlopen(monkeypatch, json.dumps({"version": "0.0.1"}).encode())
    assert preflight_live_register("0.0.1", "http://127.0.0.1:7391") == "0.0.1"
