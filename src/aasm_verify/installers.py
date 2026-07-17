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

import importlib.util
import shutil
import subprocess
import sys
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


def install_python_sdk(
    ref: str, *, dest: str | None = None, _runner: object | None = None
) -> str | None:
    """Install the ``python-sdk`` (``agent_assembly``) from source at *ref*.

    Installs the pure-Python distribution into the *current* interpreter's
    environment, which is what makes the ``sdk`` area actually run: the per-area
    pytest subprocess is spawned from this same ``sys.executable`` (see
    :func:`aasm_verify.runners.run_area`), so once the package is importable here
    ``skip_if_package_missing('agent_assembly')`` resolves it there — no PATH/env
    plumbing is needed, unlike the ``aasm`` binary.

    Returns the checkout path, or ``None`` when ``pip`` is unavailable. That
    best-effort gate mirrors :func:`install_aasm_cli`: a toolchain-light lane
    skips the sdk area cleanly instead of hard-failing.

    The compiled PyO3 ``_core`` extension is a *separate* artifact (built via the
    native toolchain, not this pure-Python install), so the native-binding tests
    keep skipping cleanly when it is absent — installing the pure-Python client
    is enough to exercise the import / public-export / functional-install checks.
    """
    if importlib.util.find_spec("pip") is None:
        return None
    runner = _runner if _runner is not None else subprocess.run
    checkout = install_from_source("python-sdk", ref, dest=dest, _runner=_runner)
    runner(  # type: ignore[operator]
        [sys.executable, "-m", "pip", "install", checkout],
        check=True,
    )
    return checkout


def install_node_sdk(
    ref: str, *, dest: str | None = None, _runner: object | None = None
) -> str | None:
    """Build the ``node-sdk`` (``@agent-assembly/sdk``) from source at *ref*.

    Clones the SDK, installs its dependencies, and builds the pure-JS ``dist/``
    (ESM + CJS) so that ``import '@agent-assembly/sdk'`` resolves. Returns the
    checkout path, which the caller exposes via ``AASM_NODE_SDK_DIR``.

    Why the checkout path rather than a global install: an ESM ``import`` of a
    bare specifier resolves only from a ``node_modules`` on the *resolver's* cwd
    path — a throwaway temp dir does not work. Running the node smoke with its
    cwd set *inside the package's own checkout* lets Node reach the package by
    its self-reference (the ``name`` + ``exports`` map), so no separate consumer
    project or ``NODE_PATH`` plumbing is needed. That is why the ``sdk`` area's
    node test reads ``AASM_NODE_SDK_DIR`` and runs node with that cwd.

    Returns ``None`` when Node or ``pnpm`` is unavailable — the same clean-skip
    gate the other installers apply so a toolchain-light lane leaves the node
    portion of the sdk area skipping rather than hard-failing. The compiled napi
    ``.node`` addon is a *separate* native artifact (built via the Rust
    toolchain, not this pure-JS build), so the native-binding test keeps skipping
    cleanly when it is absent — the pure-JS import / public-export /
    functional-install checks run regardless.
    """
    if shutil.which("node") is None or shutil.which("pnpm") is None:
        return None
    runner = _runner if _runner is not None else subprocess.run
    checkout = install_from_source("node-sdk", ref, dest=dest, _runner=_runner)
    # ``--dir`` runs pnpm against the checkout without a process chdir (keeps this
    # process's cwd untouched). ``pnpm build`` compiles only the pure-JS dist —
    # the napi native build is deliberately not run here (see docstring).
    runner(  # type: ignore[operator]
        ["pnpm", "--dir", checkout, "install"],
        check=True,
    )
    runner(  # type: ignore[operator]
        ["pnpm", "--dir", checkout, "run", "build"],
        check=True,
    )
    return checkout


def install_go_sdk(
    ref: str, *, dest: str | None = None, _runner: object | None = None
) -> str | None:
    """Clone the ``go-sdk`` at *ref* and return the checkout path.

    The ``sdk`` area's Go smoke acquires the SDK two ways — from a local source
    checkout (a ``replace`` directive) and from the public module proxy. With no
    local checkout the *source* acquisition skips; this materializes one in a
    securely created private temp dir (via :func:`install_from_source`, which
    uses ``tempfile.mkdtemp`` — never a world-writable path, S5443) so the caller
    can point the Go test at it through ``AASM_GO_SDK_DIR``. (The proxy
    acquisition needs no local install and is unaffected.)

    Returns the checkout path, or ``None`` when the Go toolchain is unavailable —
    the same clean-skip gate the other installers apply. The native
    ``libaa_ffi_go`` is a separate artifact, so the cgo-ABI test keeps asserting
    a wired-but-unlinked shim rather than requiring the native library here.
    """
    if shutil.which("go") is None:
        return None
    return install_from_source("go-sdk", ref, dest=dest, _runner=_runner)


def install_examples(
    ref: str, *, dest: str | None = None, _runner: object | None = None
) -> str | None:
    """Clone the ``examples`` repo at *ref* and return the checkout path.

    The ``examples`` area asserts against a local examples checkout; with none in
    place it skips unconditionally. This materializes one in a securely-created
    private temp dir (via :func:`install_from_source`, which uses
    ``tempfile.mkdtemp`` — never a world-writable path, S5443) so the caller can
    point ``tests/public/test_examples.py`` at it through ``AASM_EXAMPLES_DIR``.

    Returns the checkout path, or ``None`` when ``git`` is unavailable — the same
    clean-skip gate the other installers apply so a toolchain-light lane leaves
    the examples area skipping rather than hard-failing.
    """
    if shutil.which("git") is None:
        return None
    return install_from_source("examples", ref, dest=dest, _runner=_runner)


def install_from_release(repo: str, version: str) -> None:
    """Install a repo's published package from the registry.

    Deferred (AAASM-4736): release-mode installs are already performed in the
    workflow itself (the ``release`` profile runs ``scripts/install-from-release.sh``
    before ``pytest -m release``), so this is not part of the source-mode
    false-green defect. Left unwired rather than adding a callerless duplicate.
    """
    raise NotImplementedError
