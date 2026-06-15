"""Obtain the ``agent-assembly`` core source tree at a given git ref.

Mirrors the clone approach in ``scripts/install-from-branch.sh``: a
shallow clone of the ``agent-assembly`` repo at a branch, tag, or SHA.

For local development and validation, ``AASM_CORE_SOURCE_DIR`` may point
at an existing checkout (e.g. the sibling monorepo) to skip cloning —
but the default behaviour is to clone the repo by ref so CI is
reproducible from nothing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

DEFAULT_ORG = "ai-agent-assembly"
DEFAULT_REPO = "agent-assembly"
DEFAULT_REF = "master"


def core_source_override() -> Path | None:
    """Return ``AASM_CORE_SOURCE_DIR`` as a Path when set, else ``None``.

    Lets local runs point the fixture at an already-checked-out core
    monorepo instead of cloning over the network.
    """
    raw = os.environ.get("AASM_CORE_SOURCE_DIR")
    if raw:
        return Path(raw).expanduser()
    return None


def clone_core_source(
    dest: Path,
    *,
    ref: str = DEFAULT_REF,
    org: str = DEFAULT_ORG,
    repo: str = DEFAULT_REPO,
) -> Path:
    """Shallow-clone *repo* from *org* at *ref* into *dest*; return *dest*.

    Tries a depth-1 clone of the branch/tag first; falls back to a full
    clone plus checkout for refs that ``--branch`` cannot resolve (e.g.
    an arbitrary commit SHA). Raises ``subprocess.CalledProcessError``
    when git fails.
    """
    clone_url = f"https://github.com/{org}/{repo}.git"
    dest = Path(dest)

    shallow = subprocess.run(
        ["git", "clone", "--depth", "1", "--branch", ref, clone_url, str(dest)],
        capture_output=True,
        text=True,
    )
    if shallow.returncode == 0:
        return dest

    subprocess.run(
        ["git", "clone", clone_url, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "-C", str(dest), "checkout", ref],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def resolve_core_source(
    dest: Path,
    *,
    ref: str = DEFAULT_REF,
) -> Path:
    """Return a core source tree, preferring an override over cloning.

    Uses ``AASM_CORE_SOURCE_DIR`` when it points at an existing
    directory; otherwise shallow-clones the core repo at *ref* into
    *dest*.
    """
    override = core_source_override()
    if override is not None and override.is_dir():
        return override
    return clone_core_source(dest, ref=ref)
