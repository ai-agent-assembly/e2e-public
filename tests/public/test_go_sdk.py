"""Smoke tests for the Agent Assembly Go SDK.

These tests exercise the *install matrix* for the Go SDK: a tiny consumer module
is built and run against the SDK acquired two ways — from the local source
checkout (via a ``replace`` directive) and from the public module proxy (via
``go get``). Beyond plain module resolution, the build is asserted to compile
and link the cgo/FFI shim (``internal/ffi``) that the ``assembly`` package pulls
in transitively, which is what makes a Go consumer a real install rather than a
pure-Go stub.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap

import pytest

from tests.public.conftest import skip_if_binary_missing

COMPONENT = "go-sdk"

# Canonical published module path, served by the Go module proxy.
MODULE_PATH = "github.com/ai-agent-assembly/go-sdk"

# The native library the cgo C-ABI bridge links against when the ``aa_ffi_go``
# build tag is active (``#cgo LDFLAGS: -laa_ffi_go`` in cgo_bridge.go).
FFI_NATIVE_LIB = "aa_ffi_go"


def _ffi_shim_package(module_path: str) -> str:
    """Return the internal cgo/FFI shim package import path for *module_path*.

    A consumer build whose dependency graph includes this package has linked the
    FFI shim, not merely resolved the module.
    """
    return f"{module_path}/internal/ffi"


_GO_MAIN = textwrap.dedent("""\
    package main

    import (
        "fmt"
        "{module_path}/assembly"
    )

    func main() {{
        // Verify the package is importable and the sentinel error is accessible.
        fmt.Println(assembly.ErrBinaryNotFound != nil)
    }}
""")

_GO_MOD_SOURCE = textwrap.dedent("""\
    module smoke

    go 1.22

    require {module_path} v0.0.0

    replace {module_path} => {sdk_path}
""")

_GO_MOD_PROXY = textwrap.dedent("""\
    module smoke

    go 1.22
""")


def _go_sdk_path() -> str | None:
    """Return the local go-sdk directory if it exists next to this repo.

    The checkout may live two or three directories up depending on whether the
    tests run from the main repo or an isolated git worktree.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for up in ("../../..", "../../../.."):
        resolved = os.path.normpath(os.path.join(here, up, "go-sdk"))
        if os.path.isfile(os.path.join(resolved, "go.mod")):
            return resolved
    return None


