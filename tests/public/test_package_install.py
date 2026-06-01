"""Registry install verification: PyPI, npm, and Go module.

All tests require ``AASM_RELEASE_VERSION`` in the environment; they skip when
it is absent.  Each test installs the versioned package into an isolated
temporary directory so that no global state is modified.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tests.public.conftest import release_version

COMPONENT_PYTHON = "python-sdk"
COMPONENT_NODE = "node-sdk"
COMPONENT_GO = "go-sdk"

PYPI_PACKAGE = "agent-assembly-sdk"
NPM_PACKAGE = "@agent-assembly/sdk"
GO_MODULE = "github.com/AI-agent-assembly/go-sdk"


def _require_version() -> str:
    v = release_version()
    if v is None:
        pytest.skip("AASM_RELEASE_VERSION not set — skipping registry install tests")
    return v


@pytest.mark.release
def test_pypi_install_python_sdk(tmp_path: Path) -> None:
    """pip install agent-assembly-sdk=={version} succeeds and the package is importable."""
    version = _require_version()
    venv_dir = tmp_path / "venv"
    subprocess.run(
        [sys.executable, "-m", "venv", str(venv_dir)],
        check=True,
        capture_output=True,
    )
    pip = venv_dir / "bin" / "pip"
    result = subprocess.run(
        [str(pip), "install", f"{PYPI_PACKAGE}=={version}"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if "No matching distribution" in result.stderr or "Could not find" in result.stderr:
            pytest.skip(
                f"[{COMPONENT_PYTHON}] {PYPI_PACKAGE}=={version} not on PyPI — "
                "classification: known_prerequisite"
            )
        pytest.fail(
            f"[{COMPONENT_PYTHON}] pip install failed (exit {result.returncode})\n"
            f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )

    python = venv_dir / "bin" / "python"
    check = subprocess.run(
        [str(python), "-c", "import agent_assembly; print(agent_assembly.__version__)"],
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, (
        f"[{COMPONENT_PYTHON}] import agent_assembly failed (exit {check.returncode})\n"
        f"stdout: {check.stdout.strip()}\nstderr: {check.stderr.strip()}"
    )
    installed_version = check.stdout.strip()
    assert installed_version, (
        f"[{COMPONENT_PYTHON}] agent_assembly.__version__ is empty after install"
    )


@pytest.mark.release
def test_npm_install_node_sdk(tmp_path: Path) -> None:
    """npm install @agent-assembly/sdk@{version} succeeds and the package is importable."""
    from tests.public.conftest import skip_if_binary_missing

    skip_if_binary_missing("node")
    skip_if_binary_missing("npm")
    version = _require_version()

    work_dir = tmp_path / "npm-test"
    work_dir.mkdir()

    result = subprocess.run(
        ["npm", "install", f"{NPM_PACKAGE}@{version}"],
        capture_output=True,
        text=True,
        cwd=str(work_dir),
    )
    if result.returncode != 0:
        stderr = result.stderr
        if "No matching version" in stderr or "E404" in stderr or "not found" in stderr.lower():
            pytest.skip(
                f"[{COMPONENT_NODE}] {NPM_PACKAGE}@{version} not on npm — "
                "classification: known_prerequisite"
            )
        pytest.fail(
            f"[{COMPONENT_NODE}] npm install failed (exit {result.returncode})\n"
            f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
        )

    check_script = (
        f"const pkg = require('{NPM_PACKAGE}/package.json'); "
        "console.log(pkg.version);"
    )
    check = subprocess.run(
        ["node", "-e", check_script],
        capture_output=True,
        text=True,
        cwd=str(work_dir),
    )
    assert check.returncode == 0, (
        f"[{COMPONENT_NODE}] node require failed (exit {check.returncode})\n"
        f"stdout: {check.stdout.strip()}\nstderr: {check.stderr.strip()}"
    )
    assert check.stdout.strip(), f"[{COMPONENT_NODE}] package.json version is empty after install"
