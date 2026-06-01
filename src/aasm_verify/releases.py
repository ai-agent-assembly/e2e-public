"""Release-mode target matrix for Agent Assembly public verification."""

from __future__ import annotations

from dataclasses import dataclass

_PRERELEASE_MARKERS: tuple[str, ...] = (
    "alpha",
    "beta",
    "rc",
    ".a",
    ".b",
    "-alpha",
    "-beta",
    "-rc",
    "a0",
    "a1",
    "a2",
    "a3",
    "a4",
    "a5",
    "a6",
    "a7",
    "a8",
    "a9",
)


@dataclass(frozen=True)
class ReleaseTargetMatrix:
    """Per-ecosystem version forms for a single product release version.

    Maps one bare product version to the format expected by each public
    distribution channel: PyPI, npm, Go module proxy, GitHub Releases,
    crates.io, Homebrew tap.
    """

    version: str
    github_tag: str
    pypi_version: str
    npm_version: str
    go_version: str
    crates_version: str
    is_prerelease: bool