def _module_path_of(sdk_path: str) -> str:
    """Read the declared module path from a local go-sdk checkout's go.mod.

    The local checkout may be a stale fork whose declared module path differs
    in case (e.g. ``github.com/AI-agent-assembly/...``) from the canonical
    lowercase published path. ``replace`` directives must match the SDK's own
    declared path, so we honour whatever the checkout declares.
    """
    with open(os.path.join(sdk_path, "go.mod"), encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line.startswith("module "):
                return line.split(None, 1)[1].strip()
    raise ValueError(f"[{COMPONENT}] no module directive in {sdk_path}/go.mod")


def _go_env() -> dict[str, str]:
    """Return a go-friendly environment with module mode forced on.

    ``GOFLAGS=-mod=mod`` lets ``go get`` / ``go build`` update go.mod and go.sum
    inside the throwaway consumer module without a pre-seeded lock file.
    """
    env = dict(os.environ)
    env["GOFLAGS"] = "-mod=mod"
    env.setdefault("GO111MODULE", "on")
    # The cgo/FFI shim path requires cgo; force it on so the shim is part of the
    # build graph rather than silently dropped on a CGO_ENABLED=0 runner.
    env["CGO_ENABLED"] = "1"
    return env


def _write_source_consumer(tmp: str, sdk_path: str, module_path: str) -> None:
    """Write a consumer module wired to the local SDK checkout via ``replace``."""
    go_mod = _GO_MOD_SOURCE.format(module_path=module_path, sdk_path=sdk_path)
    with open(os.path.join(tmp, "go.mod"), "w") as f:
        f.write(go_mod)
    with open(os.path.join(tmp, "main.go"), "w") as f:
        f.write(_GO_MAIN.format(module_path=module_path))


def _write_proxy_consumer(tmp: str) -> None:
    """Write a consumer module that pulls the SDK from the module proxy."""
    with open(os.path.join(tmp, "go.mod"), "w") as f:
        f.write(_GO_MOD_PROXY)
    with open(os.path.join(tmp, "main.go"), "w") as f:
        f.write(_GO_MAIN.format(module_path=MODULE_PATH))
    # Resolve the SDK (and its transitive deps) from the proxy.
    result = subprocess.run(
        ["go", "get", f"{MODULE_PATH}/assembly@latest"],
        capture_output=True,
        text=True,
        cwd=tmp,
        env=_go_env(),
    )
    if result.returncode != 0:
        pytest.skip(
            f"[{COMPONENT}] go get from module proxy failed (offline or proxy "
            f"unreachable) — classification: external_flake\nstderr: {result.stderr.strip()}"
        )


def _consumer(acquisition: str, tmp: str) -> str:
    """Materialize a consumer module for the given acquisition path.

    Returns the SDK module import path used by the consumer (which may differ
    in case between the source checkout and the canonical proxy path).
    """
    if acquisition == "source":
        sdk_path = _go_sdk_path()
        if sdk_path is None:
            pytest.skip(
                f"[{COMPONENT}] Local go-sdk directory not found — clone "
                "https://github.com/ai-agent-assembly/go-sdk alongside this repo "
                "to run the source-path test"
            )
        module_path = _module_path_of(sdk_path)
        _write_source_consumer(tmp, sdk_path, module_path)
        return module_path
    if acquisition == "proxy":
        _write_proxy_consumer(tmp)
        return MODULE_PATH
    raise ValueError(acquisition)  # pragma: no cover - guarded by parametrization


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
def test_go_sdk_links_ffi_shim(acquisition: str) -> None:
    """Consumer build compiles and links the cgo/FFI shim, not just the module.

    A successful ``go build`` whose dependency graph includes the internal FFI
    shim package proves the shim is compiled into the consumer binary. Plain
    module resolution would not pull the shim into the link.
    """
    skip_if_binary_missing("go")

    with tempfile.TemporaryDirectory() as tmp:
        module_path = _consumer(acquisition, tmp)
        ffi_shim_package = _ffi_shim_package(module_path)
        env = _go_env()

        # The FFI shim must be in the build's dependency graph.
        deps = subprocess.run(
            ["go", "list", "-deps", "."],
            capture_output=True,
            text=True,
            cwd=tmp,
            env=env,
        )
        assert deps.returncode == 0, (
            f"[{COMPONENT}/{acquisition}] go list -deps failed "
            f"(exit {deps.returncode})\nstderr: {deps.stderr.strip()}"
        )
        assert ffi_shim_package in deps.stdout.split(), (
            f"[{COMPONENT}/{acquisition}] FFI shim package {ffi_shim_package!r} "
            f"absent from consumer build graph — the SDK did not pull in its "
            f"cgo/FFI shim. Deps:\n{deps.stdout.strip()}"
        )

        # And the build that includes it must compile + link successfully.
        build = subprocess.run(
            ["go", "build", "./..."],
            capture_output=True,
            text=True,
            cwd=tmp,
            env=env,
        )
        assert build.returncode == 0, (
            f"[{COMPONENT}/{acquisition}] go build failed (exit {build.returncode})\n"
            f"stdout: {build.stdout.strip()}\nstderr: {build.stderr.strip()}"
        )


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
def test_go_sdk_cgo_abi_binding_is_wired(acquisition: str) -> None:
    """The ``aa_ffi_go`` cgo C-ABI bridge links against the native library.

    Building with ``-tags aa_ffi_go`` activates the cgo bridge whose
    ``#cgo LDFLAGS: -laa_ffi_go`` directive forces the linker to resolve the
    native ``libaa_ffi_go``. We do not ship that Rust artifact here, so the
    expected outcome is either a clean link (native lib present) or a link-stage
    failure that specifically names the native library — both of which prove the
    cgo bridge is genuinely wired rather than stubbed out. A *compile* error or a
    module-resolution error would mean the shim is broken, and fails the test.
    """
    skip_if_binary_missing("go")

    with tempfile.TemporaryDirectory() as tmp:
        _consumer(acquisition, tmp)
        env = _go_env()

        result = subprocess.run(
            ["go", "build", "-tags", "aa_ffi_go", "./..."],
            capture_output=True,
            text=True,
            cwd=tmp,
            env=env,
        )
        combined = f"{result.stdout}\n{result.stderr}"

        if result.returncode == 0:
            # Native lib was available and the cgo bridge linked cleanly.
            return

        # Otherwise the only acceptable failure is the linker not finding the
        # native library — that is the cgo bridge firing its LDFLAGS, i.e. the
        # shim is wired. Anything else (compile error, unresolved import,
        # missing module) is a real defect.
        assert FFI_NATIVE_LIB in combined, (
            f"[{COMPONENT}/{acquisition}] cgo C-ABI build failed for a reason "
            f"other than the missing native '{FFI_NATIVE_LIB}' library — the FFI "
            f"shim may be broken.\nstdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}"
        )
        assert ("library" in combined and "not found" in combined) or "ld:" in combined, (
            f"[{COMPONENT}/{acquisition}] expected a linker-stage failure naming "
            f"'{FFI_NATIVE_LIB}', but the failure does not look like a link "
            f"error.\nstdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
def test_go_sdk_runs_smoke(acquisition: str) -> None:
    """Consumer ``go run`` executes and a public symbol is usable at runtime."""
    skip_if_binary_missing("go")

    with tempfile.TemporaryDirectory() as tmp:
        _consumer(acquisition, tmp)

        result = subprocess.run(
            ["go", "run", "."],
            capture_output=True,
            text=True,
            cwd=tmp,
            env=_go_env(),
        )
        assert result.returncode == 0, (
            f"[{COMPONENT}/{acquisition}] go run failed (exit {result.returncode})\n"
            f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )
        assert result.stdout.strip() == "true", (
            f"[{COMPONENT}/{acquisition}] Expected 'true' from smoke run "
            f"(assembly.ErrBinaryNotFound != nil), got: {result.stdout.strip()!r}"
        )
