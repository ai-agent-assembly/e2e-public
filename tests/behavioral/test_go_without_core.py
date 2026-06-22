"""Behavioral tests for the Go SDK when no governance gateway is reachable.

These tests assert the Go SDK's *designed* client-side behavior with no
``aa-gateway`` running. The decisive switch lives in ``assembly/tool_wrapper.go``
(``shouldDenyOnUnavailable``): when the governance ``Check`` returns an error
(which is exactly what an unreachable gateway produces), the wrapper either
rejects the governed action or lets it proceed, depending on the resolved
``failClosed`` posture and the enforcement mode.

Since AAASM-3108/3109 the Go SDK's ``failClosed`` field **defaults to true**
(``assembly/defaults.go``): a governance check transport error or timeout *denies*
the tool call under an enforcing posture, so an unreachable gateway cannot silently
let an unchecked action run. ``shouldDenyOnUnavailable`` denies only when
``failClosed`` is set **and** the mode enforces — two independent ways an action is
allowed on a check error: the explicit ``WithFailClosed(false)`` opt-in
(``assembly/options.go``, allows under any mode), or the observe / disabled
postures (allow even with the fail-closed default, so the proxy / eBPF layers stay
authoritative). These cells assert each of those branches.

Rather than stand up a real gateway and then kill it, each cell drives the
public ``assembly.WrapTools`` / ``GovernanceClient`` surface with a client whose
``Check`` returns a connection error — a faithful, deterministic stand-in for
"no gateway reachable" that exercises the same branch in ``tool_wrapper.go``. A
tiny Go consumer module is built and run for each configuration, mirroring the
consumer-build pattern in ``tests/public/test_go_sdk.py``.

Acquisition paths, as in the public Go smoke tests:

* ``proxy``  — the canonical published module from the Go module proxy
  (``github.com/ai-agent-assembly/go-sdk``, lowercase).
* ``source`` — the local checkout next to this repo. Its ``go.mod`` declares the
  canonical lowercase module path ``github.com/ai-agent-assembly/go-sdk``;
  ``replace`` directives must match the SDK's own declared path, so the consumer
  honours whatever the checkout declares. The behavior asserted here is identical
  on both paths.

Note on enforcement mode: in the Go SDK ``WithEnforcementMode`` (enforce /
observe / disabled) is *also* consulted by the local ``tool_wrapper`` check loop
on the unavailable path (``shouldDenyOnUnavailable``): the observe and disabled
postures always allow on a check error so the proxy / eBPF layers stay
authoritative, while ``enforce`` (and the empty "gateway default" mode, which
resolves to live enforce) denies under the fail-closed default. The observe /
disabled cells therefore proceed; the enforce cell denies.
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
    // Command consumer exercises the Go SDK's no-gateway behavior across
    // enforcement configurations. The governance client always reports the
    // gateway as unreachable, so the runtime's fail-closed default (AAASM-3108)
    // vs. the WithFailClosed(false) / observe / disabled allow-on-error paths is
    // what determines each outcome.
    package main

    import (
        "context"
        "errors"
        "fmt"

        "{module_path}/assembly"
    )

    // echoTool is a trivial governed action whose Call always succeeds when it
    // is allowed to run. Its execution (or non-execution) is the observable
    // signal for whether governance let the action proceed.
    type echoTool struct{{}}

    func (echoTool) Name() string                                       {{ return "echo" }}
    func (echoTool) Description() string                                {{ return "echoes input" }}
    func (echoTool) Call(_ context.Context, in string) (string, error) {{ return "ran:" + in, nil }}

    // unreachableClient stands in for "no gateway reachable": every Check
    // fails with a connection error, the same signal a dead gateway produces.
    type unreachableClient struct{{}}

    func (unreachableClient) Check(
        context.Context, assembly.CheckRequest,
    ) (assembly.Decision, error) {{
        return assembly.Decision{{}}, errors.New(
            "dial tcp 127.0.0.1:50051: connect: connection refused")
    }}

    func (unreachableClient) WaitForApproval(
        context.Context, assembly.ApprovalRequest,
    ) (assembly.Decision, error) {{
        return assembly.Decision{{}}, nil
    }}

    func (unreachableClient) RecordResult(
        context.Context, assembly.RecordRequest,
    ) error {{
        return nil
    }}

    func (unreachableClient) Close() error {{ return nil }}

    // run wraps the governed tool with the given options, invokes it against the
    // unreachable gateway, and prints "<label>|OK|<output>" when the action
    // proceeds or "<label>|ERROR|<message>" when governance rejects it.
    func run(label string, opts ...assembly.Option) {{
        tools := assembly.WrapTools([]assembly.Tool{{echoTool{{}}}}, unreachableClient{{}}, opts...)
        out, err := tools[0].Call(context.Background(), "payload")
        if err != nil {{
            fmt.Printf("%s|ERROR|%s\\n", label, err.Error())
            return
        }}
        fmt.Printf("%s|OK|%s\\n", label, out)
    }}

    func main() {{
        // enforce + no gateway + default (failClosed=true, AAASM-3108) ->
        // action rejected.
        run("enforce_default", assembly.WithEnforcementMode(assembly.EnforcementModeEnforce))
        // enforce + no gateway + explicit WithFailClosed(true) -> action
        // rejected (same as the default; the explicit opt-in is asserted too).
        run("enforce_failclosed",
            assembly.WithEnforcementMode(assembly.EnforcementModeEnforce),
            assembly.WithFailClosed(true))
        // enforce + no gateway + WithFailClosed(false) -> action proceeds: the
        // explicit fail-open opt-in allows on a check error regardless of mode.
        run("enforce_failopen",
            assembly.WithEnforcementMode(assembly.EnforcementModeEnforce),
            assembly.WithFailClosed(false))
        // observe + no gateway -> action proceeds (allow-on-error posture).
        run("observe", assembly.WithEnforcementMode(assembly.EnforcementModeObserve))
        // disabled + no gateway -> action proceeds (allow-on-error posture).
        run("disabled", assembly.WithEnforcementMode(assembly.EnforcementModeDisabled))
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
            f"unreachable)\nstderr: {result.stderr.strip()}"
        )


def _consumer(acquisition: str, tmp: str) -> None:
    """Materialize the no-gateway behavioral consumer for *acquisition*."""
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
def test_enforce_no_gateway_default_fails_closed(acquisition: str) -> None:
    """enforce + no gateway + default -> governed action errors (fail-closed).

    This is the secure fail-closed default (AAASM-3108/3109): with the gateway
    unreachable the governance ``Check`` errors, and because ``failClosed``
    defaults to ``true`` (``assembly/defaults.go``) under an enforcing posture
    ``shouldDenyOnUnavailable`` denies, so the wrapper returns an error instead
    of running the tool unchecked.
    """
    skip_if_binary_missing("go")
    outcomes = _run_consumer(acquisition)

    assert "enforce_default" in outcomes, (
        f"[{COMPONENT}/{acquisition}] consumer did not emit the enforce_default "
        f"cell; got {outcomes!r}"
    )
    status, detail = outcomes["enforce_default"]
    assert status == "ERROR", (
        f"[{COMPONENT}/{acquisition}] the fail-closed default should reject the "
        f"governed action with no gateway under enforce, but it proceeded: "
        f"{detail!r}"
    )
    assert detail != "ran:payload", (
        f"[{COMPONENT}/{acquisition}] the governed tool must NOT execute under the "
        f"fail-closed default with no gateway, but it produced tool output: "
        f"{detail!r}"
    )


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
def test_enforce_no_gateway_fail_closed_denies(acquisition: str) -> None:
    """enforce + no gateway + WithFailClosed(true) -> governed action errors.

    The explicit fail-closed posture (``assembly/options.go``), which matches the
    AAASM-3108 default: with the gateway unreachable the wrapper returns an error
    instead of running the tool. Asserted alongside the default so a future flip
    of the default does not silently weaken the explicit opt-in.
    """
    skip_if_binary_missing("go")
    outcomes = _run_consumer(acquisition)

    assert "enforce_failclosed" in outcomes, (
        f"[{COMPONENT}/{acquisition}] consumer did not emit the "
        f"enforce_failclosed cell; got {outcomes!r}"
    )
    status, detail = outcomes["enforce_failclosed"]
    assert status == "ERROR", (
        f"[{COMPONENT}/{acquisition}] WithFailClosed(true) should reject the "
        f"governed action when the gateway is unreachable, but it proceeded: "
        f"{detail!r}"
    )
    assert detail != "ran:payload", (
        f"[{COMPONENT}/{acquisition}] the governed tool must NOT execute under "
        f"fail-closed with no gateway, but it produced tool output: {detail!r}"
    )


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
def test_enforce_no_gateway_fail_open_optin_proceeds(acquisition: str) -> None:
    """enforce + no gateway + WithFailClosed(false) -> governed action proceeds.

    The explicit fail-open opt-in (``assembly/options.go``): with ``failClosed``
    set to false ``shouldDenyOnUnavailable`` returns early and allows on a check
    error regardless of the enforcement mode, so the wrapper falls through and
    runs the tool. This is the caller's deliberate opt-out of the secure
    AAASM-3108 default — the inverse of ``test_enforce_no_gateway_default_fails_closed``.
    """
    skip_if_binary_missing("go")
    outcomes = _run_consumer(acquisition)

    assert "enforce_failopen" in outcomes, (
        f"[{COMPONENT}/{acquisition}] consumer did not emit the enforce_failopen "
        f"cell; got {outcomes!r}"
    )
    status, detail = outcomes["enforce_failopen"]
    assert status == "OK", (
        f"[{COMPONENT}/{acquisition}] WithFailClosed(false) should let the "
        f"governed action proceed with no gateway, but it was rejected: {detail!r}"
    )
    assert detail == "ran:payload", (
        f"[{COMPONENT}/{acquisition}] expected the governed tool to actually "
        f"execute under the fail-open opt-in (output 'ran:payload'), got: {detail!r}"
    )


@pytest.mark.sdk
@pytest.mark.parametrize("acquisition", ["source", "proxy"])
@pytest.mark.parametrize("mode", ["observe", "disabled"])
def test_non_enforce_no_gateway_proceeds(acquisition: str, mode: str) -> None:
    """observe / disabled + no gateway -> governed action proceeds.

    ``shouldDenyOnUnavailable`` always allows on a check error under the observe
    and disabled postures (so the proxy / eBPF layers stay authoritative) even
    though ``failClosed`` defaults to true — only ``enforce`` denies on error.
    These cells therefore proceed.
    """
    skip_if_binary_missing("go")
    outcomes = _run_consumer(acquisition)

    assert mode in outcomes, (
        f"[{COMPONENT}/{acquisition}] consumer did not emit the {mode} cell; got {outcomes!r}"
    )
    status, detail = outcomes[mode]
    assert status == "OK", (
        f"[{COMPONENT}/{acquisition}] {mode} mode should let the governed action "
        f"proceed with no gateway, but it was rejected: {detail!r}"
    )
    assert detail == "ran:payload", (
        f"[{COMPONENT}/{acquisition}] expected the governed tool to execute "
        f"under {mode} mode (output 'ran:payload'), got: {detail!r}"
    )
