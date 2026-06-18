"""Install-path matrix verification (AAASM-3151).

Drives the :data:`install_matrix.INSTALL_MATRIX` of public-artifact install
paths — the ``aasm`` core binary and the three SDKs across source-branch / tag
/ sha / registry-release modes — and proves two things:

* **Offline (always runs):** every manifest entry is well-formed, the
  parametrization wires one test per case, the isolated-tempdir helper and the
  AC4 evidence writer behave, and every unsupported install path is explicitly
  documented (AC2).
* **Online (skip-guarded):** when the required tools and release/version inputs
  are present, the case actually installs the artifact and records the resolved
  version/ref as evidence (AC1/AC3/AC4). A missing tool or release-version input
  → SKIP; a failed install of a *present* artifact → FAIL.

The install execution is guarded by :func:`_skip_unless_runnable`, which emits a
*justified* skip reason (naming the missing binary/env var) so the repo's
skip-audit (``aasm_verify.skip_audit``) never flags it as un-justified.
"""

from __future__ import annotations

import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

from tests.install import install_matrix
from tests.install._support import (
    isolated_install_dir,
    read_install_evidence,
    write_install_evidence,
)
from tests.install.install_matrix import (
    INSTALL_MATRIX,
    MODES,
    TARGETS,
    InstallCase,
    validate_case,
    validate_matrix,
)

# Repo root: this file is at <root>/tests/install/test_install_matrix.py, so the
# scripts/ directory referenced by source-mode install argv resolves here.
_REPO_ROOT = Path(__file__).resolve().parents[2]

# Cases the matrix expects to actually run an install (vs. document-only).
_RUNNABLE_CASES: tuple[InstallCase, ...] = tuple(c for c in INSTALL_MATRIX if not c.unsupported)
_UNSUPPORTED_CASES: tuple[InstallCase, ...] = tuple(c for c in INSTALL_MATRIX if c.unsupported)


def _resolve_template(argv: tuple[str, ...], *, dest: str = "") -> tuple[str, ...]:
    """Fill ``{ref}`` / ``{version}`` / ``{dest}`` placeholders.

    Source modes read their ref from a mode-specific env var; registry modes
    read ``AASM_RELEASE_VERSION``. ``go`` versions get a ``v`` prefix. ``{dest}``
    is the isolated per-case clone directory. Returns the argv unchanged when no
    placeholder is present.
    """
    version = os.environ.get("AASM_RELEASE_VERSION", "")
    ref = (
        os.environ.get("AA_CORE_TAG")
        or os.environ.get("AA_CORE_SHA")
        or os.environ.get("AA_REF")
        or "master"
    )
    resolved = []
    for arg in argv:
        if "{version}" in arg:
            v = f"v{version}" if "go-sdk" in arg and not version.startswith("v") else version
            arg = arg.replace("{version}", v)
        if "{ref}" in arg:
            arg = arg.replace("{ref}", ref)
        if "{dest}" in arg:
            arg = arg.replace("{dest}", dest)
        resolved.append(arg)
    return tuple(resolved)


def _missing_tools(case: InstallCase) -> list[str]:
    """Return required binaries that are absent from PATH."""
    return [tool for tool in case.required_tools if shutil.which(tool) is None]


def _missing_input_env(case: InstallCase) -> list[str]:
    """Return required input env vars that are unset/empty."""
    return [name for name in case.required_input_env if not os.environ.get(name)]


def _github_reachable() -> bool:
    """True when github.com:443 accepts a TCP connection within 2s.

    Source-mode installs clone from GitHub; in an offline sandbox the clone
    cannot run, so the case skips (justified: network requirement) rather than
    failing on a network error that is not an install-path regression.
    """
    try:
        with socket.create_connection(("github.com", 443), timeout=2):
            return True
    except OSError:
        return False


def _skip_unless_runnable(case: InstallCase) -> None:
    """Skip with a *justified* reason when tools or release inputs are absent.

    The reason names the concrete missing binary or env var so the repo's
    skip-audit treats the skip as justified (an environment requirement),
    never an un-justified coverage gap. Ticket semantics: a missing
    release/version input → SKIP (here); a failed install of a present
    artifact → FAIL (left to the test body).
    """
    missing_tools = _missing_tools(case)
    if missing_tools:
        pytest.skip(
            f"[{case.target}] required tool(s) not found in PATH: "
            f"{', '.join(missing_tools)} — install to run the {case.mode} install path"
        )
    missing_env = _missing_input_env(case)
    if missing_env:
        pytest.skip(
            f"[{case.target}] required input env not set: {', '.join(missing_env)} "
            f"— set it to supply the release/ref for the {case.mode} install path"
        )
    # Source-mode installs clone from GitHub; registry installs reach PyPI/npm/
    # the Go proxy. Either way a network is required — skip (justified) offline.
    if not _github_reachable():
        pytest.skip(
            f"[{case.target}] network not available (github.com:443 unreachable) "
            f"— the {case.mode} install path requires network access (AAASM-3151)"
        )


