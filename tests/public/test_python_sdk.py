"""Smoke tests for the Agent Assembly Python SDK."""

from __future__ import annotations

import importlib.util

import pytest

from tests.public.conftest import skip_if_package_missing

COMPONENT = "python-sdk"

# The PyO3 native extension is published as a submodule of the package
# (`module-name = "agent_assembly._core"` in python-sdk/pyproject.toml).
NATIVE_MODULE = "agent_assembly._core"


def _require_native_module() -> object:
    """Import the compiled native extension or skip when it is absent.

    The wheel ships in two flavours: pure-Python (no native ext) and
    native-accelerated. Skip cleanly when the `_core` extension was not
    built so the source/pure-Python install path stays green.
    """
    skip_if_package_missing("agent_assembly")
    if importlib.util.find_spec(NATIVE_MODULE) is None:
        pytest.skip(
            f"[{COMPONENT}] native extension {NATIVE_MODULE!r} not built "
            "(pure-Python install) — skipping native-binding check"
        )
    return importlib.import_module(NATIVE_MODULE)


@pytest.mark.sdk
def test_python_sdk_importable() -> None:
    """agent_assembly package can be imported."""
    skip_if_package_missing("agent_assembly")
    import agent_assembly  # noqa: F401 — import is the smoke assertion

    assert hasattr(agent_assembly, "__version__"), (
        f"[{COMPONENT}] agent_assembly.__version__ not found — unexpected package state"
    )


@pytest.mark.sdk
def test_python_sdk_version_string() -> None:
    """agent_assembly.__version__ is a non-empty string."""
    skip_if_package_missing("agent_assembly")
    import agent_assembly

    version = agent_assembly.__version__
    assert isinstance(version, str) and version, (
        f"[{COMPONENT}] Expected non-empty version string, got {version!r}"
    )


@pytest.mark.sdk
def test_python_sdk_public_exports() -> None:
    """Core public names are accessible from the top-level package."""
    skip_if_package_missing("agent_assembly")
    import agent_assembly

    expected = ["init_assembly", "AssemblyContext", "AssemblyError"]
    missing = [name for name in expected if not hasattr(agent_assembly, name)]
    assert not missing, (
        f"[{COMPONENT}] Missing public exports: {missing}"
    )
