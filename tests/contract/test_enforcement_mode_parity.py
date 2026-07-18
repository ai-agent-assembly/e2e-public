"""Cross-SDK enforcement-mode parity (AAASM-2993).

This is the *cross-SDK* half of the enforcement-mode contract Epic — the half
that needs **no live core**. It reads the enforcement-mode contract straight out
of each SDK's source / built artifacts and asserts the three SDKs agree on the
canonical posture vocabulary.

Two contracts are exercised:

1. **Enforcement-mode parity (assertion).** Each SDK must expose *exactly* the
   canonical posture set ``{"enforce", "observe", "disabled"}``. This is the
   wire-level governance posture sent to the gateway at registration
   (``aa_core::EnforcementMode``), so all three SDKs must agree token-for-token
   or a Python agent and a Go agent would register under incompatible postures.

2. **Init / runtime-mode divergence (pinned finding, *not* a hard failure).**
   The *transport / runtime* mode is a separate, SDK-local concept and the three
   SDKs do **not** agree on it today:

       python : auto | ebpf | proxy | sdk-only          (RuntimeMode Literal)
       node   : auto | sdk-only | grpc-sidecar | napi-inprocess  (AssemblyMode)
       go     : (functional options — no enum at all)

   That inconsistency is a real cross-SDK finding. This test *pins current
   reality* so the divergence is documented and any future drift is caught,
   rather than asserting a parity that does not exist. See
   ``test_init_runtime_mode_divergence_is_pinned`` below.

Each SDK source is resolved from the ``AASM_<LANG>_SDK_DIR`` env var the verify
harness materializes (``verify-profiles.yml`` clones each SDK under
``/tmp/aa-sdks/<lang>-sdk``), falling back to a sibling checkout for local dev.
When a source cannot be resolved — *or*, for the node probe, when a resolved SDK
still can't be exercised (toolchain absent, ``dist/`` unbuilt, or the public
``import('@agent-assembly/sdk')`` failing) — the probe skips in a normal run but
**hard-fails under strict mode** (``AASM_VERIFY_STRICT=1``): a "not found" /
"not built" skip reads as a *justified* environment prerequisite to the
skip-audit (:mod:`aasm_verify.skip_audit`), so a bare skip would let strict CI go
green having verified no cross-SDK parity at all — the AAASM-4736/4774/4808/4828
false-green class. Under strict, any un-exercised source is a coverage gap, not a
prerequisite, and the cross-SDK equality test refuses to "pass" over a subset.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from typing import NoReturn

import pytest

from aasm_verify.skip_audit import STRICT_ENV_VAR

# The single source of truth for the canonical enforcement-mode vocabulary.
# Mirrors ``aa_core::EnforcementMode`` on the wire (snake_case tokens).
CANONICAL_ENFORCEMENT_MODES: frozenset[str] = frozenset({"enforce", "observe", "disabled"})

# Known per-SDK init/runtime-mode vocabularies (the documented divergence).
# These are asserted to pin *current reality*, not a desired parity.
PYTHON_RUNTIME_MODES: frozenset[str] = frozenset({"auto", "ebpf", "proxy", "sdk-only"})
NODE_ASSEMBLY_MODES: frozenset[str] = frozenset(
    {"auto", "sdk-only", "grpc-sidecar", "napi-inprocess"}
)


# SDK checkout dir -> the env var the verify harness exports for it. These are
# the same names the fixed sibling probes read (``AASM_NODE_SDK_DIR`` in
# ``tests/public/test_node_sdk.py``, ``AASM_GO_SDK_DIR`` in
# ``tests/public/test_go_sdk.py``); ``verify-profiles.yml`` materializes each SDK
# under ``/tmp/aa-sdks/<name>`` and points these at it.
_SDK_DIR_ENV: dict[str, str] = {
    "python-sdk": "AASM_PYTHON_SDK_DIR",
    "node-sdk": "AASM_NODE_SDK_DIR",
    "go-sdk": "AASM_GO_SDK_DIR",
}


def _strict_mode() -> bool:
    """True when the run opts into strict verification (``AASM_VERIFY_STRICT=1``).

    Shared contract name with the skip-audit and the AAASM-3160 CI profiles.
    """
    return os.environ.get(STRICT_ENV_VAR) == "1"


def _stop(component: str, message: str) -> NoReturn:
    """Hard-fail under strict mode; skip (as a known prerequisite) otherwise.

    A missing SDK source is a legitimate prerequisite gate in a partial local
    run, but under ``AASM_VERIFY_STRICT=1`` it is a coverage gap: the skip-audit
    classifies a "not found"/env-var reason as *justified*, so a plain skip would
    let strict CI go green without ever verifying cross-SDK parity (AAASM-4808).
    Failing under strict is what turns that silent gap back into a red signal.

    The ``classification: known_prerequisite`` tag is a literal so the *static*
    marker audit (``aasm-verify markers``) reads it as a justified prerequisite,
    not a policy violation.
    """
    if _strict_mode():
        pytest.fail(
            f"[{component}] {message} — cross-SDK enforcement-mode parity was NOT "
            f"verified (AAASM-4808 false-green guard under {STRICT_ENV_VAR}=1)"
        )
    pytest.skip(f"[{component}] {message} (classification: known_prerequisite)")


def _resolve_sdk_dir(name: str) -> str | None:
    """Resolve an SDK source checkout, or None when none is available.

    Prefers ``AASM_<LANG>_SDK_DIR`` — the checkout the verify harness
    materializes (AAASM-4774/4808) so the source probe actually runs instead of
    skipping — and falls back to a sibling ``../<name>`` checkout for the
    manual/local workflow. The integration-tests checkout may be the main repo
    or an isolated git worktree, so a sibling may live three or four directories
    up. Mirrors the resolution pattern in ``tests/public/test_go_sdk.py``.
    """
    env_dir = os.environ.get(_SDK_DIR_ENV[name])
    if env_dir and os.path.isdir(env_dir):
        return os.path.normpath(env_dir)
    here = os.path.dirname(os.path.abspath(__file__))
    for up in ("../../..", "../../../.."):
        resolved = os.path.normpath(os.path.join(here, up, name))
        if os.path.isdir(resolved):
            return resolved
    return None


def _require_sdk_dir(name: str) -> str:
    """Resolve *name*'s SDK source dir or stop the test (fail under strict)."""
    resolved = _resolve_sdk_dir(name)
    if resolved is None:
        # `_stop` is NoReturn (raises pytest.fail/skip), so control never falls
        # through — the return below is reached only when a dir was resolved.
        _stop(
            name,
            f"SDK source not resolved — set {_SDK_DIR_ENV[name]} "
            f"or clone {name} alongside this repo",
        )
    return resolved


