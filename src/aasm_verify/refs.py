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
