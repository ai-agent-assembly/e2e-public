"""Behavioral tests for the Go SDK's *positive* enforcement-decision contract.

This is the positive mirror of ``tests/behavioral/test_go_without_core.py``.
Where the without-core suite asserts the **unavailable** branch (governance
``Check`` *errors*, and the wrapper denies or proceeds per the fail-closed
default and enforcement posture), this suite asserts the **decisive** branch
(governance ``Check`` *succeeds* and returns a ``Decision``):

* a ``Decision{Denied:true}`` must block the wrapped tool **before** the inner
  tool body runs, surfacing a ``PolicyViolationError``;
* a ``Decision{}`` (allow) must let the wrapped tool run and return its body
  output.

The decisive switch lives in ``assembly/tool_wrapper.go`` ``(*AssemblyTool).Call``:
the wrapper calls ``t.client.Check(ctx, CheckRequest{...})`` *before* invoking
``t.inner.Call``; when ``Check`` returns a ``nil`` error and ``decision.Denied``
is true it returns ``&PolicyViolationError{...}`` and never reaches the inner
tool. Otherwise it proceeds to ``t.inner.Call``.

Tier-A — public injection (this file, run by default)
-----------------------------------------------------
Rather than stand up a live ``aa-gateway`` and author policy, each cell drives
the public ``assembly.WrapTools`` / ``GovernanceClient`` surface with an
**injected** governance client whose ``Check`` returns a deterministic
``Decision`` keyed on the tool name:

* ``blocked_tool`` -> ``Decision{Denied:true, Reason:"policy: blocked"}``;
* ``allowed_tool`` -> ``Decision{}`` (allow).

This proves the wrapper's enforcement-decision contract through the SDK's
public API — no transport, no gateway, fully deterministic — exactly the way
``test_go_without_core.py`` proves the unavailable-gateway contract.

Note on enforcement mode: in the Go SDK there is **no client-side observe
gate**. ``WithEnforcementMode`` (enforce / observe / disabled) is a
registration-time wire field (``assembly/init_bridge.go``); it does not gate the
local ``tool_wrapper`` check loop. Once ``Check`` returns an allow ``Decision``,
every mode follows the identical proceed path. The observe posture is therefore
documented here, not asserted as a distinct client-side branch.

Tier-B — live-core deny (placeholder, ``live`` + ``xfail``)
-----------------------------------------------------------
A *true* end-to-end deny — driving the Go SDK's real ``GatewayClient.Check``
against a running ``aa-gateway`` with a deny policy — cannot be exercised in this
repo yet. Wiring the real transport (replacing the ``(*GatewayClient).Check``
stub with a ``GatewayTransport`` + gRPC ``CheckAction`` call) has landed
(**AAASM-3021**, Done); what remains is a live gateway plus a built Go SDK to
prove it. The live path is a strict ``xfail`` pinned on the open flip gate
**AAASM-3172**, so it documents the boundary and XPASSes loudly once the deny is
wired in — rather than a dead ``run=False`` doc that can never surface a
regression. It also carries the ``live`` marker so the default suite
(``-m 'not live'``) skips it.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
import textwrap

import pytest

from tests.public.conftest import skip_if_binary_missing

COMPONENT = "go-sdk"

# Canonical published module path, served by the Go module proxy (lowercase).
MODULE_PATH = "github.com/ai-agent-assembly/go-sdk"


_GO_MAIN = textwrap.dedent("""\
    // Command consumer exercises the Go SDK's positive enforcement-decision
    // contract. An injected governance client returns a deterministic Decision
    // keyed on the tool name: "blocked_tool" is denied, "allowed_tool" is
    // allowed. The wrapper must block the denied tool before its body runs and
    // let the allowed tool execute.
    package main

    import (
        "context"
        "fmt"

        "{module_path}/assembly"
    )

    // sentinelTool is a governed action whose Call always returns "ran:<input>"
    // when it is allowed to run. The presence or absence of that "ran:" output
    // is the observable signal for whether the inner tool body executed.
    type sentinelTool struct{{ name string }}

    func (t sentinelTool) Name() string        {{ return t.name }}
    func (t sentinelTool) Description() string  {{ return "sentinel" }}
    func (t sentinelTool) Call(_ context.Context, in string) (string, error) {{
        return "ran:" + in, nil
    }}

    // policyClient stands in for a live gateway with a loaded policy: Check
    // returns an allow/deny Decision based on the tool name, with no error.
    type policyClient struct{{}}

    func (policyClient) Check(
        _ context.Context, req assembly.CheckRequest,
    ) (assembly.Decision, error) {{
        if req.ToolName == "blocked_tool" {{
            return assembly.Decision{{Denied: true, Reason: "policy: blocked"}}, nil
        }}
        return assembly.Decision{{}}, nil
    }}

    func (policyClient) WaitForApproval(
        context.Context, assembly.ApprovalRequest,
    ) (assembly.Decision, error) {{
        return assembly.Decision{{}}, nil
    }}

    func (policyClient) RecordResult(
        context.Context, assembly.RecordRequest,
    ) error {{
        return nil
    }}

    func (policyClient) Close() error {{ return nil }}

    // run wraps the named governed tool with the policy client, invokes it, and
    // prints "<label>|OK|<output>" when the action proceeds or
    // "<label>|ERROR|<message>" when governance rejects it.
    func run(label, toolName string) {{
        tool := sentinelTool{{name: toolName}}
        tools := assembly.WrapTools([]assembly.Tool{{tool}}, policyClient{{}},
            assembly.WithEnforcementMode(assembly.EnforcementModeEnforce))
        out, err := tools[0].Call(context.Background(), "payload")
        if err != nil {{
            fmt.Printf("%s|ERROR|%s\\n", label, err.Error())
            return
        }}
        fmt.Printf("%s|OK|%s\\n", label, out)
    }}

    func main() {{
        // deny Decision -> wrapper blocks before the inner tool body runs.
        run("deny", "blocked_tool")
        // allow Decision -> inner tool runs and returns its body output.
        run("allow", "allowed_tool")
    }}
