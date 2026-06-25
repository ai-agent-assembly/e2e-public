"""Behavioral: the Node SDK fails *closed at init* for ``enforce``, *open* otherwise.

These tests assert the *designed* boot-time security posture of
``@agent-assembly/sdk`` when no gateway / native ``aa-runtime`` is reachable.
The contract is split by enforcement mode, and the split lives at the
``initAssembly`` boundary (AAASM-3105, the Node analogue of AAASM-3697):

* ``enforce`` **fails closed at init**. ``createClient`` refuses to route a live
  ``"enforce"`` posture through the allow-all no-op gateway client, because doing
  so would let a policy-denied action proceed unchecked — a silent fail-open.
  Unless the mode is the check-capable one (``"napi-inprocess"``) or the caller
  supplies their own ``gatewayClient``, ``initAssembly`` throws a
  ``ConfigurationError`` rather than pretending to enforce. The ``sdk-only`` /
  ``auto`` modes used here are *not* check-capable, so ``enforce`` raises.

* ``observe`` and ``disabled`` **fail open**: a missing gateway must never block a
  governed action under these postures, so ``initAssembly`` returns a usable
  context without raising and the agent proceeds.

The SDK is explicitly *not* the authoritative enforcement point (the
runtime/proxy/eBPF layers are) — but the boot-time refusal above is the SDK
being honest: it will not *claim* to enforce through a client that cannot block.

The error is matched by its ``name``/message, not by ``instanceof``: the node-sdk
does **not** export ``ConfigurationError`` from its public surface (only
``OpTerminatedError`` / ``PolicyViolationError`` are exported), so the harness
script asserts on ``err.name === 'ConfigurationError'`` plus the message — both
verified empirically against the installed package.

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

# Substring of the ConfigurationError the SDK raises when 'enforce' is requested
# through a non-check-capable mode. Verified empirically against the installed
# package; kept as a fragment so wording tweaks downstream don't break the test.
_ENFORCE_REFUSAL_FRAGMENT = "requires a check-capable client"


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


# 'enforce' with no reachable core fails CLOSED at init: routing a live enforce
# posture through the allow-all no-op client would silently fail open, so the SDK
# refuses to boot and throws a ConfigurationError. We capture the thrown error's
# name + message (the SDK does not export ConfigurationError, so we cannot use
# instanceof) and confirm init never produced a usable context.
_ENFORCE_FAIL_CLOSED_SCRIPT = textwrap.dedent("""\
    import { initAssembly } from '@agent-assembly/sdk';

    const NO_GATEWAY_URL = '%(url)s';
    let result;
    try {
      // sdk-only is not the check-capable mode (napi-inprocess), so 'enforce'
      // must be refused at init rather than route through the no-op client.
      const ctx = await initAssembly({
        mode: 'sdk-only',
        enforcementMode: 'enforce',
        gatewayUrl: NO_GATEWAY_URL,
        agentId: 'without-core-enforce',
      });
      // Reaching here means init did NOT fail closed — record that for the test.
      await ctx.shutdown();
      result = { threw: false };
    } catch (err) {
      result = {
        threw: true,
        errName: err && err.name ? err.name : null,
        message: err && err.message ? err.message : null,
      };
    }

    process.stdout.write(JSON.stringify(result));
