"""Install-path matrix: the public-artifact install cases this repo verifies.

This module is the single source of truth for **how a developer obtains each
Agent Assembly public artifact** — the `aasm` core binary and the three SDKs —
across every supported install path: a source branch, a git tag, a commit SHA,
and a published registry/release package (PyPI / npm / Go module proxy /
GitHub Release). It exists so the parametrized suite in
``test_install_matrix.py`` can drive one assertion per (target, mode) pair and
report the resolved version/ref of whatever it installed (AAASM-3151 AC4).

Each entry mirrors an existing entry point so the matrix never invents a new
install mechanism:

* source-branch / tag / sha  → ``scripts/install-from-{branch,tag}.sh`` and
  ``tests/install/smoke-test-rust-build.sh`` (clone at a ref).
* release / pypi / npm / gomod → ``scripts/install-from-release.sh`` and
  ``tests/public/test_package_install.py`` (registry install).

The matrix carries no live network or toolchain dependency: it is plain data
plus pure validation, so its schema can be asserted **offline**. The test
module is responsible for skip-guarding entries whose tools or release inputs
are absent (see :data:`InstallCase.required_tools` /
:attr:`InstallCase.required_input_env`).

Why a manifest rather than hand-written test functions: the install paths are a
*matrix* — the same four-or-so modes repeated across four targets — and a
manifest makes the coverage gaps (e.g. "tag/SHA install for an SDK is
unsupported") explicit and assertable rather than silently missing.
"""

from __future__ import annotations

from dataclasses import dataclass

# The four public-artifact targets this matrix covers. ``aasm`` is the core
# Rust monorepo binary; the rest are the language SDKs. These names are the
# canonical GitHub repo names (also the JIRA component names).
TARGETS: tuple[str, ...] = ("aasm", "python-sdk", "node-sdk", "go-sdk")

# Every install path the matrix knows about. ``source-branch``/``tag``/``sha``
# are git-ref clones; ``release`` is a GitHub Release artifact download;
# ``pypi``/``npm``/``gomod`` are language-registry installs.
MODES: tuple[str, ...] = (
    "source-branch",
    "tag",
    "sha",
    "release",
    "pypi",
    "npm",
    "gomod",
)

# Modes that resolve a git ref directly (no registry / release artifact).
_SOURCE_MODES: frozenset[str] = frozenset({"source-branch", "tag", "sha"})
# Modes that pull a published artifact and therefore need a release version.
_REGISTRY_MODES: frozenset[str] = frozenset({"release", "pypi", "npm", "gomod"})


@dataclass(frozen=True)
class InstallCase:
    """One install path for one public artifact.

    The fields together fully describe a verifiable install: *what* to run
    (``install_argv``), *how to confirm it* (``verify_argv``), *what ref/version
    the confirmation should report* (``expected_ref_kind``/``expected_ref``),
    and *what must be present* for the case to run rather than skip
    (``required_tools`` binaries on PATH, ``required_input_env`` env vars).

    ``unsupported`` marks an install path that does not exist for this target
    (e.g. there is no tag-pinned install story for an SDK distinct from its
    registry release); such a case carries an ``unsupported_reason`` and is
    asserted as documented rather than executed (AAASM-3151 AC2).
    """

    target: str
    mode: str
    # The argv a developer/CI would run to perform the install. Templated with
    # ``{ref}`` / ``{version}`` placeholders resolved from env at run time.
    install_argv: tuple[str, ...]
    # The argv that, after a successful install, prints the installed
    # version/ref to stdout (the AC4 evidence source).
    verify_argv: tuple[str, ...]
    # What kind of identifier ``verify_argv`` is expected to report: "ref" for a
    # git ref/SHA, "version" for a registry version string.
    expected_ref_kind: str
    # Human description of the ref/version the verify command should report,
    # e.g. "the cloned branch tip SHA" or "AASM_RELEASE_VERSION".
    expected_ref: str
    # Binaries that must be on PATH for the case to execute (else SKIP).
    required_tools: tuple[str, ...] = ()
    # Env vars that must be set to supply a ref/version (else SKIP).
    required_input_env: tuple[str, ...] = ()
    # True when this install path does not exist for this target.
    unsupported: bool = False
    # Why an ``unsupported`` path does not exist (required when unsupported).
    unsupported_reason: str = ""

    @property
    def id(self) -> str:
        """Stable pytest parametrization id, e.g. ``aasm-source-branch``."""
        return f"{self.target}-{self.mode}"