""")

_GO_MOD_SOURCE = textwrap.dedent("""\
    module consumer

    go 1.22

    require {module_path} v0.0.0

    replace {module_path} => {sdk_path}
""")

_GO_MOD_PROXY = textwrap.dedent("""\
    module consumer

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

    The local checkout may be a stale fork whose declared module path differs in
    case (e.g. ``github.com/AI-agent-assembly/...``) from the canonical
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

    ``GOFLAGS=-mod=mod`` lets ``go get`` / ``go run`` update go.mod and go.sum
    inside the throwaway consumer module without a pre-seeded lock file.
    """
    env = dict(os.environ)
    env["GOFLAGS"] = "-mod=mod"
    env.setdefault("GO111MODULE", "on")
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


def _consumer(acquisition: str, tmp: str) -> None:
    """Materialize the positive-enforcement behavioral consumer for *acquisition*."""
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
        return
    if acquisition == "proxy":
        _write_proxy_consumer(tmp)
        return
    raise ValueError(acquisition)  # pragma: no cover - guarded by parametrization


def _run_consumer(acquisition: str) -> dict[str, tuple[str, str]]:
    """Build and run the consumer; return ``{label: (status, detail)}``.

    ``status`` is ``"OK"`` (the governed action ran) or ``"ERROR"`` (governance
    rejected it); ``detail`` is the tool output or the error message.
    """
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
            f"[{COMPONENT}/{acquisition}] consumer go run failed "
            f"(exit {result.returncode})\nstdout: {result.stdout.strip()}\n"
            f"stderr: {result.stderr.strip()}"
        )
        outcomes: dict[str, tuple[str, str]] = {}
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or "|" not in line:
                continue
            label, status, detail = line.split("|", 2)
            outcomes[label] = (status, detail)
        return outcomes


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
def test_deny_decision_blocks_before_inner_tool_runs(acquisition: str) -> None:
    """deny Decision -> PolicyViolationError, inner tool body does NOT run.

    With ``Check`` returning ``Decision{Denied:true}`` and a ``nil`` error, the
    wrapper (``assembly/tool_wrapper.go``) returns a ``PolicyViolationError``
    *before* ever calling ``t.inner.Call``. The sentinel "ran:payload" output is
    the proof of inner execution; it must be absent.
    """
    skip_if_binary_missing("go")
    outcomes = _run_consumer(acquisition)

    assert "deny" in outcomes, (
        f"[{COMPONENT}/{acquisition}] consumer did not emit the deny cell; got {outcomes!r}"
    )
    status, detail = outcomes["deny"]
    assert status == "ERROR", (
        f"[{COMPONENT}/{acquisition}] a deny Decision must reject the governed "
        f"action, but it proceeded: {detail!r}"
    )
    assert "policy: blocked" in detail, (
        f"[{COMPONENT}/{acquisition}] the denial error should surface the policy "
        f"reason (PolicyViolationError), got: {detail!r}"
    )
    assert detail != "ran:payload", (
        f"[{COMPONENT}/{acquisition}] the inner tool body must NOT execute when "
        f"the Decision is deny, but it produced tool output: {detail!r}"
    )


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
def test_allow_decision_lets_inner_tool_run(acquisition: str) -> None:
    """allow Decision -> inner tool runs and returns its body output.

    With ``Check`` returning ``Decision{}`` (allow) and a ``nil`` error, the
    wrapper falls through to ``t.inner.Call`` and returns its result. The
    sentinel "ran:payload" output is the proof the inner body executed.
    """
    skip_if_binary_missing("go")
    outcomes = _run_consumer(acquisition)

    assert "allow" in outcomes, (
        f"[{COMPONENT}/{acquisition}] consumer did not emit the allow cell; got {outcomes!r}"
    )
    status, detail = outcomes["allow"]
    assert status == "OK", (
        f"[{COMPONENT}/{acquisition}] an allow Decision should let the governed "
        f"action proceed, but it was rejected: {detail!r}"
    )
    assert detail == "ran:payload", (
        f"[{COMPONENT}/{acquisition}] expected the governed tool to actually "
        f"execute under an allow Decision (output 'ran:payload'), got: {detail!r}"
    )


@pytest.mark.live
@pytest.mark.xfail(
    reason=(
        "AAASM-3172: flip-gated on a published SDK release that wires the Go "
        "SDK's (*GatewayClient).Check to a GatewayTransport + the generated gRPC "
        "CheckAction. That product fix landed (AAASM-3021, Done), but this "
        "placeholder has no live gateway + built Go SDK to prove it, so it fails "
        "today. strict=True so it XPASSes loudly the day the live deny is wired "
        "in (do not re-point to the Done AAASM-3021)."
    ),
    strict=True,
    raises=AssertionError,
)
def test_live_core_deny_blocks_tool() -> None:
    """Placeholder for the true end-to-end deny against a running aa-gateway.

    When AAASM-3172 flips this in — against a published SDK carrying the
    AAASM-3021 wiring — this cell should stand up ``aa-gateway`` with a deny
    policy and assert that the Go SDK's *real* client (not an injected stub)
    blocks the tool. Until then it raises so it is a strict xfail pinned on the
    open gate, not a dead ``run=False`` doc that can never surface a regression.
    """
    raise AssertionError("live-core deny path is flip-gated on AAASM-3172")
