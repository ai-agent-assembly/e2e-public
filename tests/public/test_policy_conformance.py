"""Smoke tests for policy fixture well-formedness and CLI conformance path."""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

COMPONENT = "policy-conformance"

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "fixtures", "policies")
_ALLOW_DENY_BASIC = os.path.normpath(os.path.join(_FIXTURES_DIR, "allow-deny-basic.yaml"))


@pytest.mark.conformance
def test_allow_deny_fixture_exists() -> None:
    """fixtures/policies/allow-deny-basic.yaml is present in the repo."""
    assert os.path.isfile(_ALLOW_DENY_BASIC), (
        f"[{COMPONENT}] Missing fixture file: {_ALLOW_DENY_BASIC!r}"
    )


@pytest.mark.conformance
def test_allow_deny_fixture_well_formed() -> None:
    """allow-deny-basic.yaml is valid YAML with the expected top-level keys."""
    assert os.path.isfile(_ALLOW_DENY_BASIC), pytest.skip(
        f"[{COMPONENT}] Fixture not found — skipping well-formedness check"
    )

    try:
        import importlib.util

        if importlib.util.find_spec("yaml") is None:
            pytest.skip(
                f"[{COMPONENT}] PyYAML not installed — skipping YAML parse check"
            )
        import yaml  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        pytest.skip(f"[{COMPONENT}] PyYAML not installed — skipping YAML parse check")

    with open(_ALLOW_DENY_BASIC) as f:
        doc = yaml.safe_load(f)

    assert isinstance(doc, dict), (
        f"[{COMPONENT}] Expected YAML document to be a mapping, got {type(doc).__name__}"
    )
    for key in ("version", "name", "rules"):
        assert key in doc, (
            f"[{COMPONENT}] Missing required key {key!r} in allow-deny-basic.yaml"
        )
    assert isinstance(doc["rules"], list) and len(doc["rules"]) >= 1, (
        f"[{COMPONENT}] Expected at least one rule in allow-deny-basic.yaml"
    )
    effects = {r.get("effect") for r in doc["rules"]}
    assert "allow" in effects, (
        f"[{COMPONENT}] allow-deny-basic.yaml must contain at least one allow rule"
    )
    assert "deny" in effects, (
        f"[{COMPONENT}] allow-deny-basic.yaml must contain at least one deny rule"
    )


@pytest.mark.conformance
def test_aasm_verify_dry_run() -> None:
    """aasm-verify public --mode latest --dry-run exits 0 and prints the target matrix."""
    result = subprocess.run(
        [sys.executable, "-m", "aasm_verify.cli", "public", "--mode", "latest", "--dry-run"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT}] aasm-verify --dry-run failed (exit {result.returncode})\n"
        f"stdout: {result.stdout.strip()}\nstderr: {result.stderr.strip()}"
    )
    assert "Verification Target Matrix" in result.stdout, (
        f"[{COMPONENT}] Expected target matrix in dry-run output:\n{result.stdout.strip()}"
    )
    assert "dry-run" in result.stdout, (
        f"[{COMPONENT}] Expected dry-run confirmation in output:\n{result.stdout.strip()}"
    )
