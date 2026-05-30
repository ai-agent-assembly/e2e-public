"""Ref/version resolver for Agent Assembly public integration verification."""

from __future__ import annotations

PUBLIC_REPOS: tuple[str, ...] = (
    "agent-assembly",
    "python-sdk",
    "node-sdk",
    "go-sdk",
    "agent-assembly-examples",
)

REGISTRY_REPOS: frozenset[str] = frozenset({"python-sdk", "node-sdk", "go-sdk"})

VALID_MODES: tuple[str, ...] = ("latest", "tag", "sha", "release")