def _aasm_clone_argv(ref_placeholder: str) -> tuple[str, ...]:
    """argv that clones the core monorepo at a ref into the isolated work dir.

    Passes ``--dest {dest}`` so the clone lands inside the test's per-case
    tempdir (resolved at run time) instead of the script default under
    ``/tmp/aa-install`` — keeping the clone isolated and lettings verify run in
    the same directory.
    """
    return (
        "bash",
        "scripts/install-from-branch.sh",
        "--repo",
        "agent-assembly",
        "--ref",
        ref_placeholder,
        "--dest",
        "{dest}",
    )


# The install-path matrix. Source-mode aasm cases mirror
# ``smoke-test-rust-build.sh`` / ``install-from-branch.sh``; registry cases
# mirror ``test_package_install.py`` / ``install-from-release.sh``. SDK
# tag/SHA paths are explicitly marked unsupported (their pinned install is the
# registry release), satisfying AC2's "documented if unsupported".
INSTALL_MATRIX: tuple[InstallCase, ...] = (
    # --- aasm core: source-branch / tag / sha (AC1, AC2) ---
    InstallCase(
        target="aasm",
        mode="source-branch",
        install_argv=_aasm_clone_argv("{ref}"),
        verify_argv=("git", "rev-parse", "HEAD"),
        expected_ref_kind="ref",
        expected_ref="the cloned branch tip SHA (AA_REF, default master)",
        required_tools=("git",),
    ),
    InstallCase(
        target="aasm",
        mode="tag",
        install_argv=(
            "bash",
            "scripts/install-from-tag.sh",
            "--repo",
            "agent-assembly",
            "--tag",
            "{ref}",
            "--dest",
            "{dest}",
        ),
        verify_argv=("git", "describe", "--tags"),
        expected_ref_kind="ref",
        expected_ref="the checked-out git tag (AA_CORE_TAG)",
        required_tools=("git",),
        required_input_env=("AA_CORE_TAG",),
    ),
    InstallCase(
        target="aasm",
        mode="sha",
        install_argv=_aasm_clone_argv("{ref}"),
        verify_argv=("git", "rev-parse", "HEAD"),
        expected_ref_kind="ref",
        expected_ref="the checked-out commit SHA (AA_CORE_SHA)",
        required_tools=("git",),
        required_input_env=("AA_CORE_SHA",),
    ),
    # --- core runtime artifact: GitHub Release tarball (AC3 runtime artifact) ---
    InstallCase(
        target="aasm",
        mode="release",
        install_argv=(
            "bash",
            "scripts/install-from-release.sh",
            "--repo",
            "agent-assembly",
            "--version",
            "{version}",
        ),
        verify_argv=("aasm", "--version"),
        expected_ref_kind="version",
        expected_ref="AASM_RELEASE_VERSION (the released aasm binary version)",
        required_tools=("aasm",),
        required_input_env=("AASM_RELEASE_VERSION",),
    ),
    # --- python-sdk: PyPI release (AC3) + unsupported source pins (AC2) ---
    InstallCase(
        target="python-sdk",
        mode="pypi",
        install_argv=(
            "pip",
            "install",
            "agent-assembly=={version}",
        ),
        verify_argv=(
            "python",
            "-c",
            "import agent_assembly; print(agent_assembly.__version__)",
        ),
        expected_ref_kind="version",
        expected_ref="AASM_RELEASE_VERSION (agent_assembly.__version__)",
        required_tools=("pip", "python"),
        required_input_env=("AASM_RELEASE_VERSION",),
    ),
    InstallCase(
        target="python-sdk",
        mode="tag",
        install_argv=(),
        verify_argv=(),
        expected_ref_kind="version",
        expected_ref="n/a",
        unsupported=True,
        unsupported_reason=(
            "python-sdk has no tag-pinned public install distinct from its PyPI "
            "release; the registry version IS the pinned artifact (pypi mode)."
        ),
    ),
    # --- node-sdk: npm release (AC3) + unsupported source pins (AC2) ---
    InstallCase(
        target="node-sdk",
        mode="npm",
        install_argv=(
            "npm",
            "install",
            "@agent-assembly/sdk@{version}",
        ),
        verify_argv=(
            "node",
            "-e",
            "console.log(require('@agent-assembly/sdk/package.json').version)",
        ),
        expected_ref_kind="version",
        expected_ref="AASM_RELEASE_VERSION (installed package.json version)",
        required_tools=("npm", "node"),
        required_input_env=("AASM_RELEASE_VERSION",),
    ),
    InstallCase(
        target="node-sdk",
        mode="tag",
        install_argv=(),
        verify_argv=(),
        expected_ref_kind="version",
        expected_ref="n/a",
        unsupported=True,
        unsupported_reason=(
            "node-sdk has no tag-pinned public install distinct from its npm "
            "release; the registry version IS the pinned artifact (npm mode)."
        ),
    ),
    # --- go-sdk: Go module proxy (AC3) — gomod IS the tag/SHA install ---
    InstallCase(
        target="go-sdk",
        mode="gomod",
        install_argv=(
            "go",
            "get",
            "github.com/ai-agent-assembly/go-sdk@{version}",
        ),
        verify_argv=(
            "go",
            "list",
            "-m",
            "github.com/ai-agent-assembly/go-sdk",
        ),
        expected_ref_kind="version",
        expected_ref="v{AASM_RELEASE_VERSION} (go list -m resolved version)",
        required_tools=("go",),
        required_input_env=("AASM_RELEASE_VERSION",),
    ),
)


