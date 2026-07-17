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

import shutil
import subprocess
import tempfile
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
    # Default to a securely-created private temp dir (0700, owned by this
    # process) rather than a predictable world-writable path like
    # /tmp/aa-install/<repo>, which is a symlink/race target (S5443).
    checkout = dest or tempfile.mkdtemp(prefix="aa-install-")
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


def install_aasm_cli(
    ref: str, *, dest: str | None = None, _runner: object | None = None
) -> str | None:
    """Build the ``aasm`` CLI from ``agent-assembly`` at *ref*; return its bin dir.

    Returns the directory containing the freshly built ``aasm`` binary (for the
    caller to prepend to ``PATH`` so ``skip_if_binary_missing('aasm')`` finds it),
    or ``None`` when the Rust toolchain / ``protoc`` is unavailable. That
    best-effort gate keeps toolchain-light lanes (e.g. the Python-only ``smoke``
    profile) skipping cleanly as before, while a toolchain-equipped lane (the
    ``full`` profile, which sets up Rust + protoc) gets a real binary and the
    runtime area actually runs instead of skipping unconditionally.

    ``aa-cli`` produces the ``aasm`` binary, so a debug ``cargo build -p aa-cli``
    is enough for the runtime smoke (``aasm --version`` / ``--help``); a debug
    build keeps the extra clone+compile within the profile's time budget.
    """
    if shutil.which("cargo") is None or shutil.which("protoc") is None:
        return None
    runner = _runner if _runner is not None else subprocess.run
    checkout = install_from_source("agent-assembly", ref, dest=dest, _runner=_runner)
    runner(  # type: ignore[operator]
        [
            "cargo",
            "build",
            "-p",
            "aa-cli",
            "--manifest-path",
            str(Path(checkout) / "Cargo.toml"),
        ],
        check=True,
    )
    return str(Path(checkout) / "target" / "debug")


def install_from_release(repo: str, version: str) -> None:
    """Install a repo's published package from the registry.

    Deferred (AAASM-4736): release-mode installs are already performed in the
    workflow itself (the ``release`` profile runs ``scripts/install-from-release.sh``
    before ``pytest -m release``), so this is not part of the source-mode
    false-green defect. Left unwired rather than adding a callerless duplicate.
    """
    raise NotImplementedError
