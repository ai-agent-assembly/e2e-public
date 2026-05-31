"""Smoke tests for the Agent Assembly Go SDK."""

from __future__ import annotations

import os
import subprocess
import textwrap

import pytest

from tests.public.conftest import skip_if_binary_missing

COMPONENT = "go-sdk"
MODULE_PATH = "github.com/AI-agent-assembly/go-sdk"

_GO_MAIN = textwrap.dedent("""\
    package main

    import (
        "fmt"
        "github.com/AI-agent-assembly/go-sdk/assembly"
    )

    func main() {
        // Verify the package is importable and the sentinel error is accessible.
        fmt.Println(assembly.ErrBinaryNotFound != nil)
    }
""")

_GO_MOD_TEMPLATE = textwrap.dedent("""\
    module smoke

    go 1.22

    require {module_path} v0.0.0

    replace {module_path} => {sdk_path}
""")


def _go_sdk_path() -> str | None:
    """Return the local go-sdk directory if it exists next to this repo."""
    candidate = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..", "go-sdk",
    )
    resolved = os.path.normpath(candidate)
    return resolved if os.path.isdir(os.path.join(resolved, "go.mod")) else None


@pytest.mark.sdk
def test_go_sdk_builds() -> None:
    """Go SDK can be imported and the package compiles without errors."""
    skip_if_binary_missing("go")

    sdk_path = _go_sdk_path()
    if sdk_path is None:
        pytest.skip(
            f"[{COMPONENT}] Local go-sdk directory not found — "
            "clone https://github.com/AI-agent-assembly/go-sdk alongside this repo to run this test"
        )

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        go_mod = _GO_MOD_TEMPLATE.format(module_path=MODULE_PATH, sdk_path=sdk_path)
        with open(os.path.join(tmp, "go.mod"), "w") as f:
            f.write(go_mod)
        with open(os.path.join(tmp, "main.go"), "w") as f:
            f.write(_GO_MAIN)

        result = subprocess.run(
            ["go", "build", "./..."],
            capture_output=True,
            text=True,
            cwd=tmp,
        )
        assert result.returncode == 0, (
            f"[{COMPONENT}] go build failed (exit {result.returncode})\n"
            f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )


@pytest.mark.sdk
def test_go_sdk_runs_smoke() -> None:
    """Go SDK smoke program runs without panicking."""
    skip_if_binary_missing("go")

    sdk_path = _go_sdk_path()
    if sdk_path is None:
        pytest.skip(
            f"[{COMPONENT}] Local go-sdk directory not found — "
            "clone https://github.com/AI-agent-assembly/go-sdk alongside this repo to run this test"
        )

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        go_mod = _GO_MOD_TEMPLATE.format(module_path=MODULE_PATH, sdk_path=sdk_path)
        with open(os.path.join(tmp, "go.mod"), "w") as f:
            f.write(go_mod)
        with open(os.path.join(tmp, "main.go"), "w") as f:
            f.write(_GO_MAIN)

        result = subprocess.run(
            ["go", "run", "."],
            capture_output=True,
            text=True,
            cwd=tmp,
        )
        assert result.returncode == 0, (
            f"[{COMPONENT}] go run failed (exit {result.returncode})\n"
            f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )
        assert result.stdout.strip() == "true", (
            f"[{COMPONENT}] Expected 'true' from smoke run, got: {result.stdout.strip()!r}"
        )
