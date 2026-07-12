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

Each SDK probe is skipped independently when that SDK's checkout or toolchain
is absent, so the suite runs in partial environments (e.g. CI without Go).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

# The single source of truth for the canonical enforcement-mode vocabulary.
# Mirrors ``aa_core::EnforcementMode`` on the wire (snake_case tokens).
CANONICAL_ENFORCEMENT_MODES: frozenset[str] = frozenset({"enforce", "observe", "disabled"})

# Known per-SDK init/runtime-mode vocabularies (the documented divergence).
# These are asserted to pin *current reality*, not a desired parity.
PYTHON_RUNTIME_MODES: frozenset[str] = frozenset({"auto", "ebpf", "proxy", "sdk-only"})
NODE_ASSEMBLY_MODES: frozenset[str] = frozenset(
    {"auto", "sdk-only", "grpc-sidecar", "napi-inprocess"}
)


def _sibling_sdk_dir(name: str) -> str | None:
    """Return a sibling SDK checkout directory if one exists next to this repo.

    The integration-tests checkout may be the main repo or an isolated git
    worktree, so the SDKs may live three or four directories up. Mirrors the
    resolution pattern in ``tests/public/test_go_sdk.py``.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for up in ("../../..", "../../../.."):
        resolved = os.path.normpath(os.path.join(here, up, name))
        if os.path.isdir(resolved):
            return resolved
    return None


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
    sdk_dir = _sibling_sdk_dir("python-sdk")
    if sdk_dir is None:
        pytest.skip("[python-sdk] checkout not found next to this repo")

    assembly_py = os.path.join(sdk_dir, "agent_assembly", "core", "assembly.py")
    if not os.path.isfile(assembly_py):
        pytest.skip(f"[python-sdk] {assembly_py} not found")

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
    sdk_dir = _sibling_sdk_dir("node-sdk")
    if sdk_dir is None:
        pytest.skip("[node-sdk] checkout not found next to this repo")
    if shutil.which("node") is None:
        pytest.skip("[node-sdk] node toolchain not available")
    if not os.path.isdir(os.path.join(sdk_dir, "dist")):
        pytest.skip(
            "[node-sdk] dist/ not built — run `pnpm build` in node-sdk "
            "(classification: known_prerequisite)"
        )

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
        pytest.skip(
            "[node-sdk] could not import @agent-assembly/sdk — "
            "classification: known_prerequisite "
            f"(node_modules not linked?)\nstderr: {result.stderr.strip()}"
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
    sdk_dir = _sibling_sdk_dir("go-sdk")
    if sdk_dir is None:
        pytest.skip("[go-sdk] checkout not found next to this repo")

    enforcement_go = os.path.join(sdk_dir, "assembly", "enforcement_mode.go")
    if not os.path.isfile(enforcement_go):
        pytest.skip(f"[go-sdk] {enforcement_go} not found")

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
    pairwise equality directly across whichever SDKs are present. Each absent SDK
    is skipped individually; the comparison runs over the SDKs that resolved.
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
            # That SDK/toolchain is absent — skip it, keep comparing the rest.
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
    sdk_dir = _sibling_sdk_dir("python-sdk")
    if sdk_dir is None:
        pytest.skip("[python-sdk] checkout not found next to this repo")
    assembly_py = os.path.join(sdk_dir, "agent_assembly", "core", "assembly.py")
    if not os.path.isfile(assembly_py):
        pytest.skip(f"[python-sdk] {assembly_py} not found")

    with open(assembly_py, encoding="utf-8") as handle:
        source = handle.read()
    match = re.search(r"RuntimeMode\s*=\s*Literal\[([^\]]*)\]", source)
    assert match is not None, "[python-sdk] could not locate `RuntimeMode = Literal[...]`"
    return frozenset(re.findall(r'"([^"]+)"', match.group(1)))


def _node_assembly_modes() -> frozenset[str]:
    """Extract the Node ``AssemblyMode`` union tokens from the SDK source."""
    sdk_dir = _sibling_sdk_dir("node-sdk")
    if sdk_dir is None:
        pytest.skip("[node-sdk] checkout not found next to this repo")
    mode_ts = os.path.join(sdk_dir, "src", "types", "assembly-mode.ts")
    if not os.path.isfile(mode_ts):
        pytest.skip(f"[node-sdk] {mode_ts} not found")

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
    sdk_dir = _sibling_sdk_dir("go-sdk")
    if sdk_dir is None:
        pytest.skip("[go-sdk] checkout not found next to this repo")

    assembly_dir = os.path.join(sdk_dir, "assembly")
    if not os.path.isdir(assembly_dir):
        pytest.skip(f"[go-sdk] {assembly_dir} not found")

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
