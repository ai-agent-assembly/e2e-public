"""Behavioral tests for the Node SDK's positive enforcement contract.

This is the positive mirror of ``test_node_without_core.py``. Where that module
locks in the *fail-open* behavior with no gateway (the no-op client always
answers ``denied: false``), this module proves the *enforcement-decision*
contract of the tool wrapper: when a gateway returns a deny, the wrapped tool
must be blocked; when it returns allow, the wrapped tool must run.

The deny/allow decision and the block live in ``withAssembly`` /
``wrapSingleTool`` (``node-sdk/src/wrappers/with-assembly.ts``). For each wrapped
tool the wrapper calls
``gateway.check({ action: 'tool_call', toolName, args, runId })`` *before* the
original ``execute()``; if ``decision.denied`` is truthy it throws a
``PolicyViolationError`` and never calls the original body, otherwise (for
``{ denied: false, pending: false }``) it proceeds.

Tier-A — public injection (no live core)
----------------------------------------
``initAssembly`` / ``createClient`` (``node-sdk/src/core/init-assembly.ts``)
returns ``config.gatewayClient`` verbatim when one is injected (only otherwise
falling back to ``createNoopGatewayClient``). That is the clean, public seam.
We inject a custom ``gatewayClient`` whose ``check()`` returns
``{ denied: true, pending: false }`` for a ``blocked_tool`` and
``{ denied: false, pending: false }`` for an ``allowed_tool``, wrap both tools
via ``withAssembly``, and assert:

* DENY  — calling ``blocked_tool`` rejects with ``PolicyViolationError`` and the
  original tool body did *not* run (proved by a side-effect flag).
* ALLOW — calling ``allowed_tool`` resolves and its body *did* run.

This exercises the wrapper's real deny/allow branch through the public API
without standing up a live ``aa-core``.

observe mode
------------
The Node wrapper has *no* observe branch: ``wrapSingleTool`` throws on any
truthy ``decision.denied`` regardless of enforcement mode. "observe =
record-but-allow" is a server-side concept (the gateway returns
``denied: false`` and records the event); there is no client-side observe
behavior to assert here, so this module intentionally does not test one.

Live core (gated by AAASM-3021)
-------------------------------
A true end-to-end deny from a real gateway cannot be exercised yet: the shipped
SDK's ``createClient`` returns ``createNoopGatewayClient`` and never calls the
gRPC ``checkAction``, so a live core can never produce a client-visible deny
(AAASM-3021). The ``test_node_live_core_deny_blocks_tool`` placeholder records
that gap as ``xfail`` so it never produces a false green and flips to ``XPASS``
the day the SDK wires ``check()`` to the gRPC path.

The package is installed from the sibling ``../node-sdk`` checkout (built via
``pnpm build`` if its committed ``dist/`` is stale) into an isolated temporary
project, then exercised by shelling out to ``node`` — mirroring the without-core
behavioral test. Everything is skipped when ``node``/``npm`` are absent or the
SDK cannot be built/installed.
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

# Gateway URL is never dialled in Tier-A (the injected client answers in-process),
# but initAssembly still resolves it, so give it a deliberately unreachable value.
_UNUSED_GATEWAY_URL = "http://127.0.0.1:1"


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
    work_dir = tmp_path_factory.mktemp("node_with_core")
    _install_into(work_dir, checkout)
    return work_dir


# Inject a custom gateway client that denies 'blocked_tool' and allows
# 'allowed_tool', then wrap both tools via withAssembly. Each tool body sets a
# side-effect flag so we can prove whether the original execute() actually ran.
# We assert the wrapper's enforcement branch directly:
#   * deny  -> calling blocked_tool throws PolicyViolationError and the body
#              never ran (ranBlocked stays false);
#   * allow -> calling allowed_tool resolves and the body ran (ranAllowed true).
# The injected client is what createClient returns verbatim (init-assembly.ts),
# so this drives the real public seam without a live core.
_ENFORCEMENT_SCRIPT = textwrap.dedent("""\
    import {
      initAssembly,
      withAssembly,
      PolicyViolationError,
    } from '@agent-assembly/sdk';

    // A custom gateway client implementing the GatewayClient contract. check()
    // is the only governed method exercised here; the rest are inert no-ops.
    function denyingGatewayClient() {
      return {
        mode: 'sdk-only',
        start: async () => undefined,
        close: async () => undefined,
        check: async (request) => {
          if (request.toolName === 'blocked_tool') {
            return { denied: true, pending: false, reason: 'policy: blocked_tool' };
          }
          return { denied: false, pending: false };
        },
        waitForApproval: async () => ({ denied: false }),
        record: async () => undefined,
        recordResult: async () => undefined,
        scanPrompts: async () => undefined,
      };
    }

    const gatewayClient = denyingGatewayClient();

    // initAssembly returns our injected client verbatim via createClient; we
    // also hand the same client to withAssembly, which is what wraps the tools.
    const ctx = await initAssembly({
      mode: 'sdk-only',
      enforcementMode: 'enforce',
      gatewayUrl: '%(url)s',
      agentId: 'with-core-probe',
      gatewayClient,
    });

    const sideEffects = { ranBlocked: false, ranAllowed: false };

    const tools = {
      blocked_tool: {
        execute: async () => {
          sideEffects.ranBlocked = true;
          return 'blocked-body-result';
        },
      },
      allowed_tool: {
        execute: async () => {
          sideEffects.ranAllowed = true;
          return 'allowed-body-result';
        },
      },
    };

    withAssembly(tools, { gatewayClient });

    // DENY: blocked_tool must reject with PolicyViolationError, body must not run.
    let blockedThrew = false;
    let blockedErrorName = null;
    let blockedIsPolicyViolation = false;
    try {
      await tools.blocked_tool.execute();
    } catch (err) {
      blockedThrew = true;
      blockedErrorName = err?.constructor?.name ?? null;
      blockedIsPolicyViolation = err instanceof PolicyViolationError;
    }

    // ALLOW: allowed_tool must resolve and its body must run.
    const allowedResult = await tools.allowed_tool.execute();

    await ctx.shutdown();

    process.stdout.write(JSON.stringify({
      blockedThrew,
      blockedErrorName,
      blockedIsPolicyViolation,
      ranBlocked: sideEffects.ranBlocked,
      ranAllowed: sideEffects.ranAllowed,
      allowedResult,
    }));
