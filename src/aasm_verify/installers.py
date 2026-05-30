"""Installation helpers for cloning and installing Agent Assembly repos."""

from __future__ import annotations


def install_from_source(repo: str, ref: str) -> None:
    """Clone and install a repo from a source ref (branch, tag, or SHA)."""
    raise NotImplementedError


def install_from_release(repo: str, version: str) -> None:
    """Install a repo's published package from the registry."""
    raise NotImplementedError
