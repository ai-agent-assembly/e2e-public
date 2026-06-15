"""Registry install verification: PyPI, npm, and Go module.

All tests require ``AASM_RELEASE_VERSION`` in the environment; they skip when
it is absent.  Each test installs the versioned package into an isolated
temporary directory so that no global state is modified.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tests.public.conftest import release_version

COMPONENT_PYTHON = "python-sdk"
COMPONENT_NODE = "node-sdk"
COMPONENT_GO = "go-sdk"

PYPI_PACKAGE = "agent-assembly"
NPM_PACKAGE = "@agent-assembly/sdk"
GO_MODULE = "github.com/ai-agent-assembly/go-sdk"


def _require_version() -> str:
    v = release_version()
    if v is None:
        pytest.skip("AASM_RELEASE_VERSION not set — skipping registry install tests")
    return v


@pytest.mark.release
def test_pypi_install_python_sdk(tmp_path: Path) -> None:
    """pip install agent-assembly=={version} succeeds and the package is importable."""
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

    # Read the installed package.json from disk rather than via require():
    # packages with an "exports" map don't expose "./package.json", so
    # require('@agent-assembly/sdk/package.json') throws ERR_PACKAGE_PATH_NOT_EXPORTED.
    pkg_json = work_dir / "node_modules" / "@agent-assembly" / "sdk" / "package.json"
    assert pkg_json.is_file(), (
        f"[{COMPONENT_NODE}] {NPM_PACKAGE} package.json not found after install at {pkg_json}"
    )
    installed_version = json.loads(pkg_json.read_text()).get("version", "")
    assert installed_version, (
        f"[{COMPONENT_NODE}] package.json version is empty after install"
    )


@pytest.mark.release
def test_go_module_version_install(tmp_path: Path) -> None:
    """go get github.com/ai-agent-assembly/go-sdk@v{version} resolves without error."""
    from tests.public.conftest import skip_if_binary_missing

    skip_if_binary_missing("go")
    version = _require_version()
    go_version = f"v{version}" if not version.startswith("v") else version

    work_dir = tmp_path / "go-test"
    work_dir.mkdir()

    init_result = subprocess.run(
        ["go", "mod", "init", "aa-registry-test"],
        capture_output=True,
        text=True,
        cwd=str(work_dir),
    )
    assert init_result.returncode == 0, (
        f"[{COMPONENT_GO}] go mod init failed (exit {init_result.returncode})\n"
        f"stderr: {init_result.stderr.strip()}"
    )

    get_result = subprocess.run(
        ["go", "get", f"{GO_MODULE}@{go_version}"],
        capture_output=True,
        text=True,
        cwd=str(work_dir),
        env={**__import__("os").environ, "GOFLAGS": "-mod=mod"},
    )
    if get_result.returncode != 0:
        stderr = get_result.stderr
        not_found = (
            "no matching versions" in stderr
            or "unknown revision" in stderr
            or "not found" in stderr
        )
        if not_found:
            pytest.skip(
                f"[{COMPONENT_GO}] {GO_MODULE}@{go_version} not in module proxy — "
                "classification: known_prerequisite"
            )
        pytest.fail(
            f"[{COMPONENT_GO}] go get failed (exit {get_result.returncode})\n"
            f"stdout: {get_result.stdout.strip()}\nstderr: {get_result.stderr.strip()}"
        )

    list_result = subprocess.run(
        ["go", "list", "-m", GO_MODULE],
        capture_output=True,
        text=True,
        cwd=str(work_dir),
        env={**__import__("os").environ, "GOFLAGS": "-mod=mod"},
    )
    assert list_result.returncode == 0, (
        f"[{COMPONENT_GO}] go list -m failed (exit {list_result.returncode})\n"
        f"stderr: {list_result.stderr.strip()}"
    )
    assert go_version in list_result.stdout, (
        f"[{COMPONENT_GO}] Expected {go_version!r} in go list output, "
        f"got: {list_result.stdout.strip()!r}"
    )
