"""Offline verification of the curl installer's component/profile logic (AAASM-3955).

These tests download the canonical source-of-truth installer
(``scripts/install-cli.sh`` on ``master``) and exercise its pure resolution
functions by sourcing it with ``AASM_LIB=1`` (which loads the functions without
running ``main``). They assert the component/profile model and the
component→artifact/binary naming the Homebrew formulae (AAASM-3953) and release
artifacts (AAASM-3951) must agree on — **without** needing a published release or
network beyond fetching the script.

Network is required only to fetch the installer once; if that fails the whole
module skips with a justified reason (a ``classification:`` env tag — these are
environment prerequisites, not a masked defect), never a silent gap.
"""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

RAW_INSTALLER_URL = (
    "https://raw.githubusercontent.com/ai-agent-assembly/agent-assembly/HEAD/"
    "scripts/install-cli.sh"
)


@pytest.fixture(scope="module")
def installer(tmp_path_factory: pytest.TempPathFactory):
    """Fetch the canonical installer once; skip the module if unreachable."""
    if shutil.which("sh") is None:
        pytest.skip(
            "POSIX sh unavailable — required for installer logic tests "
            "(classification: known_prerequisite)"
        )
    dest = tmp_path_factory.mktemp("installer") / "install-cli.sh"
    try:
        with urllib.request.urlopen(RAW_INSTALLER_URL, timeout=30) as resp:
            dest.write_bytes(resp.read())
    except (urllib.error.URLError, TimeoutError) as exc:  # pragma: no cover - network
        pytest.skip(
            f"installer source unreachable ({exc}); "
            "network prerequisite (classification: external_flake)"
        )
    return dest


def _eval(installer, expr: str) -> subprocess.CompletedProcess:
    """Source the installer (AASM_LIB=1, no main) and run a shell expression."""
    return subprocess.run(
        ["sh", "-c", f'AASM_LIB=1 . "{installer}"; {expr}'],
        capture_output=True,
        text=True,
    )


def _out(installer, expr: str) -> str:
    r = _eval(installer, expr)
    assert r.returncode == 0, f"expr failed: {expr}\nstderr: {r.stderr.strip()}"
    return r.stdout.strip()


@pytest.mark.parametrize(
    ("profile", "expected"),
    [("cli", "cli"), ("local", "cli runtime"), ("full", "cli runtime proxy")],
)
def test_profile_expands_to_components(installer, profile: str, expected: str) -> None:
    """`--profile` names expand to the documented component lists (ADR-014)."""
    assert _out(installer, f"resolve_profile {profile}") == expected


@pytest.mark.parametrize(
    ("component", "binary"),
    [("cli", "aasm"), ("runtime", "aa-runtime"), ("proxy", "aa-proxy"), ("ebpf", "aa-ebpf")],
)
def test_component_installs_real_binary_name(installer, component: str, binary: str) -> None:
    """Components install their REAL binary names (the CLI execs aa-*)."""
    assert _out(installer, f"component_binary {component}") == binary


def test_cli_artifact_keeps_legacy_triple_name(installer) -> None:
    """`cli` resolves the legacy target-triple artifact (no version / 'cli' token)."""
    art = _out(installer, "component_artifact cli v0.0.1-rc.2")
    assert art.startswith("aasm-")
    assert art.endswith(".tar.gz")
    assert "aasm-cli-" not in art
    assert "v0.0.1-rc.2" not in art


def test_runtime_artifact_uses_component_scheme(installer) -> None:
    """`runtime` resolves the ADR-014 aasm-<component>-<version>-<os>-<arch> name."""
    art = _out(installer, "component_artifact runtime v0.0.1-rc.2")
    assert art.startswith("aasm-runtime-v0.0.1-rc.2-")
    assert art.endswith(".tar.gz")


def test_default_selection_is_cli_only(installer) -> None:
    """No component/profile flags → CLI only (never pulls runtime implicitly)."""
    out = _out(installer, 'parse_args; echo "$COMPONENTS"')
    assert out == "cli"


def test_components_flag_selects_requested(installer) -> None:
    """`--components cli,runtime` selects exactly those (correct sh -s -- syntax)."""
    out = _out(installer, 'parse_args --components cli,runtime; echo "$COMPONENTS"')
    assert out == "cli runtime"


def test_unknown_component_fails_with_actionable_error(installer) -> None:
    """An unknown component fails fast and lists the valid names."""
    r = _eval(installer, "parse_args --component bogus")
    assert r.returncode != 0
    assert "unknown component" in (r.stdout + r.stderr).lower()
    assert "cli runtime proxy ebpf" in (r.stdout + r.stderr)


def test_unknown_profile_fails(installer) -> None:
    """An unknown profile fails fast (does not silently fall back to cli)."""
    r = _eval(installer, "parse_args --profile bogus")
    assert r.returncode != 0


def test_help_documents_pipe_syntax_and_components(installer) -> None:
    """`--help` shows the correct `sh -s --` pipe syntax and the component model."""
    out = _out(installer, "usage")
    assert "sh -s -- --components" in out
    assert "--profile" in out
    assert "--uninstall" in out  # uninstall lifecycle documented (AAASM-3957)
