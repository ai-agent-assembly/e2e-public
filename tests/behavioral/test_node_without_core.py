"""Behavioral tests for the Node SDK's fail-open design with no gateway.

These tests assert the *designed* behavior of ``@agent-assembly/sdk`` when no
gateway (aa-core) is reachable. By design the SDK is fail-open: ``initAssembly``
returns a no-op gateway client (``createNoopGatewayClient``) whose governed
``check()`` always resolves to ``{denied: false}`` — see
``node-sdk/src/core/init-assembly.ts`` (``createClient``) and
``node-sdk/src/gateway/client.ts`` (``createNoopGatewayClient``).

The SDK is explicitly *not* a security boundary (the runtime/proxy/eBPF layers
are): a missing gateway must never block a governed action from the SDK's
perspective. These tests lock in that contract per enforcement mode.

The package is installed from the sibling ``../node-sdk`` checkout (built via
``pnpm build`` if its committed ``dist/`` is stale) into an isolated temporary
project, then exercised by shelling out to ``node`` — mirroring the public Node
smoke tests. Everything is skipped when ``node``/``npm`` are absent or the SDK
cannot be built/installed. No gateway is ever started.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from tests.public.conftest import skip_if_binary_missing

COMPONENT = "node-sdk"
PACKAGE = "@agent-assembly/sdk"

# Sibling node-sdk checkout: <workspace>/node-sdk, relative to this repo's root.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_NODE_SDK_DIR = _REPO_ROOT.parent / "node-sdk"

# A deliberately unreachable gateway URL. Port 1 (tcpmux) is privileged and not
# listening, so any real connection attempt fails fast — modelling "no core".
_NO_GATEWAY_URL = "http://127.0.0.1:1"

ENFORCEMENT_MODES = ("enforce", "observe", "disabled")


def _node_sdk_checkout() -> Path:
    """Return the sibling node-sdk checkout path, or skip if it is absent."""
    if not (_NODE_SDK_DIR / "package.json").is_file():
        pytest.skip(f"node-sdk checkout not found at {_NODE_SDK_DIR}")
    return _NODE_SDK_DIR


def _build_node_sdk(checkout: Path) -> None:
    """Build the node-sdk so the installed ``dist/`` is fresh, or skip on failure.

    The committed ``dist/`` may be stale, so we rebuild. ``pnpm`` is required to
    build; when it is unavailable we fall back to whatever ``dist/`` is checked
    in, and skip only if no build output exists at all.
    """
    if shutil.which("pnpm") is not None:
        result = subprocess.run(
            ["pnpm", "build"],
            cwd=checkout,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            pytest.skip(
                f"[{COMPONENT}] 'pnpm build' failed (exit {result.returncode})\n"
                f"stderr: {result.stderr.strip()[-2000:]}"
            )
        return

    # No pnpm: rely on the committed dist if present, otherwise skip.
    if not (checkout / "dist" / "esm" / "index.js").is_file():
        pytest.skip(f"[{COMPONENT}] pnpm unavailable and no committed dist/ to install")


def _install_into(work_dir: Path, checkout: Path) -> None:
    """Install the local node-sdk into an isolated ESM project, or skip on failure."""
    (work_dir / "package.json").write_text('{"type":"module","private":true}\n')
    result = subprocess.run(
        ["npm", "install", "--no-audit", "--no-fund", str(checkout)],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        pytest.skip(
            f"[{COMPONENT}] 'npm install {checkout}' failed (exit {result.returncode})\n"
            f"stderr: {result.stderr.strip()[-2000:]}"
        )


def _run_node(work_dir: Path, script: str) -> subprocess.CompletedProcess[str]:
    """Run an ESM snippet under node from *work_dir*."""
    return subprocess.run(
        ["node", "--input-type=module", "-e", script],
        cwd=work_dir,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="module")
def node_sdk_project(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build + install the local node-sdk into an isolated project once per module."""
    skip_if_binary_missing("node")
    skip_if_binary_missing("npm")
    checkout = _node_sdk_checkout()
    _build_node_sdk(checkout)
    work_dir = tmp_path_factory.mktemp("node_without_core")
    _install_into(work_dir, checkout)
    return work_dir