""") % {"url": _NO_GATEWAY_URL}


@pytest.mark.sdk
def test_node_enforce_fails_closed_at_init_without_gateway(node_sdk_project: Path) -> None:
    """enforce, no core → ``initAssembly`` throws ConfigurationError (fail-closed).

    The Node analogue of AAASM-3697 (AAASM-3105): with no check-capable client and
    the gateway unreachable, ``initAssembly(enforcementMode: 'enforce')`` refuses to
    boot rather than route a live enforce posture through the allow-all no-op
    client (which would silently fail open). It throws a ``ConfigurationError``.

    Matched by ``err.name``/message — the SDK does not export ``ConfigurationError``
    from its public surface, so ``instanceof`` is not available to the harness.
    """
    result = _run_node(node_sdk_project, _ENFORCE_FAIL_CLOSED_SCRIPT)
    assert result.returncode == 0, (
        f"[{COMPONENT}] enforce fail-closed probe crashed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )

    outcome = json.loads(result.stdout)
    assert outcome["threw"] is True, (
        f"[{COMPONENT}] expected initAssembly(enforce) to fail closed (throw) with no "
        f"core reachable, but it returned a context instead: {outcome!r}"
    )
    assert outcome["errName"] == "ConfigurationError", (
        f"[{COMPONENT}] expected a ConfigurationError on enforce fail-closed, got "
        f"{outcome['errName']!r}"
    )
    assert _ENFORCE_REFUSAL_FRAGMENT in (outcome["message"] or ""), (
        f"[{COMPONENT}] enforce fail-closed message did not describe the "
        f"check-capable-client requirement: {outcome['message']!r}"
    )


# 'observe' and 'disabled' fail OPEN: with no gateway reachable these postures
# must never block, so initAssembly boots cleanly and reports the requested mode.
_FAIL_OPEN_SCRIPT = textwrap.dedent("""\
    import { initAssembly } from '@agent-assembly/sdk';

    const MODES = ['observe', 'disabled'];
    const NO_GATEWAY_URL = '%(url)s';
    const results = {};

    for (const mode of MODES) {
      // Boot the SDK with the gateway unreachable. sdk-only keeps the assertion
      // hermetic (no native sidecar event). observe/disabled intentionally let
      // actions through, so init must succeed even with no core present.
      const ctx = await initAssembly({
        mode: 'sdk-only',
        enforcementMode: mode,
        gatewayUrl: NO_GATEWAY_URL,
        agentId: 'without-core-probe',
      });

      results[mode] = {
        initOk: true,
        enforcement: ctx.enforcementMode,
      };
      await ctx.shutdown();
    }

    process.stdout.write(JSON.stringify(results));
""") % {"url": _NO_GATEWAY_URL}


@pytest.mark.sdk
def test_node_observe_and_disabled_fail_open_without_gateway(node_sdk_project: Path) -> None:
    """observe/disabled, no core → ``initAssembly`` boots (fail-open).

    Unlike ``enforce``, the ``observe`` and ``disabled`` postures intentionally let
    actions through, so a missing gateway must not block them: ``initAssembly``
    returns a usable context without raising and preserves the requested mode.
    """
    result = _run_node(node_sdk_project, _FAIL_OPEN_SCRIPT)
    assert result.returncode == 0, (
        f"[{COMPONENT}] fail-open probe failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )

    decisions = json.loads(result.stdout)
    for mode in ("observe", "disabled"):
        assert mode in decisions, f"[{COMPONENT}] missing result for mode {mode!r}"
        outcome = decisions[mode]
        assert outcome["initOk"] is True, (
            f"[{COMPONENT}] initAssembly did not complete for mode {mode!r} (fail-open)"
        )
        assert outcome["enforcement"] == mode, (
            f"[{COMPONENT}] mode {mode!r}: enforcement not preserved ({outcome['enforcement']!r})"
        )


# In the default ('auto') mode the SDK additionally fires a native registration
# event at boot. With no gateway reachable that send is fire-and-forget, so under
# a fail-open posture (observe) initAssembly must still resolve and shut down
# cleanly — proving the SDK never hard-fails just because aa-core is down. ('auto'
# is not check-capable, so 'enforce' would fail closed here too — covered above.)
_AUTO_BOOT_SCRIPT = textwrap.dedent("""\
    import { initAssembly } from '@agent-assembly/sdk';

    const ctx = await initAssembly({
      enforcementMode: 'observe',
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

    The auto-mode native registration send is fire-and-forget, so under a
    fail-open posture (``observe``) a missing gateway must not raise from
    ``initAssembly``/``shutdown`` — the agent keeps running rather than crashing on
    a down core. (Auto mode is not check-capable, so ``enforce`` fails closed at
    init here too — that path is asserted by the enforce fail-closed test.)
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
    assert payload["enforcement"] == "observe", (
        f"[{COMPONENT}] auto-mode preserved enforcementMode mismatch: {payload['enforcement']!r}"
    )
