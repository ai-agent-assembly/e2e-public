"""Clean-environment examples manifest (AAASM-3153).

The `agent-assembly-examples
<https://github.com/ai-agent-assembly/examples>`_ repo is the
public surface this suite validates: each example must install and run from a
**clean** environment (a fresh ``uv sync`` / ``pnpm install --frozen-lockfile``
/ ``go test``), not from whatever happens to be cached on the developer's box.

This module is the single source of truth for *which* examples we validate and
*how*. It is **pure data plus a small schema** — it imports nothing beyond the
stdlib and never touches the network — so the manifest-validation tests
(schema, quick/heavy classification, AC4 optional-reason) run and pass fully
offline. The actual install-and-run tests parametrize over :data:`EXAMPLES`
and are skip-guarded on the environment they need (a binary, a writable cache,
the examples checkout, the network).

Why a manifest at all? Because clean-environment validation has two failure
modes that must never be confused (AC5):

* an **environment** is missing (no ``pnpm``, offline, no checkout) — the
  example is *not at fault*, so the test must **skip** with an env reason; and
* the **example or product** is broken (install fails, run exits non-zero,
  expected output absent) — that must **fail**.

Encoding the install/run contract as data lets every language test share one
clean-tempdir runner that draws this exact distinction, rather than three
hand-rolled copies that drift.
"""

from __future__ import annotations

from dataclasses import dataclass

# Languages we validate. Mirrors the top-level directory layout of the
# examples repo (``python/`` ``node/`` ``go/``) and the SDK trio.
LANGUAGES: tuple[str, ...] = ("python", "node", "go")

# Classification flag values for the quick-vs-framework-heavy split (AC4).
#
# * ``quick`` examples install and run with only the SDK toolchain and finish
#   fast with no external service — they are the representative set we *require*
#   to pass from clean (AC1/AC2/AC3).
# * ``framework_heavy`` examples pull a large framework (LangChain, a web
#   server, an agent runtime) and/or need an external service. AC4 lets these
#   be **explicitly marked optional** — but only with a stated ``optional_reason``
#   so the choice is auditable rather than silent.
QUICK: str = "quick"
FRAMEWORK_HEAVY: str = "framework_heavy"
CLASSIFICATIONS: tuple[str, ...] = (QUICK, FRAMEWORK_HEAVY)

# Documented per-language install and run commands, shared by every example of
# that language (the examples follow one convention per language).
_UV_SYNC_DEV_CMD: tuple[str, ...] = ("uv", "sync", "--extra", "dev")
_PYTEST_RUN_CMD: tuple[str, ...] = ("uv", "run", "pytest", "tests/", "-q")
_PNPM_FROZEN_INSTALL_CMD: tuple[str, ...] = ("pnpm", "install", "--frozen-lockfile")
_GO_TEST_RUN_CMD: tuple[str, ...] = ("go", "test", "./...")


@dataclass(frozen=True)
class Example:
    """One validated example and its clean-environment install/run contract.

    Attributes:
        name: Stable identifier, unique within its language. Matches the
            example's directory name under ``<language>/`` in the examples repo.
        language: One of :data:`LANGUAGES`.
        rel_path: Path to the example relative to the examples-repo root, using
            forward slashes (e.g. ``"python/quickstart"``).
        install_cmd: Argv (no shell) that installs the example's deps from a
            **clean** checkout — the documented clean-setup command. Empty tuple
            means "no install step" (the run command is self-contained).
        run_cmd: Argv (no shell) that runs / type-checks / smoke-tests the
            example after install.
        expected_exit: The exit code a healthy run returns (0 for all current
            examples). A different code is an example/product failure, not an
            environment one.
        expected_output_substring: A substring that must appear in stdout/stderr
            of a healthy run, or ``""`` to assert only on exit code.
        required_tools: External binaries that must be on ``PATH`` to run this
            example. Absence ⇒ an env **skip**, never a fail (AC5).
        required_services: External services (a running gateway, a DB) the
            example needs. A non-empty list means the example cannot run in a
            bare sandbox and is skip-guarded on the service.
        classification: One of :data:`CLASSIFICATIONS`.
        optional: When ``True`` the example is excluded from the required clean
            run set (AC4); it still appears in the manifest and is validated for
            schema, but its install/run test is marked optional.
        optional_reason: Why an example is optional. **Required** (non-empty)
            whenever ``optional`` is ``True`` or ``classification`` is
            ``framework_heavy`` — this is the AC4 auditability guarantee.
    """

    name: str
    language: str
    rel_path: str
    install_cmd: tuple[str, ...]
    run_cmd: tuple[str, ...]
    expected_exit: int = 0
    expected_output_substring: str = ""
    required_tools: tuple[str, ...] = ()
    required_services: tuple[str, ...] = ()
    classification: str = QUICK
    optional: bool = False
    optional_reason: str = ""

    @property
    def id(self) -> str:
        """Return a stable pytest parametrization id (``<language>-<name>``)."""
        return f"{self.language}-{self.name}"