# --------------------------------------------------------------------------- #
# Per-SDK enforcement-mode extraction
# --------------------------------------------------------------------------- #


def _python_enforcement_modes() -> frozenset[str]:
    """Extract the accepted enforcement-mode tokens from the Python SDK source.

    Reads ``agent_assembly/core/assembly.py`` and parses the
    ``EnforcementMode = Literal[...]`` declaration. We parse the source rather
    than import it so the probe has zero dependency on the SDK being installed
    into this repo's virtualenv.
    """
    sdk_dir = _require_sdk_dir("python-sdk")

    assembly_py = os.path.join(sdk_dir, "agent_assembly", "core", "assembly.py")
    if not os.path.isfile(assembly_py):
        _stop("python-sdk", f"{assembly_py} not found — wrong checkout or the contract moved")

    with open(assembly_py, encoding="utf-8") as handle:
        source = handle.read()

    match = re.search(r"EnforcementMode\s*=\s*Literal\[([^\]]*)\]", source)
    assert match is not None, (
        "[python-sdk] could not locate `EnforcementMode = Literal[...]` in "
        "agent_assembly/core/assembly.py — the enforcement-mode contract moved"
    )
    tokens = frozenset(re.findall(r'"([^"]+)"', match.group(1)))
    assert tokens, "[python-sdk] EnforcementMode Literal parsed to an empty set"
    return tokens


