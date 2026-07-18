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
    assert not missing, f"[{COMPONENT}] Missing public exports: {missing}"


@pytest.mark.sdk
def test_python_sdk_native_binding_loads() -> None:
    """The compiled PyO3 `_core` extension loads from a platform binary.

    Proves the install is native-accelerated, not merely pure-Python: the
    extension module must originate from a compiled artifact (`.so`/`.pyd`),
    and must expose its native-backed symbols.
    """
    core = _require_native_module()

    origin = getattr(core, "__file__", None)
    assert origin is not None and origin.endswith((".so", ".pyd", ".dylib")), (
        f"[{COMPONENT}] {NATIVE_MODULE} did not load from a compiled extension; __file__={origin!r}"
    )

    expected_symbols = ["RuntimeClient", "GovernanceEvent"]
    missing = [name for name in expected_symbols if not hasattr(core, name)]
    assert not missing, f"[{COMPONENT}] native extension loaded but missing symbols: {missing}"


@pytest.mark.sdk
def test_python_sdk_native_binding_required() -> None:
    """The native ``_core`` extension MUST be present — a skip is NOT acceptable.

    The strict, release-readiness counterpart to
    ``test_python_sdk_native_binding_loads`` (which skips cleanly for the
    development pure-Python path). AAASM-4477's whole point is that a
    "detect condition X, then *skip* when X is present" test lets a real defect
    pass green forever — so this one *asserts* the binding is present instead of
    skipping when it is absent.

    An SDK that is not installed at all is a legitimate environment skip; only a
    *present-but-pure-Python* install is the defect this asserts on.
    """
    skip_if_package_missing("agent_assembly")

    assert importlib.util.find_spec(NATIVE_MODULE) is not None, (
        f"[{COMPONENT}] native extension {NATIVE_MODULE!r} is absent — release "
        "install is pure-Python only"
    )
    core = importlib.import_module(NATIVE_MODULE)
    origin = getattr(core, "__file__", None)
    assert origin is not None and origin.endswith((".so", ".pyd", ".dylib")), (
        f"[{COMPONENT}] {NATIVE_MODULE} did not load from a compiled extension; "
        f"__file__={origin!r}"
    )


@pytest.mark.sdk
def test_python_sdk_functional_install() -> None:
    """Core public API is actually usable, not just attribute-present.

    A functional install must expose a callable initializer and a usable
    exception hierarchy — beyond mere `hasattr` presence checks.
    """
    skip_if_package_missing("agent_assembly")
    import agent_assembly

    assert callable(agent_assembly.init_assembly), (
        f"[{COMPONENT}] init_assembly is not callable: {agent_assembly.init_assembly!r}"
    )

    error_cls = agent_assembly.AssemblyError
    assert isinstance(error_cls, type) and issubclass(error_cls, Exception), (
        f"[{COMPONENT}] AssemblyError is not an exception class: {error_cls!r}"
    )

    # The exception must be raisable and catchable as a real exception.
    with pytest.raises(agent_assembly.AssemblyError):
        raise agent_assembly.AssemblyError("functional install probe")
