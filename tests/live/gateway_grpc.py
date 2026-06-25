"""Speak ``PolicyService.CheckAction`` gRPC to a live ``aa-gateway``.

The other ``tests/live/`` helpers only TCP-probe the gateway for readiness
(``test_live_gateway.py``) or drive the SDK over its UDS / HTTP transports
(``runtime_client.py`` / ``sdk_client.py``). None of them call the gateway's
*policy verdict* RPC. This module fills that gap: it generates Python protobuf
stubs from the core monorepo's ``proto/`` tree at runtime, opens an insecure
loopback channel to a spawned gateway, and issues a real ``CheckAction`` —
the same RPC the runtime hot-path uses — so a test can assert the product
policy engine's allow/deny verdict rather than a test-local oracle.

``grpcio`` / ``grpcio-tools`` are *optional* (the ``grpc`` extra): a plain
``uv sync`` stays gRPC-free and callers skip cleanly via
:func:`grpc_tooling_available`, mirroring the ``cargo``/``_core`` skip-guards
the rest of the live suite uses.

Why generate stubs at runtime instead of vendoring them: the proto files are
the wire-protocol source of truth in the core repo, and the live fixture
already requires a core checkout (``AASM_CORE_SOURCE_DIR`` or a clone) to build
the gateway. Generating against that same checkout keeps the stubs in lockstep
with the gateway under test instead of risking a stale committed copy.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
from functools import cache
from pathlib import Path
from types import ModuleType, SimpleNamespace

#: Proto files needed for the PolicyService.CheckAction call. ``policy.proto``
#: imports ``common.proto``; both resolve under a single ``-I <proto dir>``.
_PROTO_FILES = ("common.proto", "policy.proto")


def grpc_tooling_available() -> bool:
    """Return True when both ``grpcio`` and ``grpcio-tools`` can be imported.

    Probes without importing so a caller can skip cleanly when the optional
    ``grpc`` extra is not installed.
    """
    return (
        importlib.util.find_spec("grpc") is not None
        and importlib.util.find_spec("grpc_tools") is not None
    )


def proto_dir(core_source: Path) -> Path:
    """Return the ``proto/`` directory inside a core ``agent-assembly`` checkout."""
    return Path(core_source) / "proto"


@cache
def _generate_stubs(proto_dir_str: str) -> str:
    """Codegen the Python protobuf + gRPC stubs for *proto_dir_str*; return the out dir.

    Runs ``grpc_tools.protoc`` once per proto directory (memoised) into a fresh
    temp directory and prepends it to ``sys.path`` so the generated
    ``common_pb2`` / ``policy_pb2`` / ``policy_pb2_grpc`` modules (which import
    each other by bare filename) resolve. Raises ``RuntimeError`` if codegen
    fails.
    """
    from grpc_tools import protoc  # noqa: PLC0415 — optional dep, imported lazily

    src = Path(proto_dir_str)
    out = Path(tempfile.mkdtemp(prefix="aa-proto-py-"))
    args = [
        "protoc",
        f"-I{src}",
        f"--python_out={out}",
        f"--grpc_python_out={out}",
        *[str(src / name) for name in _PROTO_FILES],
    ]
    rc = protoc.main(args)
    if rc != 0:
        raise RuntimeError(
            f"grpc_tools.protoc failed (exit {rc}) generating stubs from {src} "
            f"for {', '.join(_PROTO_FILES)}"
        )
    # The generated modules import one another by bare name (e.g.
    # ``import common_pb2``), so the out dir must be importable directly.
    if str(out) not in sys.path:
        sys.path.insert(0, str(out))
    return str(out)


def load_policy_pb(core_source: Path) -> SimpleNamespace:
    """Generate (once) and import the gRPC stubs; return the modules namespace.

    The returned namespace exposes ``common`` (``common_pb2``), ``policy``
    (``policy_pb2``), and ``policy_grpc`` (``policy_pb2_grpc``). Call
    :func:`grpc_tooling_available` first to decide whether to skip.
    """
    _generate_stubs(str(proto_dir(core_source)))
    import common_pb2 as common  # noqa: PLC0415
    import policy_pb2 as policy  # noqa: PLC0415
    import policy_pb2_grpc as policy_grpc  # noqa: PLC0415

    return SimpleNamespace(common=common, policy=policy, policy_grpc=policy_grpc)


def _grpc() -> ModuleType:
    """Import and return the ``grpc`` runtime module (lazy, optional)."""
    import grpc  # noqa: PLC0415

    return grpc


def check_action_decision(
    endpoint: str,
    pb: SimpleNamespace,
    *,
    action_type: int,
    context: object,
    agent_id: str = "conformance-probe",
    timeout: float = 5.0,
) -> tuple[str, str]:
    """Call ``CheckAction`` on the gateway at *endpoint*; return ``(decision, reason)``.

    Builds a minimal ``CheckActionRequest`` for an *unregistered* agent with an
    empty credential token — the gateway skips credential validation for agents
    it has never registered, then runs the policy engine and returns its verdict
    (registration is not required to exercise the verdict path).

    :param endpoint: ``"host:port"`` of the gateway's gRPC listener.
    :param pb: the namespace from :func:`load_policy_pb`.
    :param action_type: a ``common.ActionType`` enum value (e.g. ``TOOL_CALL``).
    :param context: a ``policy.ActionContext`` with exactly the matching oneof set.
    :returns: ``(decision_name, reason)`` — e.g. ``("DENY", "tool denied by policy")``.
    """
    grpc = _grpc()
    request = pb.policy.CheckActionRequest(
        agent_id=pb.common.AgentId(org_id="conformance", team_id="conformance", agent_id=agent_id),
        credential_token="",
        trace_id="conformance-trace",
        span_id="conformance-span",
        action_type=action_type,
        context=context,
    )
    with grpc.insecure_channel(endpoint) as channel:
        stub = pb.policy_grpc.PolicyServiceStub(channel)
        response = stub.CheckAction(request, timeout=timeout)
    return pb.common.Decision.Name(response.decision), response.reason