def _node_enforcement_modes() -> frozenset[str]:
    """Extract ``ENFORCEMENT_MODES`` from the built Node SDK via its exports map.

    Imports ``@agent-assembly/sdk`` through a throwaway Node process so the
    ``package.json`` ``exports`` map (not a deep path into ``dist/``) is what
    resolves the public symbol — i.e. we verify the *public* contract a real
    consumer sees.
    """
    sdk_dir = _require_sdk_dir("node-sdk")
    # These post-resolution prerequisites route through the strict-aware `_stop`
    # (AAASM-4828, completing AAASM-4808): once the node SDK source *is* resolved,
    # a missing toolchain / unbuilt `dist/` / failed public import is no longer a
    # local-only prerequisite under strict — the verify harness materializes and
    # builds the SDK, so under `AASM_VERIFY_STRICT=1` any of these means node
    # parity was never verified. A bare `pytest.skip` here reads as *justified* to
    # the skip-audit, so strict CI would go green having verified no node parity.
    if shutil.which("node") is None:
        _stop("node-sdk", "node toolchain not available")
    if not os.path.isdir(os.path.join(sdk_dir, "dist")):
        _stop("node-sdk", "dist/ not built — run `pnpm build` in node-sdk")

    # Resolve the package by name so the `exports` map governs the import,
    # exactly as a downstream consumer would `import { ENFORCEMENT_MODES }`.
    script = (
        "import('@agent-assembly/sdk')"
        ".then(m => { process.stdout.write(JSON.stringify(m.ENFORCEMENT_MODES)); })"
        ".catch(e => { process.stderr.write(String(e && e.message || e)); process.exit(3); });"
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
        cwd=sdk_dir,
        check=False,
    )
    if result.returncode != 0:
        # The dangerous path (AAASM-4828): a resolvable node SDK whose *public*
        # `import('@agent-assembly/sdk')` fails means the exports-map contract was
        # never exercised. Under strict this is a coverage gap, not a prerequisite,
        # so it must fail — not green-skip via a skip-audit-justified reason.
        _stop(
            "node-sdk",
            f"could not import @agent-assembly/sdk (node_modules not linked?): "
            f"{result.stderr.strip()}",
        )

    modes = json.loads(result.stdout)
    assert isinstance(modes, list) and modes, (
        f"[node-sdk] ENFORCEMENT_MODES did not resolve to a non-empty array: {modes!r}"
    )
    return frozenset(modes)


def _go_enforcement_modes() -> frozenset[str]:
    """Extract the ``EnforcementMode*`` const values from the Go SDK source.

    Parses ``assembly/enforcement_mode.go`` for the ``EnforcementModeEnforce |
    Observe | Disabled`` const declarations. Source parsing keeps the probe
    independent of the Go toolchain being installed.
    """
    sdk_dir = _require_sdk_dir("go-sdk")

    enforcement_go = os.path.join(sdk_dir, "assembly", "enforcement_mode.go")
    if not os.path.isfile(enforcement_go):
        _stop("go-sdk", f"{enforcement_go} not found — wrong checkout or the contract moved")

    with open(enforcement_go, encoding="utf-8") as handle:
        source = handle.read()

    # Match `EnforcementModeEnforce EnforcementMode = "enforce"` style consts.
    tokens = frozenset(re.findall(r'EnforcementMode\w+\s+EnforcementMode\s*=\s*"([^"]+)"', source))
    assert tokens, (
        '[go-sdk] could not parse any `EnforcementMode* EnforcementMode = "..."` '
        "consts from assembly/enforcement_mode.go — the contract moved"
    )
    return tokens


# --------------------------------------------------------------------------- #
# Check 1 — enforcement-mode parity
# --------------------------------------------------------------------------- #


@pytest.mark.sdk
def test_python_enforcement_modes_are_canonical() -> None:
    """Python ``EnforcementMode`` is exactly {enforce, observe, disabled}."""
    assert _python_enforcement_modes() == CANONICAL_ENFORCEMENT_MODES


@pytest.mark.sdk
def test_node_enforcement_modes_are_canonical() -> None:
    """Node ``ENFORCEMENT_MODES`` is exactly {enforce, observe, disabled}."""
    assert _node_enforcement_modes() == CANONICAL_ENFORCEMENT_MODES


