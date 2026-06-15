"""Smoke tests for the Agent Assembly Node.js/TypeScript SDK."""

from __future__ import annotations

import subprocess
import textwrap

import pytest

from tests.public.conftest import skip_if_binary_missing

COMPONENT = "node-sdk"
PACKAGE = "@agent-assembly/sdk"

_ESM_SMOKE = textwrap.dedent("""\
    import { initAssembly, ENFORCEMENT_MODES } from '@agent-assembly/sdk';
    const hasInit = typeof initAssembly === 'function';
    const hasModes = typeof ENFORCEMENT_MODES === 'object' && ENFORCEMENT_MODES !== null;
    if (!hasInit || !hasModes) {
      const msg = `[${COMPONENT}] unexpected exports: initAssembly=${typeof initAssembly} `
        + `ENFORCEMENT_MODES=${typeof ENFORCEMENT_MODES}\\n`;
      process.stderr.write(msg);
      process.exit(1);
    }
    console.log('ok');
""".replace("${COMPONENT}", COMPONENT))


def _node_has_package() -> bool:
    """Return True when @agent-assembly/sdk can be resolved by node."""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", f"import '{PACKAGE}'"],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


@pytest.mark.sdk
def test_node_sdk_importable() -> None:
    """@agent-assembly/sdk can be imported via ESM."""
    skip_if_binary_missing("node")
    if not _node_has_package():
        pytest.skip(f"npm package {PACKAGE!r} not installed — run 'npm install {PACKAGE}'")


@pytest.mark.sdk
def test_node_sdk_public_exports() -> None:
    """initAssembly and ENFORCEMENT_MODES are exported from the package."""
    skip_if_binary_missing("node")
    if not _node_has_package():
        pytest.skip(f"npm package {PACKAGE!r} not installed — run 'npm install {PACKAGE}'")

    result = subprocess.run(
        ["node", "--input-type=module", "-e", _ESM_SMOKE],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT}] ESM smoke failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    assert "ok" in result.stdout, (
        f"[{COMPONENT}] Expected 'ok' in output, got: {result.stdout.strip()!r}"
    )
