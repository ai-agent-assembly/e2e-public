"""Installation helpers that materialize the artifacts a verification area needs.

The public pytest areas (``runtime``/``sdk``/``examples``) *skip* when the
artifact they assert against — the ``aasm`` binary, an installed SDK, an examples
checkout — is absent (AAASM-4736). A run that never installs anything therefore
goes green without exercising the product (a false-green). These helpers put the
artifact in place first, delegating to the already-working
``scripts/install-from-*.sh`` entry points as the single source of truth for how
a repo is fetched rather than duplicating clone/build logic here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

# Repo root: src/aasm_verify/installers.py -> parents[2] == the repository root,
# where scripts/ lives. Resolved once so callers get an absolute path regardless
# of the process CWD.
_SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def install_from_source(
    repo: str, ref: str, *, dest: str | None = None, _runner: object | None = None
) -> str:
    """Clone *repo* at *ref* into *dest* and return the checkout path.

    Delegates to ``scripts/install-from-branch.sh`` (the canonical clone path,
    incl. its branch/tag/SHA fallback) so that logic lives in exactly one place.
    ``_runner`` is a test injection seam defaulting to :func:`subprocess.run`.
    """
    runner = _runner if _runner is not None else subprocess.run
    checkout = dest or f"/tmp/aa-install/{repo}"
    runner(  # type: ignore[operator]
        [
            "bash",
            str(_SCRIPTS_DIR / "install-from-branch.sh"),
            "--repo",
            repo,
            "--ref",
            ref,
            "--dest",
            checkout,
        ],
        check=True,
    )
    return checkout


def install_from_release(repo: str, version: str) -> None:
    """Install a repo's published package from the registry.

    Deferred (AAASM-4736): release-mode installs are already performed in the
    workflow itself (the ``release`` profile runs ``scripts/install-from-release.sh``
    before ``pytest -m release``), so this is not part of the source-mode
    false-green defect. Left unwired rather than adding a callerless duplicate.
    """
    raise NotImplementedError