@dataclass(frozen=True)
class SchemaError:
    """One manifest entry that fails a schema invariant."""

    case_id: str
    problem: str


def validate_case(case: InstallCase) -> list[SchemaError]:
    """Return every schema violation for a single :class:`InstallCase`.

    A well-formed *supported* case has a valid target/mode, a non-empty install
    and verify argv, an ``expected_ref_kind`` of ``ref``/``version``, a non-empty
    ``expected_ref``, and — for registry modes — at least one
    ``required_input_env`` supplying the version. A well-formed *unsupported*
    case instead carries an ``unsupported_reason`` and empty argv.
    """
    errors: list[SchemaError] = []

    def add(problem: str) -> None:
        errors.append(SchemaError(case_id=case.id, problem=problem))

    if case.target not in TARGETS:
        add(f"unknown target {case.target!r}")
    if case.mode not in MODES:
        add(f"unknown mode {case.mode!r}")

    if case.unsupported:
        if not case.unsupported_reason.strip():
            add("unsupported case must carry a non-empty unsupported_reason")
        if case.install_argv or case.verify_argv:
            add("unsupported case must have empty install_argv and verify_argv")
        return errors

    if not case.install_argv:
        add("supported case must have a non-empty install_argv")
    if not case.verify_argv:
        add("supported case must have a non-empty verify_argv")
    if case.expected_ref_kind not in ("ref", "version"):
        add(f"expected_ref_kind must be 'ref' or 'version', got {case.expected_ref_kind!r}")
    if not case.expected_ref.strip():
        add("supported case must document a non-empty expected_ref")
    if case.mode in _REGISTRY_MODES and not case.required_input_env:
        add("registry-mode case must require a release-version input env var")

    return errors


def validate_matrix(matrix: tuple[InstallCase, ...] = INSTALL_MATRIX) -> list[SchemaError]:
    """Return every schema violation across the whole matrix.

    Also enforces matrix-level invariants: case ids are unique, and AC1's
    source-branch path for ``agent-assembly`` is present.
    """
    errors: list[SchemaError] = []
    seen: set[str] = set()
    for case in matrix:
        for err in validate_case(case):
            errors.append(err)
        if case.id in seen:
            errors.append(SchemaError(case_id=case.id, problem="duplicate case id"))
        seen.add(case.id)

    if "aasm-source-branch" not in seen:
        errors.append(
            SchemaError(
                case_id="aasm-source-branch",
                problem="AC1 requires a source-branch install case for agent-assembly",
            )
        )
    return errors


def is_source_mode(mode: str) -> bool:
    """True when *mode* clones a git ref rather than a published artifact."""
    return mode in _SOURCE_MODES


def is_registry_mode(mode: str) -> bool:
    """True when *mode* installs a published registry/release artifact."""
    return mode in _REGISTRY_MODES