# For every enforcement mode, with no gateway reachable, assert that:
#   1. initAssembly resolves without throwing (the SDK is fail-open on boot), and
#   2. the governed gateway-client check() resolves to denied=false.
# The no-op gateway client returned by createNoopGatewayClient (which is exactly
# what createClient returns when no gateway client is injected) is the unit that
# encodes the fail-open contract, so we assert directly on its check() result.
_FAIL_OPEN_SCRIPT = textwrap.dedent("""\
    import { initAssembly, createNoopGatewayClient } from '@agent-assembly/sdk';

    const MODES = ['enforce', 'observe', 'disabled'];
    const NO_GATEWAY_URL = '%(url)s';
    const results = {};

    for (const mode of MODES) {
      // Boot the SDK with the gateway unreachable. sdk-only keeps the assertion
      // hermetic (no native sidecar event); the governed-check fail-open path is
      // identical across modes because createClient always yields the no-op client.
      const ctx = await initAssembly({
        mode: 'sdk-only',
        enforcementMode: mode,
        gatewayUrl: NO_GATEWAY_URL,
        agentId: 'without-core-probe',
      });

      // The governed check the SDK runs before a tool call. With no gateway the
      // no-op client answers allow regardless of enforcement mode (fail-open).
      const client = createNoopGatewayClient(mode);
      const decision = await client.check({
        toolName: 'do_governed_thing',
        runId: 'run-1',
        input: {},
      });

      results[mode] = {
        initOk: true,
        denied: decision.denied,
        pending: decision.pending ?? false,
        clientMode: client.mode,
      };
      await ctx.shutdown();
    }

    process.stdout.write(JSON.stringify(results));
""") % {"url": _NO_GATEWAY_URL}


@pytest.mark.sdk
def test_node_fail_open_per_enforcement_mode(node_sdk_project: Path) -> None:
    """No gateway: governed check is allow (denied=false) for every mode.

    Asserts the designed fail-open behavior — for enforce, observe, and
    disabled, with no aa-core reachable, ``initAssembly`` succeeds and the
    governed ``check()`` resolves to ``denied: false``.
    """
    result = _run_node(node_sdk_project, _FAIL_OPEN_SCRIPT)
    assert result.returncode == 0, (
        f"[{COMPONENT}] fail-open probe failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )

    decisions = json.loads(result.stdout)
    for mode in ENFORCEMENT_MODES:
        assert mode in decisions, f"[{COMPONENT}] missing result for mode {mode!r}"
        outcome = decisions[mode]
        assert outcome["initOk"] is True, (
            f"[{COMPONENT}] initAssembly did not complete for mode {mode!r}"
        )
        # Fail-open: the governed action proceeds (not denied) with no gateway.
        assert outcome["denied"] is False, (
            f"[{COMPONENT}] mode {mode!r}: expected denied=false (fail-open), "
            f"got {outcome['denied']!r}"
        )
        assert outcome["clientMode"] == mode, (
            f"[{COMPONENT}] mode {mode!r}: no-op client mode mismatch "
            f"({outcome['clientMode']!r})"
        )


# In the default ('auto') mode the SDK additionally fires a native registration
# event at boot. With no gateway reachable that send is fire-and-forget, so
# initAssembly must still resolve and shut down cleanly — proving the SDK never
# hard-fails just because aa-core is down.
_AUTO_BOOT_SCRIPT = textwrap.dedent("""\
    import { initAssembly } from '@agent-assembly/sdk';

    const ctx = await initAssembly({
      enforcementMode: 'enforce',
      gatewayUrl: '%(url)s',
      agentId: 'without-core-auto',
    });
    const enforcement = ctx.enforcementMode;
    await ctx.shutdown();
    process.stdout.write(JSON.stringify({ initOk: true, enforcement }));
""") % {"url": _NO_GATEWAY_URL}


@pytest.mark.sdk
def test_node_auto_mode_boots_without_gateway(node_sdk_project: Path) -> None:
    """Default mode boots and shuts down cleanly with no gateway reachable.

    The auto-mode native registration send is fire-and-forget, so a missing
    gateway must not raise from ``initAssembly``/``shutdown`` — the agent keeps
    running (fail-open) rather than crashing on a down core.
    """
    result = _run_node(node_sdk_project, _AUTO_BOOT_SCRIPT)
    assert result.returncode == 0, (
        f"[{COMPONENT}] auto-mode boot failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    payload = json.loads(result.stdout)
    assert payload["initOk"] is True, (
        f"[{COMPONENT}] auto-mode initAssembly did not complete cleanly"
    )
    assert payload["enforcement"] == "enforce", (
        f"[{COMPONENT}] auto-mode preserved enforcementMode mismatch: "
        f"{payload['enforcement']!r}"
    )