""") % {"url": _UNUSED_GATEWAY_URL}


@pytest.mark.sdk
def test_node_wrapper_enforces_deny_and_allow(node_sdk_project: Path) -> None:
    """A gateway deny blocks the wrapped tool; an allow lets it run.

    Drives the wrapper's enforcement branch (``wrapSingleTool``) through the
    public injection seam (``initAssembly``/``withAssembly`` with a custom
    ``gatewayClient``):

    * ``blocked_tool`` (gateway ``denied: true``) rejects with
      ``PolicyViolationError`` and its body never executes; and
    * ``allowed_tool`` (gateway ``denied: false``) resolves and its body runs.
    """
    result = _run_node(node_sdk_project, _ENFORCEMENT_SCRIPT)
    assert result.returncode == 0, (
        f"[{COMPONENT}] enforcement probe failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )

    outcome = json.loads(result.stdout)

    # DENY branch: rejected with PolicyViolationError and the body did NOT run.
    assert outcome["blockedThrew"] is True, (
        f"[{COMPONENT}] blocked_tool did not reject — wrapper failed to enforce the deny"
    )
    assert outcome["blockedIsPolicyViolation"] is True, (
        f"[{COMPONENT}] blocked_tool rejected with {outcome['blockedErrorName']!r}, "
        f"expected PolicyViolationError"
    )
    assert outcome["ranBlocked"] is False, (
        f"[{COMPONENT}] blocked_tool body ran despite the deny — enforcement happens "
        f"after execute() instead of before"
    )

    # ALLOW branch: resolved and the body DID run.
    assert outcome["ranAllowed"] is True, (
        f"[{COMPONENT}] allowed_tool body did not run despite an allow decision"
    )
    assert outcome["allowedResult"] == "allowed-body-result", (
        f"[{COMPONENT}] allowed_tool returned {outcome['allowedResult']!r}, "
        f"expected the original body's result to pass through"
    )


# The same deny driven by a *real* gateway over the SDK's native transport. This
# cannot pass yet: the shipped createClient returns createNoopGatewayClient and
# never calls the gRPC checkAction, so a live core's deny is invisible to the
# client (AAASM-3021). Marked xfail so it is never a false green and surfaces as
# XPASS the day the SDK wires check() to the gRPC path — the cue to assert hard.
_LIVE_CORE_DENY_SCRIPT = textwrap.dedent("""\
    import {
      initAssembly,
      withAssembly,
      PolicyViolationError,
    } from '@agent-assembly/sdk';

    // No gatewayClient injected: createClient falls back to the no-op client,
    // which always answers { denied: false } regardless of any live core.
    const ctx = await initAssembly({
      mode: 'sdk-only',
      enforcementMode: 'enforce',
      gatewayUrl: '%(url)s',
      agentId: 'with-core-live-probe',
    });

    let ranBlocked = false;
    const tools = {
      blocked_tool: {
        execute: async () => {
          ranBlocked = true;
          return 'blocked-body-result';
        },
      },
    };
    withAssembly(tools, { gatewayClient: ctx.gatewayClient ?? undefined });

    let blockedThrew = false;
    try {
      await tools.blocked_tool.execute();
    } catch (err) {
      blockedThrew = err instanceof PolicyViolationError;
    }
    await ctx.shutdown();
    process.stdout.write(JSON.stringify({ blockedThrew, ranBlocked }));
""") % {"url": _UNUSED_GATEWAY_URL}


@pytest.mark.sdk
@pytest.mark.xfail(
    reason=(
        "AAASM-3021: the shipped SDK's createClient returns createNoopGatewayClient "
        "and never calls the gRPC checkAction, so a live core's deny is invisible to "
        "the client. The wrapper sees { denied: false } and the tool runs. This flips "
        "to XPASS once the SDK wires check() to the gRPC path — then drop the marker "
        "and assert against a real aa-core."
    ),
    strict=False,
    raises=AssertionError,
)
def test_node_live_core_deny_blocks_tool(node_sdk_project: Path) -> None:
    """Placeholder for a real-gateway deny over the SDK's native transport.

    With no client injected, ``createClient`` falls back to the no-op client, so
    no live-core deny ever reaches the wrapper (AAASM-3021). The deny assertion
    therefore fails today; ``xfail(strict=False)`` keeps it an honest signal —
    never a fabricated pass, and an ``XPASS`` flag once the gRPC path is wired.
    """
    result = _run_node(node_sdk_project, _LIVE_CORE_DENY_SCRIPT)
    assert result.returncode == 0, (
        f"[{COMPONENT}] live-core deny probe failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    outcome = json.loads(result.stdout)
    # Expected to fail until AAASM-3021: no-op client => no deny, tool runs.
    assert outcome["blockedThrew"] is True, (
        f"[{COMPONENT}] blocked_tool was not blocked by a live-core deny (AAASM-3021)"
    )
    assert outcome["ranBlocked"] is False, (
        f"[{COMPONENT}] blocked_tool body ran despite a live-core deny (AAASM-3021)"
    )