# --------------------------------------------------------------------------- #
# Offline: manifest schema + matrix wiring (always runs)
# --------------------------------------------------------------------------- #


def test_matrix_is_non_empty() -> None:
    """The install matrix defines at least one case per target."""
    covered = {case.target for case in INSTALL_MATRIX}
    assert covered == set(TARGETS), f"every target must appear in the matrix; got {covered}"


def test_matrix_schema_is_valid() -> None:
    """Every manifest entry is well-formed (modes valid, argv + expected present)."""
    errors = validate_matrix()
    assert not errors, "manifest schema violations:\n" + "\n".join(
        f"  {e.case_id}: {e.problem}" for e in errors
    )


@pytest.mark.parametrize("case", INSTALL_MATRIX, ids=lambda c: c.id)
def test_each_case_is_well_formed(case: InstallCase) -> None:
    """Each individual case passes per-entry schema validation."""
    errors = validate_case(case)
    assert not errors, f"{case.id}: " + "; ".join(e.problem for e in errors)


@pytest.mark.parametrize("case", INSTALL_MATRIX, ids=lambda c: c.id)
def test_each_case_mode_is_known(case: InstallCase) -> None:
    """Each case uses a known mode and target (parametrization wiring check)."""
    assert case.mode in MODES
    assert case.target in TARGETS


def test_ac1_source_branch_covered_for_agent_assembly() -> None:
    """AC1: a source-branch install path exists for agent-assembly (aasm)."""
    ids = {case.id for case in INSTALL_MATRIX}
    assert "aasm-source-branch" in ids


def test_ac2_tag_sha_paths_present_or_documented() -> None:
    """AC2: every target's tag/SHA install path is present or marked unsupported.

    For each target the matrix must either provide a tag/sha/gomod install case
    (a real pinned-install path) or explicitly mark a tag-mode case unsupported
    with a reason — never silently omit it.
    """
    pinned_modes = {"tag", "sha", "gomod"}
    for target in TARGETS:
        target_cases = [c for c in INSTALL_MATRIX if c.target == target]
        has_pinned = any(c.mode in pinned_modes and not c.unsupported for c in target_cases)
        has_documented = any(
            c.unsupported and c.unsupported_reason.strip() for c in target_cases
        )
        assert has_pinned or has_documented, (
            f"target {target!r} must cover a tag/SHA install path or document it "
            "as unsupported (AC2)"
        )


@pytest.mark.parametrize("case", _UNSUPPORTED_CASES, ids=lambda c: c.id)
def test_unsupported_cases_carry_a_reason(case: InstallCase) -> None:
    """AC2: an unsupported install path documents WHY it is unsupported."""
    assert case.unsupported_reason.strip(), (
        f"{case.id} is unsupported but carries no reason"
    )
    assert not case.install_argv and not case.verify_argv


def test_ac3_registry_release_paths_cover_all_ecosystems() -> None:
    """AC3: a registry/release install path exists for Python, Node, Go, runtime."""
    registry_cases = {
        (c.target, c.mode) for c in INSTALL_MATRIX if install_matrix.is_registry_mode(c.mode)
    }
    assert ("python-sdk", "pypi") in registry_cases
    assert ("node-sdk", "npm") in registry_cases
    assert ("go-sdk", "gomod") in registry_cases
    # Runtime artifact (the released aasm binary) where available:
    assert ("aasm", "release") in registry_cases


# --------------------------------------------------------------------------- #
# Offline: tempdir helper + evidence writer behavior (always runs)
# --------------------------------------------------------------------------- #


def test_isolated_install_dir_is_fresh_and_separate(tmp_path: Path) -> None:
    """The tempdir helper yields a fresh, empty, per-case directory."""
    a = isolated_install_dir(tmp_path, "aasm-source-branch")
    b = isolated_install_dir(tmp_path, "python-sdk-pypi")
    assert a.is_dir() and not any(a.iterdir())
    assert a != b
    (a / "marker").write_text("x")
    # A second case's dir is unaffected by the first.
    assert not any(b.iterdir())


