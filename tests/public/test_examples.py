"""Smoke tests for the agent-assembly-examples repo."""

from __future__ import annotations

import os

import pytest

COMPONENT = "agent-assembly-examples"

_EXAMPLES_SKIP_REASON = (
    f"[{COMPONENT}] examples repo not found next to this repo — "
    "clone https://github.com/ai-agent-assembly/examples alongside "
    "this repo to enable examples smoke tests"
)


def _examples_path() -> str | None:
    """Return the local examples directory if it exists next to this repo."""
    candidate = os.path.join(
        os.path.dirname(__file__),
        "..", "..", "..", "..", "agent-assembly-examples",
    )
    resolved = os.path.normpath(candidate)
    return resolved if os.path.isdir(os.path.join(resolved, "python")) else None


@pytest.mark.examples
def test_examples_repo_present() -> None:
    """Examples repo is cloned next to the integration-tests repo."""
    if _examples_path() is None:
        pytest.skip(_EXAMPLES_SKIP_REASON)


@pytest.mark.examples
def test_examples_python_directory_not_empty() -> None:
    """python/ examples directory contains at least one example subdirectory."""
    path = _examples_path()
    if path is None:
        pytest.skip(_EXAMPLES_SKIP_REASON)

    python_dir = os.path.join(path, "python")
    examples = [
        entry for entry in os.scandir(python_dir)
        if entry.is_dir() and not entry.name.startswith(".")
    ]
    assert examples, (
        f"[{COMPONENT}] Expected at least one Python example in {python_dir!r}, found none"
    )


@pytest.mark.examples
def test_examples_python_readme_exists() -> None:
    """At least one Python example directory contains a README."""
    path = _examples_path()
    if path is None:
        pytest.skip(_EXAMPLES_SKIP_REASON)

    python_dir = os.path.join(path, "python")
    readmes = []
    for entry in os.scandir(python_dir):
        if entry.is_dir():
            readme = os.path.join(entry.path, "README.md")
            if os.path.isfile(readme):
                readmes.append(readme)

    assert readmes, (
        f"[{COMPONENT}] No Python example has a README.md — "
        f"expected at least one under {python_dir!r}"
    )