# The representative example set. Two quick examples per language form the
# required clean-run baseline (AC1/AC2/AC3); one framework-heavy example per
# language is included but marked optional with a reason (AC4).
#
# Paths and commands describe the documented clean-setup flow for each example;
# the examples repo is not checked out in this sandbox, so the install-and-run
# tests skip until it is present. The manifest itself is validated offline.
EXAMPLES: tuple[Example, ...] = (
    # --- Python (uv sync, then the documented `uv run pytest`) ---------------
    # custom-tool-policy and llamaindex-tool-policy both run fully offline with
    # no API key and no gateway (per their READMEs), making them the
    # representative quick clean-env set for Python.
    Example(
        name="custom-tool-policy",
        language="python",
        rel_path="python/custom-tool-policy",
        install_cmd=_UV_SYNC_DEV_CMD,
        run_cmd=_PYTEST_RUN_CMD,
        required_tools=("uv",),
        classification=QUICK,
    ),
    Example(
        name="llamaindex-tool-policy",
        language="python",
        rel_path="python/llamaindex-tool-policy",
        install_cmd=_UV_SYNC_DEV_CMD,
        run_cmd=_PYTEST_RUN_CMD,
        required_tools=("uv",),
        classification=QUICK,
    ),
    Example(
        name="langchain-research-agent",
        language="python",
        rel_path="python/langchain-research-agent",
        install_cmd=_UV_SYNC_DEV_CMD,
        run_cmd=_PYTEST_RUN_CMD,
        required_tools=("uv",),
        required_services=("gateway",),
        classification=FRAMEWORK_HEAVY,
        optional=True,
        optional_reason=(
            "Pulls the full LangChain stack and exercises a network-allowlist "
            "policy against *.openai.com with a daily budget; the realistic "
            "run wants a gateway and an OPENAI_API_KEY. Excluded from the bare "
            "clean-env smoke and validated only when AASM_RUN_FRAMEWORK_HEAVY=1."
        ),
    ),
    # --- Node (pnpm install --frozen-lockfile, then tsc typecheck) -----------
    # custom-tool-policy and openai-node-tool-policy run offline (no gateway,
    # no key) and expose a `typecheck` script (tsc --noEmit).
    Example(
        name="custom-tool-policy",
        language="node",
        rel_path="node/custom-tool-policy",
        install_cmd=_PNPM_FROZEN_INSTALL_CMD,
        run_cmd=("pnpm", "run", "typecheck"),
        required_tools=("pnpm", "node"),
        classification=QUICK,
    ),
    Example(
        name="openai-node-tool-policy",
        language="node",
        rel_path="node/openai-node-tool-policy",
        install_cmd=_PNPM_FROZEN_INSTALL_CMD,
        run_cmd=("pnpm", "run", "typecheck"),
        required_tools=("pnpm", "node"),
        classification=QUICK,
    ),
    Example(
        name="mastra",
        language="node",
        rel_path="node/mastra",
        install_cmd=_PNPM_FROZEN_INSTALL_CMD,
        run_cmd=("pnpm", "run", "build"),
        required_tools=("pnpm", "node"),
        classification=FRAMEWORK_HEAVY,
        optional=True,
        optional_reason=(
            "Pulls the full Mastra agent framework; the dependency tree is "
            "large and slow to install from clean, so it is excluded from the "
            "fast clean-env smoke and validated only when "
            "AASM_RUN_FRAMEWORK_HEAVY=1."
        ),
    ),
    # --- Go (go test ./... with a writable GOCACHE, AAASM-3149) --------------
    # basic-agent and tool-policy both test fully offline against an in-process
    # mock GovernanceClient (no gateway required, per their READMEs).
    Example(
        name="basic-agent",
        language="go",
        rel_path="go/basic-agent",
        install_cmd=(),  # `go test` resolves modules itself; no separate install.
        run_cmd=_GO_TEST_RUN_CMD,
        required_tools=("go",),
        classification=QUICK,
    ),
    Example(
        name="tool-policy",
        language="go",
        rel_path="go/tool-policy",
        install_cmd=(),
        run_cmd=_GO_TEST_RUN_CMD,
        required_tools=("go",),
        classification=QUICK,
    ),
    Example(
        name="cli-runtime-integration",
        language="go",
        rel_path="go/cli-runtime-integration",
        install_cmd=(),
        run_cmd=_GO_TEST_RUN_CMD,
        required_tools=("go",),
        required_services=("aasm-runtime",),
        classification=FRAMEWORK_HEAVY,
        optional=True,
        optional_reason=(
            "Auto-starts the `aasm` CLI runtime sidecar process; a faithful "
            "run needs the installed `aasm` binary as a service. Excluded from "
            "the bare clean-env smoke and validated only when "
            "AASM_RUN_FRAMEWORK_HEAVY=1."
        ),
    ),
)

# The env flag that opts framework-heavy examples into the run set (AC4). When
# unset, optional examples skip with a justified env reason rather than fail.
FRAMEWORK_HEAVY_ENV_VAR: str = "AASM_RUN_FRAMEWORK_HEAVY"


def quick_examples() -> tuple[Example, ...]:
    """Return the non-optional, quick-classified representative examples."""
    return tuple(e for e in EXAMPLES if not e.optional and e.classification == QUICK)


def examples_for_language(language: str) -> tuple[Example, ...]:
    """Return every manifest example for ``language``."""
    return tuple(e for e in EXAMPLES if e.language == language)