@pytest.mark.sdk
def test_go_enforcement_modes_are_canonical() -> None:
    """Go ``EnforcementMode*`` consts are exactly {enforce, observe, disabled}."""
    assert _go_enforcement_modes() == CANONICAL_ENFORCEMENT_MODES


@pytest.mark.sdk
def test_enforcement_modes_match_across_sdks() -> None:
    """All three SDKs expose an *identical* enforcement-mode set.

    This is the load-bearing cross-SDK assertion: even if every SDK individually
    matched the canonical set in the per-SDK tests above, this test guards the
    pairwise equality directly across whichever SDKs are present. In a normal run
    each absent SDK is skipped individually and the comparison runs over the SDKs
    that resolved; **under strict (``AASM_VERIFY_STRICT=1``) a skipped SDK is a
    coverage gap** — the equality would otherwise "pass" over a subset (e.g.
    python+go only) while node parity was never verified (the AAASM-4828 residual
    of the AAASM-4808 false-green class), so any skip fails the test instead.
    """
    discovered: dict[str, frozenset[str]] = {}

    for name, probe in (
        ("python", _python_enforcement_modes),
        ("node", _node_enforcement_modes),
        ("go", _go_enforcement_modes),
    ):
        try:
            discovered[name] = probe()
        except pytest.skip.Exception:
            if _strict_mode():
                # Don't silently drop an SDK under strict: a subset comparison is
                # a false green — the missing SDK's parity was never verified.
                pytest.fail(
                    f"[{name}] enforcement-mode probe skipped under "
                    f"{STRICT_ENV_VAR}=1 — cross-SDK parity cannot be verified over "
                    f"a subset (AAASM-4828/4808 false-green guard)"
                )
            # Non-strict: that SDK/toolchain is absent — skip it, compare the rest.
            continue

    if not discovered:
        pytest.skip("no SDK checkout was available to compare (classification: known_prerequisite)")

    # Every present SDK must equal the canonical set...
    for name, modes in discovered.items():
        assert modes == CANONICAL_ENFORCEMENT_MODES, (
            f"[{name}] enforcement modes {sorted(modes)} != "
            f"canonical {sorted(CANONICAL_ENFORCEMENT_MODES)}"
        )

    # ...and therefore must equal each other.
    distinct = set(discovered.values())
    assert len(distinct) == 1, "enforcement-mode sets diverge across SDKs: " + ", ".join(
        f"{name}={sorted(modes)}" for name, modes in discovered.items()
    )


# --------------------------------------------------------------------------- #
# Check 2 — init / runtime-mode divergence (pinned finding)
# --------------------------------------------------------------------------- #


def _python_runtime_modes() -> frozenset[str]:
    """Extract the Python ``RuntimeMode`` Literal tokens from the SDK source."""
    sdk_dir = _require_sdk_dir("python-sdk")
    assembly_py = os.path.join(sdk_dir, "agent_assembly", "core", "assembly.py")
    if not os.path.isfile(assembly_py):
        _stop("python-sdk", f"{assembly_py} not found — wrong checkout or the contract moved")

    with open(assembly_py, encoding="utf-8") as handle:
        source = handle.read()
    match = re.search(r"RuntimeMode\s*=\s*Literal\[([^\]]*)\]", source)
    assert match is not None, "[python-sdk] could not locate `RuntimeMode = Literal[...]`"
    return frozenset(re.findall(r'"([^"]+)"', match.group(1)))


def _node_assembly_modes() -> frozenset[str]:
    """Extract the Node ``AssemblyMode`` union tokens from the SDK source."""
    sdk_dir = _require_sdk_dir("node-sdk")
    mode_ts = os.path.join(sdk_dir, "src", "types", "assembly-mode.ts")
    if not os.path.isfile(mode_ts):
        _stop("node-sdk", f"{mode_ts} not found — wrong checkout or the contract moved")

    with open(mode_ts, encoding="utf-8") as handle:
        source = handle.read()
    # ``[^;]`` already matches whitespace, so the capture group absorbs the run
    # after ``=`` with no ``\s*`` flanking it — that overlap is what made the
    # previous pattern prone to polynomial backtracking on input without a
    # terminating ``;`` (S5852). The captured text is fed to a quoted-token
    # findall below, so leading whitespace inside the group is irrelevant.
    match = re.search(r"type\s+AssemblyMode\s*=([^;]+);", source)
    assert match is not None, "[node-sdk] could not locate `type AssemblyMode = ...`"
    return frozenset(re.findall(r'"([^"]+)"', match.group(1)))


