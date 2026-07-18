"""Live framework smoke test — **Mastra** on the Node SDK (AAASM-3525).

Proves a *real* Mastra agent runs end-to-end through the Node SDK's
governance path against a **live** ``aa-runtime`` — the production
``SDK → aa-ffi → aa-runtime`` transport, not a mock. The driver
(``drivers/node-frameworks/zod3-frameworks/mastra.mjs``) builds a genuine Mastra
``createTool`` tool and wraps it with the SDK's public ``withAssembly`` (the
enforcing wrapper layer; ``patchMastra`` is also applied for the framework's
lineage hook), then runs an **allowed** tool call.

Highlight governance functions exercised on the real path (allow side): a
pre-execution governance ``check()`` runs against the live core, a real
``ToolCallIntercepted`` event is emitted over the UDS, and the Mastra tool
executes because the live core allowed it.

Layers mirror ``test_e2e_node.py``:

* **offline** — the shared allow/deny policy loads + resolves correctly (green
  in a bare ``-m e2e`` run, no toolchain).
* **allow path (live)** — needs ``cargo``/``protoc`` (to build ``aa-runtime``),
  a built Node SDK, and the framework's installed deps; skips cleanly
  (justified) otherwise.
* **deny path (live, strict-xfail)** — pinned xfail on the product gaps so it
  never yields a false green.

Known product gaps that make the deny path unprovable today — shared across all
SDKs via ``aa-sdk-client``: **AAASM-3000** (SDK⇄aa-runtime IPC deadlock) and
**AAASM-3021** (SDK pre-execution ``check()`` unwired / fails open).
**AAASM-3172** will flip the deny-path xfail to a hard assert once a fixed SDK
release ships.
"""

from __future__ import annotations

import pytest

from tests.live.enforcement import (
    ALLOWED_ACTION,
    ENFORCEMENT_POLICY,
    RESTRICTED_ACTION,
    load_policy_rules,
    policy_denies,
)
from tests.live.node_frameworks import (
    FrameworkDriverUnavailable,
    locate_framework_driver,
    run_framework_driver,
)
from tests.live.runtime import LiveRuntime

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]

FRAMEWORK = "mastra"


def test_mastra_enforcement_policy_is_well_formed() -> None:
    """Offline: the shared policy denies the restricted action and allows others.

    The floor under the live allow/deny paths — if the fixture did not encode a
    deny + a permit the live assertions would be meaningless. Runs with no
    toolchain so it is green in a bare ``-m e2e`` run.
    """
    assert ENFORCEMENT_POLICY.is_file()
    rules = load_policy_rules()
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert policy_denies(rules, ALLOWED_ACTION) is False


def test_mastra_allow_path_runs_governed_tool(live_runtime: LiveRuntime) -> None:
    """Allow path: a real Mastra agent runs an allowed governed tool via live core.

    Drives the genuine Mastra agent through the SDK's governance hook
    against the live runtime UDS: the pre-execution governance check runs
    on the real ``SDK → aa-ffi → aa-runtime`` path, a governance event is emitted,
    and the tool executes (allow took effect). Skips cleanly (justified env
    requirement) when the Node toolchain, a built SDK, or the framework deps are
    absent.
    """
    try:
        driver = locate_framework_driver(FRAMEWORK)
    except FrameworkDriverUnavailable as exc:
        pytest.skip(f"{exc} (classification: known_prerequisite)")

    result = run_framework_driver(driver, live_runtime.socket_path)
    assert result["ok"] is True
    assert result["framework"] == FRAMEWORK
    # A governance check actually ran on the live path, the allowed action was
    # permitted, and the real framework tool executed under governance.
    assert result["checks"] >= 1
    assert result["denied"] is False
    assert result["executed"] is True


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), remove this strict xfail and turn the body into a hard assert that
# the restricted action is blocked for a Mastra tool at the SDK layer.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Live deny enforcement for a Mastra agent is unprovable today: "
        "AAASM-3000 (SDK⇄aa-runtime IPC deadlock) and AAASM-3021 (pre-execution "
        "check() unwired — the SDK gateway client fails open, so a denied action "
        "is not blocked at the SDK layer). Flip to a hard assert via AAASM-3172 "
        "once a fixed SDK release ships."
    ),
)
def test_mastra_deny_path_blocks_restricted_tool() -> None:
    """Deny path: a restricted Mastra tool call is blocked against a live core.

    The load-bearing enforcement assertion — a denied action MUST be refused at
    the SDK boundary. The SDK's gateway client fails open today (AAASM-3021), so
    this is a ``strict=True`` xfail; the day it enforces it XPASSes and the strict
    marker fails the suite — the cue to flip it (AAASM-3172).
    """
    rules = load_policy_rules()
    # The policy denies the restricted action, so a correct SDK pre-check would
    # refuse it; the SDK fails open (AAASM-3021). Assert the intended contract and
    # let strict-xfail record the gap.
    sdk_would_block = False
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert sdk_would_block is True, (
        f"Node SDK does not block {RESTRICTED_ACTION!r} for a Mastra agent — "
        "the SDK gateway client fails open (AAASM-3021)"
    )
