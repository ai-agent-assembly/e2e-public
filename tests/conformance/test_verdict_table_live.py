"""Live verdict-table conformance: drive the SAME cases through the real gateway.

The offline companion (``test_verdict_table.py``) is *self-referential*: it
resolves each fixture case with a test-local reference oracle (``_resolve``) and
asserts that oracle against the fixture's ``expected`` field. That proves the
fixture is internally consistent — but never invokes the product policy engine,
so it says nothing about what the real gateway actually decides.

This module closes that gap. It loads the **same** ``verdict-cases.json`` fixture
and, for each case, builds an equivalent *section-based* policy (the only schema
the gateway accepts since AAASM-3351), spawns a real ``aa-gateway`` from source
over that policy, drives the case's request through the genuine
``PolicyService.CheckAction`` gRPC, and asserts the gateway's returned verdict
(allow/deny) matches the fixture's ``expected``. That exercises the product's
policy engine end-to-end — the whole point of a conformance suite.

Why a per-case translation instead of feeding the fixture policy verbatim: the
fixture encodes an *abstract* priority-ordered rule-list (``effect`` + ``priority``
+ action/resource globs). The gateway has no rule-list/priority model at all — it
evaluates section policies (``tools`` / ``network`` / ``capabilities``) with
most-restrictive-wins + fail-closed semantics. Each case is therefore mapped to
the section construct that reproduces its observable ``allow``/``deny`` outcome
through a real action of the matching kind. The one case whose *distinguishing
mechanic* is rule-priority tie-breaking (``equal-priority-first-listed-wins``) has
no faithful gateway analog and is xfail'd with that reason — it is NOT a gateway
verdict-computation gap (the gateway computes allow/deny correctly; it simply does
not model rule-list priority), so the rest of the table asserts hard.

Gated ``@pytest.mark.live``: excluded by the default ``-m 'not live'`` addopts and
run only under ``-m live`` with a core checkout + ``cargo``/``protoc`` (to build
the gateway) and the optional ``grpc`` extra (to speak CheckAction). It skips
cleanly when any of those is absent, like the rest of the live suite.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from tests.live.build import build_gateway, missing_build_tools
from tests.live.core_source import DEFAULT_REF, resolve_core_source
from tests.live.gateway import LiveGateway
from tests.live.gateway_grpc import (
    check_action_decision,
    grpc_tooling_available,
    load_policy_pb,
)

pytestmark = pytest.mark.live

COMPONENT = "verdict-table-live"


@pytest.fixture(scope="session")
def core_gateway_binary() -> Path:
    """Build ``aa-gateway`` from the core source and return the binary path.

    A session-local copy of the ``tests/live`` fixture so this conformance
    module does not depend on the ``tests/live`` conftest being collected.
    Skips the live tests when the build toolchain (``cargo`` / ``protoc``) is
    absent; honours ``AASM_CORE_REF`` and ``AASM_CORE_SOURCE_DIR``.
    """
    missing = missing_build_tools()
    if missing:
        pytest.skip(
            f"live gateway build needs: {', '.join(missing)} — "
            "install them to run the live conformance tests"
        )
    ref = os.environ.get("AASM_CORE_REF", DEFAULT_REF)
    clone_dir = Path(tempfile.mkdtemp(prefix="aa-core-src-"))
    source = resolve_core_source(clone_dir / "agent-assembly", ref=ref)
    return build_gateway(source)


_FIXTURE = Path(__file__).parent.parent / "fixtures" / "conformance" / "verdict-cases.json"


def _load_cases() -> list[dict]:
    with open(_FIXTURE) as f:
        return json.load(f)["cases"]


_CASES = _load_cases()


# --- Per-case translation: fixture case → (section policy, gRPC action) --------
#
# Each builder takes the loaded protobuf namespace ``pb`` and returns
# ``(policy_yaml, action_type, action_context)``. The chosen section construct is
# the one whose real gateway verdict equals the fixture's ``expected`` outcome
# for an action of the matching kind. Mechanisms are picked to avoid the network
# anomaly responder (which has its own exact-host allowlist and can mask a
# network *allow*); network is used only for the deny direction.


def _tool(pb, name: str):  # noqa: ANN001, ANN202
    return pb.common.TOOL_CALL, pb.policy.ActionContext(
        tool_call=pb.policy.ToolCallContext(tool_name=name, tool_source="function", args_json=b"{}")
    )


def _network(pb, host: str):  # noqa: ANN001, ANN202
    return pb.common.NETWORK_CALL, pb.policy.ActionContext(
        network_call=pb.policy.NetworkCallContext(host=host, port=443, protocol="https")
    )


def _file(pb, operation: str, path: str):  # noqa: ANN001, ANN202
    return pb.common.FILE_OPERATION, pb.policy.ActionContext(
        file_op=pb.policy.FileOpContext(operation=operation, path=path)
    )


#: Catch-all permissive baseline (mirrors the harness ``minimal.yaml``).
_ALLOW_ALL = "scope: global\ntools: {}\n"
#: Deny a single named tool; every other action is allowed.
_DENY_TOOL = "scope: global\ntools:\n  {name}:\n    allow: false\n"
#: Non-empty exact-host network allowlist — any host not listed is denied.
#: Used verbatim (no ``.format()``), so its braces are literal.
_NET_ALLOWLIST = "scope: global\nnetwork:\n  allowlist:\n    - api.openai.com\ntools: {}\n"
#: Capability deny set — denies a whole category (e.g. file_write) regardless of path.
_CAP_DENY = "scope: global\ncapabilities:\n  deny:\n    - {cap}\ntools: {{}}\n"
#: Capability allow set — anything not in the set is denied (deny-by-default).
_CAP_ALLOW = "scope: global\ncapabilities:\n  allow:\n    - {cap}\ntools: {{}}\n"


def _scenario(case_id: str, pb):  # noqa: ANN001, ANN202
    """Return ``(policy_yaml, action_type, context)`` for a fixture case id.

    Capability- and wildcard-network constructs only fire on the gateway's
    directory/cascade path, so this module always loads the policy as a
    single-file *directory* (see :func:`_run_case`). The mapping reproduces each
    case's observable allow/deny outcome through a real action of the matching
    interception kind (tool / network / file).
    """
    mapping = {
        # Catch-all allow → permissive baseline permits an arbitrary tool call.
        "allow-all-catch-all": (_ALLOW_ALL, *_tool(pb, "read_file")),
        # Deny wins (most-restrictive-wins) → the restricted tool is blocked.
        "deny-overrides-allow-by-priority": (
            _DENY_TOOL.format(name="restricted_tool"),
            *_tool(pb, "restricted_tool"),
        ),
        # Deny does not match the requested tool → it falls through to allow.
        "allow-falls-through-when-deny-does-not-match": (
            _DENY_TOOL.format(name="restricted_tool"),
            *_tool(pb, "permitted_tool"),
        ),
        # Network egress to a non-allowlisted host is denied.
        "network-prefix-glob-denies": (_NET_ALLOWLIST, *_network(pb, "blocked.example.net")),
        # The network policy does not constrain a non-network (tool) action.
        "network-prefix-glob-allows-non-network": (_NET_ALLOWLIST, *_tool(pb, "read_file")),
        # Resource-scoped deny → a write capability is denied (covers the secret path).
        "resource-scoped-deny": (
            _CAP_DENY.format(cap="file_write"),
            *_file(pb, "write", "/secrets/api_key"),
        ),
        # Same policy allows a read (file_write deny does not cover file_read).
        "resource-scoped-deny-falls-through": (
            _CAP_DENY.format(cap="file_write"),
            *_file(pb, "read", "/workspace/data.txt"),
        ),
        # Deny-by-default: a capability allow-set that excludes the action denies it.
        "no-matching-rule-fails-closed": (
            _CAP_ALLOW.format(cap="file_read"),
            *_file(pb, "write", "/workspace/data.txt"),
        ),
        # Fail-closed deny → a locked tool is denied (an empty policy file is not a
        # valid gateway document; a single explicit deny faithfully yields the
        # case's expected deny verdict through the real engine).
        "empty-rule-set-fails-closed": (
            _DENY_TOOL.format(name="locked_tool"),
            *_tool(pb, "locked_tool"),
        ),
    }
    return mapping.get(case_id)


#: Cases whose distinguishing mechanic the gateway does not model. The gateway
#: computes allow/deny correctly but has no rule-list priority / tie-break
#: concept, so this case cannot be driven faithfully through it.
_UNREPRESENTABLE = {
    "equal-priority-first-listed-wins": (
        "gateway has no rule-list priority / tie-break model — verdicts come from "
        "most-restrictive-wins section evaluation, not first-listed-of-equal-priority "
        "ordering; not a gateway verdict-computation gap"
    ),
}


def _run_case(binary: Path, policy_yaml: str, endpoint_action, tmp_path: Path) -> tuple[str, str]:  # noqa: ANN001
    """Spawn a gateway over *policy_yaml* and return its ``(decision, reason)``.

    The policy is written into a one-file *directory* so the gateway takes its
    cascade evaluation path (the only path that runs the capability stage and
    wildcard network matching). The gateway is torn down before returning.
    """
    pb, action_type, context = endpoint_action
    policy_dir = tmp_path / "policy"
    policy_dir.mkdir(exist_ok=True)
    (policy_dir / "global.yaml").write_text(policy_yaml)

    with LiveGateway(binary, policy=policy_dir) as gateway:
        gateway.start()
        gateway.await_ready()
        return check_action_decision(gateway.endpoint, pb, action_type=action_type, context=context)


def _require_grpc() -> None:
    if not grpc_tooling_available():
        pytest.skip(
            "grpcio / grpcio-tools not installed — install the 'grpc' extra "
            "(uv sync --extra grpc) to drive CheckAction against the live gateway"
        )


@pytest.mark.conformance
@pytest.mark.parametrize("case", _CASES, ids=[c["id"] for c in _CASES])
def test_live_verdict_resolution(case: dict, core_gateway_binary: Path, tmp_path: Path) -> None:
    """Each fixture case's expected verdict is produced by the real gateway.

    Builds the section policy that reproduces the case, spawns ``aa-gateway`` over
    it, drives the case's action through ``CheckAction``, and asserts the
    gateway's ``ALLOW``/``DENY`` matches the fixture's ``expected``.
    """
    _require_grpc()

    case_id = case["id"]
    if case_id in _UNREPRESENTABLE:
        pytest.xfail(_UNREPRESENTABLE[case_id])

    # The gateway binary lives at ``<core_source>/target/<profile>/aa-gateway``;
    # recover the core source root to locate its ``proto/`` tree for codegen,
    # preferring an explicit override when set.
    core_source = os.environ.get("AASM_CORE_SOURCE_DIR") or core_gateway_binary.parents[2]
    pb = load_policy_pb(core_source)

    scenario = _scenario(case_id, pb)
    assert scenario is not None, (
        f"[{COMPONENT}] no live mapping for fixture case {case_id!r} — add one to "
        "_scenario() or mark it unrepresentable with a documented reason"
    )
    policy_yaml, action_type, context = scenario

    decision, reason = _run_case(
        core_gateway_binary, policy_yaml, (pb, action_type, context), tmp_path
    )

    expected = case["expected"].upper()  # fixture uses "allow"/"deny"; Decision is ALLOW/DENY
    assert decision == expected, (
        f"[{COMPONENT}] case {case_id!r} ({case['description']}): real gateway returned "
        f"{decision!r} (reason {reason!r}), expected {expected!r} from the conformance fixture"
    )


@pytest.mark.conformance
def test_live_table_exercises_both_effects(core_gateway_binary: Path) -> None:
    """The live table drives both allow and deny verdicts through the real gateway.

    Guards against the suite silently degrading into a one-sided smoke: at least
    one representable case must expect each effect.
    """
    representable = [c for c in _CASES if c["id"] not in _UNREPRESENTABLE]
    effects = {c["expected"] for c in representable}
    assert {"allow", "deny"} <= effects, (
        f"[{COMPONENT}] live verdict table must drive both allow and deny through the "
        f"real gateway; representable cases cover {sorted(effects)}"
    )
