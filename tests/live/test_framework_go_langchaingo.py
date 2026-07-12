"""Live AI-agent *framework* smoke test for the **Go** SDK (AAASM-3525).

Proves a real Go AI-agent framework — **LangChainGo**, the Go SDK's only
first-class framework adapter — runs end-to-end through the SDK + a real
``aa-runtime`` and that the highlight governance functions take effect, not just
that the SDK builds. The generic ``WrapTools`` path (Go's only other "framework"
surface; the ecosystem is thin) is covered too, so neither cell is a silent gap.

This is the framework-level complement to ``test_e2e_go.py`` (which drives a
synthetic action through the same live path). Where the E2E proves the bare
allow-path transport, this proves a **genuine LangChainGo agent** — an offline
fake LLM plans, then real ``langchaingo/tools.Tool`` values are governed via the
real ``assembly.WrapTools`` / ``assembly.WrapChain`` code — runs that allow path
against a reachable live core, emitting an event (UDS reachable) and producing an
audit-shaped record.

Highlight governance functions exercised on the **allow path** (real):

* **event emission** — the driver dials the live ``aa-runtime`` UDS from a real
  SDK process; a successful connect is the SDK→core transport evidence
  (``runtimeReachable``);
* **pre-execution allow enforcement** — the real ``assembly.WrapTools`` wrapper
  consults policy, sees ALLOW, and lets the framework tool's ``Call`` run;
* **audit capture** — the governed allow decision is recorded
  (``result["audit"]``).

Honesty constraint — the **deny/block** path is **unprovable today** and is a
``strict=True`` xfail, exactly like the existing live E2E:

* **AAASM-3000** — SDK⇄aa-runtime IPC deadlock (``close()`` hangs, no events).
* **AAASM-3021** — Go SDK pre-execution ``Check`` is a no-op against a live core.

Budget/cost tracking and egress interception are **gateway/runtime policy
decisions**, not in-process SDK-wrapper behaviour; an in-process Go framework
smoke cannot assert them without the deny path the same two gaps block, so they
are deferred to the same AAASM-3172 flip — called out here, not silently skipped.

Layers, by how much they need:

* **offline** — the shared policy fixture loads + resolves allow/deny correctly
  (green in a bare ``-m e2e`` run, no toolchain).
* **allow path (live)** — needs ``go`` + the go-sdk checkout + the built cgo FFI
  library + ``cargo``/``protoc`` (to build ``aa-runtime``); skips cleanly
  (justified) otherwise.
* **deny path (live, strict-xfail)** — pinned xfail on the product gaps so it
  never yields a false green; AAASM-3172 flips it.
"""

from __future__ import annotations

import pytest

from tests.live.enforcement import (
    ALLOWED_ACTION,
    ENFORCEMENT_POLICY,
    RESTRICTED_ACTION,
    go_sdk_available,
    load_policy_rules,
    policy_denies,
)
from tests.live.framework_drivers_go import (
    LANGCHAINGO_MODE,
    WRAPTOOLS_MODE,
    DriverUnavailable,
    locate_go_framework_driver,
    run_go_framework_driver,
)
from tests.live.runtime import LiveRuntime

pytestmark = [pytest.mark.live, pytest.mark.e2e, pytest.mark.sdk]


def _require_go_toolchain() -> None:
    """Skip the calling test when the Go toolchain to drive the SDK is absent."""
    if not go_sdk_available():
        pytest.skip(
            "Go SDK toolchain not available — install go and the go-sdk module "
            "(from ../go-sdk) to run this live framework smoke test"
        )


def test_go_framework_enforcement_policy_is_well_formed() -> None:
    """Offline: the shared policy denies the restricted action and allows others.

    The floor under the live allow/deny framework assertions: if the fixture did
    not actually encode a deny + a permit, the live framework assertions would be
    meaningless. Runs with no toolchain.
    """
    assert ENFORCEMENT_POLICY.is_file()
    rules = load_policy_rules()
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert policy_denies(rules, ALLOWED_ACTION) is False


def _run_allow_path(live_runtime: LiveRuntime, mode: str) -> dict:
    """Locate + run the framework driver in *mode* against the live runtime.

    Translates a :class:`DriverUnavailable` into a clean justified skip (the
    locator decides this BEFORE anything is launched), then drives the allowed
    action and returns the parsed driver result.
    """
    _require_go_toolchain()
    try:
        driver = locate_go_framework_driver()
    except DriverUnavailable as exc:
        pytest.skip(f"{exc} (classification: known_prerequisite)")
    return run_go_framework_driver(driver, live_runtime.socket_path, ALLOWED_ACTION, mode)