@pytest.mark.sdk
def test_python_runtime_modes_pinned() -> None:
    """Pin the Python init mode vocabulary: auto | ebpf | proxy | sdk-only."""
    assert _python_runtime_modes() == PYTHON_RUNTIME_MODES


@pytest.mark.sdk
def test_node_assembly_modes_pinned() -> None:
    """Pin the Node init mode vocabulary: auto | sdk-only | grpc-sidecar | napi-inprocess."""
    assert _node_assembly_modes() == NODE_ASSEMBLY_MODES


@pytest.mark.sdk
def test_init_runtime_mode_divergence_is_pinned() -> None:
    """Document (and pin) the KNOWN cross-SDK init/runtime-mode divergence.

    This is a deliberate **finding, not a parity failure**. Unlike the
    enforcement-mode vocabulary — which the three SDKs share token-for-token —
    the *init / transport mode* concept is inconsistent across SDKs today:

        python : {auto, ebpf, proxy, sdk-only}        — RuntimeMode Literal
        node   : {auto, sdk-only, grpc-sidecar, napi-inprocess} — AssemblyMode
        go     : (functional options, no mode enum)

    Only ``"auto"`` and ``"sdk-only"`` are shared between Python and Node; the
    remaining tokens describe SDK-specific transports (Python names the
    interception layer: ebpf/proxy; Node names the transport mechanism:
    grpc-sidecar/napi-inprocess). Go exposes no init-mode enum at all — it
    configures transport purely through ``WithXxx`` functional options.

    The test asserts *what is* so the divergence is recorded and future drift is
    caught; it intentionally does NOT assert the three are equal.
    """
    python_modes = _python_runtime_modes()
    node_modes = _node_assembly_modes()

    # The divergence we are pinning: the two enum-bearing SDKs do NOT agree.
    assert python_modes != node_modes, (
        "Python RuntimeMode and Node AssemblyMode unexpectedly converged — if "
        "the SDKs unified their init-mode vocabulary, update this pinned finding "
        "(AAASM-2993) and the enforcement-mode parity epic notes."
    )

    # Document the exact shared subset and the SDK-specific tails.
    shared = python_modes & node_modes
    assert shared == frozenset({"auto", "sdk-only"}), (
        "the shared init-mode subset changed: "
        f"python={sorted(python_modes)} node={sorted(node_modes)} "
        f"shared={sorted(shared)} (expected only auto + sdk-only)"
    )

    python_only = python_modes - node_modes
    node_only = node_modes - python_modes
    assert python_only == frozenset({"ebpf", "proxy"}), (
        f"python-only init modes drifted: {sorted(python_only)}"
    )
    assert node_only == frozenset({"grpc-sidecar", "napi-inprocess"}), (
        f"node-only init modes drifted: {sorted(node_only)}"
    )


@pytest.mark.sdk
def test_go_has_no_init_mode_enum() -> None:
    """Pin the Go side of the divergence: Go exposes no init-mode enum.

    Go configures transport through functional options (``WithGatewayURL`` etc.
    in ``assembly/options.go``) rather than a mode enum. This test asserts the
    absence of any ``*Mode`` enum analogous to Python's ``RuntimeMode`` or
    Node's ``AssemblyMode`` — there is no ``AssemblyMode`` / ``RuntimeMode`` /
    ``InitMode`` type in the Go SDK. (``EnforcementMode`` is the governance
    posture, a different axis, and is expected to exist.)
    """
    sdk_dir = _require_sdk_dir("go-sdk")

    assembly_dir = os.path.join(sdk_dir, "assembly")
    if not os.path.isdir(assembly_dir):
        _stop("go-sdk", f"{assembly_dir} not found — wrong checkout or the contract moved")

    # Functional options must exist — that is the Go init-config mechanism.
    options_go = os.path.join(assembly_dir, "options.go")
    assert os.path.isfile(options_go), (
        "[go-sdk] assembly/options.go not found — the functional-options "
        "init mechanism that stands in for an init-mode enum is missing"
    )
    with open(options_go, encoding="utf-8") as handle:
        options_src = handle.read()
    assert re.search(r"func\s+With\w+\(", options_src), (
        "[go-sdk] no `WithXxx(...)` functional options found in options.go"
    )

    # No init-mode enum analogous to Python RuntimeMode / Node AssemblyMode.
    for go_file in os.listdir(assembly_dir):
        if not go_file.endswith(".go"):
            continue
        with open(os.path.join(assembly_dir, go_file), encoding="utf-8") as handle:
            text = handle.read()
        for forbidden in ("AssemblyMode", "RuntimeMode", "InitMode"):
            assert f"type {forbidden}" not in text, (
                f"[go-sdk] unexpected init-mode enum `type {forbidden}` in "
                f"assembly/{go_file} — Go gained an init-mode enum, so the "
                "documented divergence (AAASM-2993) is now stale and the "
                "cross-SDK init-mode parity epic should be revisited"
            )


