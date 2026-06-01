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


def build_release_matrix(version: str, *, prerelease: bool = False) -> ReleaseTargetMatrix:
    """Map a bare product version string to per-ecosystem version forms.

    Args:
        version: bare version string, e.g. ``"0.0.1"`` or ``"0.0.1-alpha.1"``.
            A leading ``"v"`` is accepted and stripped.
        prerelease: force pre-release classification even when the version
            string contains no recognised pre-release marker.

    Returns:
        :class:`ReleaseTargetMatrix` with per-ecosystem version forms.

    Raises:
        ValueError: if *version* is empty or contains only whitespace.
    """
    if not version or not version.strip():
        raise ValueError("version must be a non-empty string")

    bare = version.strip().lstrip("v")
    if not bare:
        raise ValueError(f"version {version!r} has no content after stripping 'v'")

    is_pre = prerelease or any(m in bare.lower() for m in _PRERELEASE_MARKERS)

    return ReleaseTargetMatrix(
        version=bare,
        github_tag=f"v{bare}",
        pypi_version=bare,
        npm_version=bare,
        go_version=f"v{bare}",
        crates_version=bare,
        is_prerelease=is_pre,
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