def test_evidence_writer_roundtrips_resolved_ref(tmp_path: Path) -> None:
    """AC4: the evidence writer records and reads back the resolved version/ref."""
    out = write_install_evidence(
        tmp_path,
        case_id="aasm-source-branch",
        target="aasm",
        mode="source-branch",
        expected_ref_kind="ref",
        expected_ref="branch tip SHA",
        resolved="deadbeefcafe",
        verify_argv=("git", "rev-parse", "HEAD"),
    )
    assert out.is_file()
    evidence = read_install_evidence(out)
    assert evidence.resolved == "deadbeefcafe"
    assert evidence.case_id == "aasm-source-branch"
    assert evidence.verify_argv == ["git", "rev-parse", "HEAD"]


def test_template_resolution_substitutes_placeholders(monkeypatch: pytest.MonkeyPatch) -> None:
    """Placeholder resolution fills {version}/{ref} and v-prefixes go versions."""
    monkeypatch.setenv("AASM_RELEASE_VERSION", "0.0.1")
    monkeypatch.delenv("AA_CORE_TAG", raising=False)
    monkeypatch.delenv("AA_CORE_SHA", raising=False)
    monkeypatch.setenv("AA_REF", "master")
    py = _resolve_template(("pip", "install", "agent-assembly=={version}"))
    assert py == ("pip", "install", "agent-assembly==0.0.1")
    go = _resolve_template(
        ("go", "get", "github.com/ai-agent-assembly/go-sdk@{version}")
    )
    assert go[-1].endswith("@v0.0.1")
    src = _resolve_template(("--ref", "{ref}"))
    assert src == ("--ref", "master")


# --------------------------------------------------------------------------- #
# Online: actual install execution (skip-guarded — justified offline skips)
# --------------------------------------------------------------------------- #


@pytest.mark.release
@pytest.mark.parametrize("case", _RUNNABLE_CASES, ids=lambda c: c.id)
def test_install_path_reports_version_or_ref(case: InstallCase, tmp_path: Path) -> None:
    """Run a supported install path and record the resolved version/ref (AC4).

    Skips (justified) when the required tools or release inputs are absent.
    Fails when a *present* artifact's install or verify command errors — that is
    a real install-path regression, not a missing prerequisite.
    """
    _skip_unless_runnable(case)

    work = isolated_install_dir(tmp_path, case.id)
    # Source-mode clones land in a sub-dir of the work tree; verify runs there.
    clone_dest = work / "checkout"
    is_source = install_matrix.is_source_mode(case.mode)
    install_argv = _resolve_template(case.install_argv, dest=str(clone_dest))
    verify_argv = _resolve_template(case.verify_argv, dest=str(clone_dest))

    # Source-mode installs invoke repo scripts; run them from the repo root so
    # their relative scripts/ paths resolve. Registry installs run in the
    # isolated work dir so node_modules / go.mod stay out of the checkout.
    install_cwd = _REPO_ROOT if is_source else work
    install = subprocess.run(
        list(install_argv),
        cwd=str(install_cwd),
        capture_output=True,
        text=True,
    )
    assert install.returncode == 0, (
        f"[{case.target}] install failed (exit {install.returncode}) for {case.id}\n"
        f"stderr: {install.stderr.strip()}"
    )

    # Verify the install where it landed: the clone dir for source modes, the
    # isolated work dir for registry modes.
    verify_cwd = clone_dest if is_source else work
    verify = subprocess.run(
        list(verify_argv),
        cwd=str(verify_cwd),
        capture_output=True,
        text=True,
    )
    assert verify.returncode == 0, (
        f"[{case.target}] verify failed (exit {verify.returncode}) for {case.id}\n"
        f"stderr: {verify.stderr.strip()}"
    )
    resolved = verify.stdout.strip()
    assert resolved, f"[{case.target}] verify reported no version/ref for {case.id}"

    evidence_file = write_install_evidence(
        tmp_path,
        case_id=case.id,
        target=case.target,
        mode=case.mode,
        expected_ref_kind=case.expected_ref_kind,
        expected_ref=case.expected_ref,
        resolved=resolved,
        verify_argv=case.verify_argv,
    )
    assert evidence_file.is_file()
