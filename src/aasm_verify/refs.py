"""Ref/version resolver for Agent Assembly public integration verification."""

from __future__ import annotations

from dataclasses import dataclass

PUBLIC_REPOS: tuple[str, ...] = (
    "agent-assembly",
    "python-sdk",
    "node-sdk",
    "go-sdk",
    "agent-assembly-examples",
)

REGISTRY_REPOS: frozenset[str] = frozenset({"python-sdk", "node-sdk", "go-sdk"})

VALID_MODES: tuple[str, ...] = ("latest", "tag", "sha", "release")


@dataclass
class ResolvedRefs:
    """Per-repo ref strings resolved for a verification run."""

    mode: str
    agent_assembly: str = "master"
    python_sdk: str = "master"
    node_sdk: str = "master"
    go_sdk: str = "master"
    examples: str = "master"


def resolve_refs(
    mode: str,
    *,
    agent_assembly_ref: str | None = None,
    python_sdk_ref: str | None = None,
    node_sdk_ref: str | None = None,
    go_sdk_ref: str | None = None,
    examples_ref: str | None = None,
    version: str | None = None,
) -> ResolvedRefs:
    """Resolve per-repo refs for the given verification mode.

    Raises ValueError on unsupported mode/ref combinations.
    """
    if mode not in VALID_MODES:
        raise ValueError(f"Unknown mode {mode!r}. Valid modes: {', '.join(VALID_MODES)}")

    if mode == "latest":
        _reject_extra_refs_for_latest(
            agent_assembly_ref, python_sdk_ref, node_sdk_ref, go_sdk_ref, examples_ref, version
        )
        return ResolvedRefs(mode=mode)

    if mode == "release":
        _validate_release_args(
            version, agent_assembly_ref, python_sdk_ref, node_sdk_ref, go_sdk_ref, examples_ref
        )
        v = version  # already validated non-None
        go_ref = v if v.startswith("v") else f"v{v}"
        return ResolvedRefs(
            mode=mode,
            agent_assembly="master",
            python_sdk=v,
            node_sdk=v,
            go_sdk=go_ref,
            examples="master",
        )

    # tag / sha: require at least one explicit ref
    _require_at_least_one_ref(
        mode, agent_assembly_ref, python_sdk_ref, node_sdk_ref, go_sdk_ref, examples_ref
    )
    return ResolvedRefs(
        mode=mode,
        agent_assembly=agent_assembly_ref or "master",
        python_sdk=python_sdk_ref or "master",
        node_sdk=node_sdk_ref or "master",
        go_sdk=go_sdk_ref or "master",
        examples=examples_ref or "master",
    )


def _reject_extra_refs_for_latest(
    agent_assembly_ref: str | None,
    python_sdk_ref: str | None,
    node_sdk_ref: str | None,
    go_sdk_ref: str | None,
    examples_ref: str | None,
    version: str | None,
) -> None:
    # In latest mode all repos track master. Tolerate refs explicitly set to "master"
    # (CI passes them as defaults) and only reject a genuinely non-master ref or a version.
    non_master_refs = [
        ref
        for ref in (agent_assembly_ref, python_sdk_ref, node_sdk_ref, go_sdk_ref, examples_ref)
        if ref is not None and ref != "master"
    ]
    if non_master_refs or version:
        raise ValueError(
            "Mode 'latest' uses master branches for all repos. "
            "Do not pass non-master per-repo refs or --version in latest mode."
        )


def _validate_release_args(
    version: str | None,
    agent_assembly_ref: str | None,
    python_sdk_ref: str | None,
    node_sdk_ref: str | None,
    go_sdk_ref: str | None,
    examples_ref: str | None,
) -> None:
    if version is None:
        raise ValueError("Mode 'release' requires --version (e.g. --version 0.0.1).")
    if any([agent_assembly_ref, python_sdk_ref, node_sdk_ref, go_sdk_ref, examples_ref]):
        raise ValueError(
            "Mode 'release' uses --version for registry packages. "
            "Do not pass per-repo refs alongside --version."
        )


def _require_at_least_one_ref(
    mode: str,
    agent_assembly_ref: str | None,
    python_sdk_ref: str | None,
    node_sdk_ref: str | None,
    go_sdk_ref: str | None,
    examples_ref: str | None,
) -> None:
    if all(r is None for r in [agent_assembly_ref, python_sdk_ref, node_sdk_ref, go_sdk_ref, examples_ref]):
        raise ValueError(
            f"Mode {mode!r} requires at least one per-repo ref "
            "(--agent-assembly-ref, --python-sdk-ref, --node-sdk-ref, --go-sdk-ref, --examples-ref)."
        )