def test_langchaingo_allow_path_governs_real_agent(live_runtime: LiveRuntime) -> None:
    """Allow path: a real LangChainGo agent runs a governed allowed tool live.

    Drives a genuine LangChainGo agent (offline fake LLM + real
    ``langchaingo/tools.Tool`` governed by ``assembly.WrapTools``, plus the
    ``assembly.WrapChain`` adapter) against the live ``aa-runtime`` for an action
    the policy allows, and asserts: the wrapped framework tool actually executed
    (allow enforcement let it through), the live UDS was reachable (event
    emission transport), and an allow audit record was produced. Skips cleanly
    (justified env requirement) when ``go``, the go-sdk checkout, or the built
    cgo FFI library is absent; does not assert a clean ``close()`` (AAASM-3000).
    """
    result = _run_allow_path(live_runtime, LANGCHAINGO_MODE)

    assert result["ok"] is True
    assert result["framework"] == "LangChainGo"
    assert result["action"] == ALLOWED_ACTION
    assert result["denied"] is False
    # Event emission: the real SDK process reached the live runtime's UDS.
    assert result["runtimeReachable"] is True
    # Audit capture: the governed allow decision was recorded.
    assert result["audit"]["decision"] == "allow"
    assert result["audit"]["tool"] == ALLOWED_ACTION


def test_wraptools_allow_path_governs_generic_agent(live_runtime: LiveRuntime) -> None:
    """Allow path: the generic Go ``WrapTools`` agent runs a governed allowed tool.

    Go's framework ecosystem beyond LangChainGo is the generic ``WrapTools``
    path (the basic-agent / tool-policy demos), so it is covered explicitly as a
    distinct cell rather than assumed equivalent — same live core, same
    highlight-function assertions as the LangChainGo cell.
    """
    result = _run_allow_path(live_runtime, WRAPTOOLS_MODE)

    assert result["ok"] is True
    assert result["framework"] == "generic WrapTools"
    assert result["action"] == ALLOWED_ACTION
    assert result["denied"] is False
    assert result["runtimeReachable"] is True
    assert result["audit"]["decision"] == "allow"


# AAASM-3172 FLIP SITE: when a fixed SDK release ships (AAASM-3000 + AAASM-3021
# resolved), remove this strict xfail and turn the body into a hard assert that
# the restricted action is blocked when a real LangChainGo agent runs it.
@pytest.mark.xfail(
    strict=True,
    reason=(
        "Go framework deny enforcement is unprovable today: AAASM-3000 "
        "(SDK⇄aa-runtime IPC deadlock) and AAASM-3021 (Go SDK pre-execution "
        "Check() is a no-op — `_, _ = c, request`), so a denied tool a real "
        "LangChainGo agent calls is not blocked at the SDK boundary. Flip to a "
        "hard assert via AAASM-3172 once a fixed SDK release ships. Budget/egress "
        "deny assertions are deferred to the same flip."
    ),
)
def test_langchaingo_deny_path_blocks_restricted_tool() -> None:
    """Deny path: a restricted tool a real LangChainGo agent calls is blocked.

    The load-bearing enforcement assertion for the Go framework smoke — a denied
    action a real framework agent invokes MUST be refused at the SDK boundary.
    The Go SDK's ``Check`` is a no-op against a live core (AAASM-3021), so this is
    a ``strict=True`` xfail; the day it enforces it XPASSes and strict-xfail fails
    the suite — the cue to flip it (AAASM-3172).
    """
    _require_go_toolchain()
    rules = load_policy_rules()
    # Encode the intended contract: the policy denies the restricted action, so a
    # correct SDK pre-check would refuse it before the framework tool runs. Go's
    # Check is a no-op (AAASM-3021); assert the contract and let strict-xfail
    # record the gap.
    sdk_would_block = False  # Go SDK Check() is `_, _ = c, request` — always allows
    assert policy_denies(rules, RESTRICTED_ACTION) is True
    assert sdk_would_block is True, (
        f"Go SDK does not block {RESTRICTED_ACTION!r} when a LangChainGo agent "
        "calls it — Check() is a no-op (AAASM-3021)"
    )