# --------------------------------------------------------------------------- #
# SDK-source resolution guard (AAASM-4808)
# --------------------------------------------------------------------------- #
#
# These exercise the resolution/strict logic itself — harness behavior, not a
# cross-SDK probe — so they carry no ``sdk`` marker and run offline in the
# default suite. They pin the AAASM-4808 fix: an unresolvable SDK source must
# hard-fail under strict (never green-skip), and the ``AASM_*_DIR`` env var the
# verify harness sets must actually be honored.


def test_env_var_resolves_sdk_dir(monkeypatch, tmp_path) -> None:
    """``AASM_<LANG>_SDK_DIR`` is honored over (and instead of) the sibling path.

    This is the whole point of the fix: the harness materializes SDKs at
    ``/tmp/aa-sdks/<lang>-sdk`` and exports these vars — never as siblings — so a
    resolver that ignored them (the old ``_sibling_sdk_dir``) always skipped.
    """
    for name, env_var in _SDK_DIR_ENV.items():
        monkeypatch.setenv(env_var, str(tmp_path))
        assert _resolve_sdk_dir(name) == os.path.normpath(str(tmp_path))


def test_strict_mode_hard_fails_when_sdk_dir_unresolved(monkeypatch) -> None:
    """Under strict, an unresolvable SDK source is a FAILURE, not a green skip.

    Regression for the AAASM-4808 false-green: a "not found" skip reads as a
    justified env prerequisite to the skip-audit, so absent this guard strict CI
    would go green having verified no cross-SDK parity at all.
    """
    monkeypatch.setattr(
        "tests.contract.test_enforcement_mode_parity._resolve_sdk_dir", lambda name: None
    )
    monkeypatch.setenv(STRICT_ENV_VAR, "1")
    with pytest.raises(pytest.fail.Exception):
        _require_sdk_dir("python-sdk")


def test_non_strict_skips_when_sdk_dir_unresolved(monkeypatch) -> None:
    """Outside strict mode an unresolvable SDK source skips (local-dev workflow)."""
    monkeypatch.setattr(
        "tests.contract.test_enforcement_mode_parity._resolve_sdk_dir", lambda name: None
    )
    monkeypatch.delenv(STRICT_ENV_VAR, raising=False)
    with pytest.raises(pytest.skip.Exception):
        _require_sdk_dir("go-sdk")


def test_unresolved_skip_reason_is_not_a_bare_greenlight(monkeypatch) -> None:
    """The non-strict skip stays classifiable as a *prerequisite*, and the
    strict path raises rather than emitting any skip the audit could justify."""
    from aasm_verify import skip_audit

    monkeypatch.setattr(
        "tests.contract.test_enforcement_mode_parity._resolve_sdk_dir", lambda name: None
    )
    monkeypatch.delenv(STRICT_ENV_VAR, raising=False)
    with pytest.raises(pytest.skip.Exception) as excinfo:
        _require_sdk_dir("node-sdk")
    # A local-dev skip is a genuine prerequisite gate — it should read as
    # justified (env var named + classification tag), NOT as a policy violation.
    assert skip_audit.is_justified(str(excinfo.value))
