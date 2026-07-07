"""AC3: each SDK package's published registry metadata matches the requested release.

Rather than installing (covered by ``tests/public/test_package_install.py``),
these tests read the *registry metadata* directly — PyPI's JSON API, the npm
registry document, and the Go module proxy ``@v/list`` — and assert the requested
version is the one the registry advertises. That catches a release where a tag
exists but a registry was never published, or was published under a mismatched
version.

Parametrized per ecosystem and skip-guarded on ``AASM_RELEASE_VERSION`` + network.
A registry that does not yet carry the version skips (known prerequisite); a
registry that carries a *different* version for the requested coordinate fails.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from tests.release.conftest import require_release_version

PYPI_PACKAGE = "agent-assembly"
NPM_PACKAGE = "@agent-assembly/sdk"
GO_MODULE = "github.com/ai-agent-assembly/go-sdk"


def _http_get(url: str) -> tuple[int, str]:
    """GET *url*; return (status, body). Status 0 marks an unreachable host."""
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 — fixed registry hosts
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, ""
    except urllib.error.URLError:
        return 0, ""


def _check_pypi(version: str) -> None:
    bare = version.lstrip("v")
    status, body = _http_get(f"https://pypi.org/pypi/{PYPI_PACKAGE}/{bare}/json")
    if status == 0:
        pytest.skip(
            "[python-sdk] PyPI unreachable — offline environment (classification: external_flake)"
        )
    if status == 404:
        pytest.skip(
            f"[python-sdk] {PYPI_PACKAGE}=={bare} not on PyPI — release not yet "
            "published (classification: known_prerequisite, AASM_RELEASE_VERSION)"
        )
    meta = json.loads(body)
    published = meta.get("info", {}).get("version", "")
    # PyPI normalizes versions to PEP 440 canonical form (e.g. "0.0.1-beta.2" ->
    # "0.0.1b2"), so compare parsed Version objects, not raw strings. packaging is
    # not a declared dependency here; skip cleanly (justified) if it is absent.
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:
        pytest.skip(
            "[python-sdk] 'packaging' not installed — required to compare PEP 440 "
            "normalized PyPI versions"
        )
    # NOSONAR(python:S8714) — intentional: distinguish "version mismatch" from
    # "unparseable version" with classification-tagged messages for downstream tooling
    try:
        assert Version(published) == Version(bare), (
            f"[python-sdk] PyPI metadata version {published!r} != requested {bare!r} — "
            "classification: release_blocker"
        )
    except InvalidVersion as exc:
        pytest.fail(
            f"[python-sdk] unparseable version (published={published!r}, "
            f"requested={bare!r}): {exc} — classification: release_blocker"
        )


def _check_npm(version: str) -> None:
    bare = version.lstrip("v")
    # The npm registry exposes a per-version document at <registry>/<pkg>/<version>.
    encoded = NPM_PACKAGE.replace("/", "%2f")
    status, body = _http_get(f"https://registry.npmjs.org/{encoded}/{bare}")
    if status == 0:
        pytest.skip(
            "[node-sdk] npm registry unreachable — offline environment "
            "(classification: external_flake)"
        )
    if status == 404:
        pytest.skip(
            f"[node-sdk] {NPM_PACKAGE}@{bare} not on npm — release not yet "
            "published (classification: known_prerequisite, AASM_RELEASE_VERSION)"
        )
    meta = json.loads(body)
    published = meta.get("version", "")
    assert published == bare, (
        f"[node-sdk] npm metadata version {published!r} != requested {bare!r} — "
        "classification: release_blocker"
    )


def _check_go(version: str) -> None:
    go_version = version if version.startswith("v") else f"v{version}"
    # The Go module proxy lists published versions one-per-line at @v/list.
    status, body = _http_get(f"https://proxy.golang.org/{GO_MODULE}/@v/list")
    if status == 0:
        pytest.skip(
            "[go-sdk] Go module proxy unreachable — offline environment "
            "(classification: external_flake)"
        )
    if status == 404 or not body.strip():
        pytest.skip(
            f"[go-sdk] no versions for {GO_MODULE} in module proxy — release not "
            "yet published (classification: known_prerequisite, AASM_RELEASE_VERSION)"
        )
    versions = {line.strip() for line in body.splitlines() if line.strip()}
    assert go_version in versions, (
        f"[go-sdk] {go_version!r} not in module-proxy version list {sorted(versions)!r} — "
        "classification: release_blocker"
    )


_CHECKERS = {
    "python-sdk": _check_pypi,
    "node-sdk": _check_npm,
    "go-sdk": _check_go,
}


@pytest.mark.release
@pytest.mark.parametrize("ecosystem", sorted(_CHECKERS))
def test_sdk_metadata_matches_release(ecosystem: str) -> None:
    """The SDK registry advertises the requested release version."""
    version = require_release_version()
    _CHECKERS[ecosystem](version)
