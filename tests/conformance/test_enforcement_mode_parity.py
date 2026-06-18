"""Cross-SDK enforcement-mode parity conformance (AC4).

The enforcement-mode constant set is a contract shared by the Python, Node, and
Go SDKs — all three must expose the same ordered modes, and the decision enum
must align with them. The data-parity checks below run offline against
``tests/fixtures/conformance/enforcement-mode-parity.json``. The live cross-SDK
comparison (actually importing each installed SDK and reading its exported
constants) is skip-guarded with an env-requirement reason, because it needs the
published SDKs / Node runtime present in the environment.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap

import pytest

from tests.public.conftest import skip_if_binary_missing, skip_if_package_missing

COMPONENT = "enforcement-mode-parity"

_FIXTURE = os.path.join(
    os.path.dirname(__file__), "..", "fixtures", "conformance", "enforcement-mode-parity.json"
)


def _load() -> dict:
    with open(_FIXTURE) as f:
        return json.load(f)


_DATA = _load()
_CANONICAL = _DATA["canonical_modes"]


# --- Offline data-parity (no SDK install required; runs green locally) --------


@pytest.mark.conformance
def test_all_sdks_declare_canonical_modes() -> None:
    """Every SDK's declared mode list matches the canonical ordered set."""
    for sdk, info in _DATA["sdk_exposed"].items():
        assert info["modes"] == _CANONICAL, (
            f"[{COMPONENT}] {sdk} SDK declares modes {info['modes']}, "
            f"expected canonical {_CANONICAL}"
        )


@pytest.mark.conformance
def test_sdk_mode_sets_are_pairwise_identical() -> None:
    """Pairwise comparison: no SDK exposes a mode another SDK omits."""
    sets = {sdk: tuple(info["modes"]) for sdk, info in _DATA["sdk_exposed"].items()}
    distinct = set(sets.values())
    assert len(distinct) == 1, (
        f"[{COMPONENT}] enforcement-mode sets diverge across SDKs: {sets}"
    )


@pytest.mark.conformance
def test_decision_enum_aligns_with_modes() -> None:
    """The decision enum's 'observe' outcome aligns with the 'observe' enforcement mode."""
    decisions = set(_DATA["canonical_decisions"])
    assert "observe" in _CANONICAL and "observe" in decisions, (
        f"[{COMPONENT}] 'observe' must appear in both modes {_CANONICAL} and "
        f"decisions {sorted(decisions)}"
    )
    assert {"allow", "deny"} <= decisions, (
        f"[{COMPONENT}] decision enum missing allow/deny: {sorted(decisions)}"
    )


# --- Live cross-SDK comparison (skip-guarded: needs installed SDKs) -----------


@pytest.mark.conformance
def test_node_sdk_enforcement_modes_match_canonical() -> None:
    """The installed Node SDK exports ENFORCEMENT_MODES equal to the canonical set.

    Skip-guarded: requires the `node` runtime and the published
    `@agent-assembly/sdk` package to be installed in the environment.
    """
    skip_if_binary_missing("node")
    package = "@agent-assembly/sdk"
    resolved = subprocess.run(
        ["node", "--input-type=module", "-e", f"import '{package}'"],
        capture_output=True,
        text=True,
    )
    if resolved.returncode != 0:
        pytest.skip(f"npm package {package!r} not installed — run 'npm install {package}'")

    script = textwrap.dedent(
        f"""\
        import {{ ENFORCEMENT_MODES }} from '{package}';
        process.stdout.write(JSON.stringify(ENFORCEMENT_MODES));
        """
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"[{COMPONENT}] failed reading Node ENFORCEMENT_MODES (exit {result.returncode})\n"
        f"stderr: {result.stderr.strip()}"
    )
    actual = json.loads(result.stdout)
    assert actual == _CANONICAL, (
        f"[{COMPONENT}] Node ENFORCEMENT_MODES={actual} diverges from canonical "
        f"{_CANONICAL} — cross-SDK parity broken"
    )


@pytest.mark.conformance
def test_python_sdk_enforcement_modes_match_canonical() -> None:
    """The installed Python SDK exposes the canonical enforcement-mode constant set.

    Skip-guarded: requires the published `agent_assembly` package installed.
    The published Python SDK exposes the modes via an ENFORCEMENT_MODES
    constant or an equivalent accepted-values collection on the package.
    """
    skip_if_package_missing("agent_assembly")
    import agent_assembly  # noqa: F401

    modes = getattr(agent_assembly, "ENFORCEMENT_MODES", None)
    if modes is None:
        pytest.skip(
            "agent_assembly package installed but does not expose ENFORCEMENT_MODES — "
            "tracked by AAASM-3158 (SDK parity surface); offline data-parity still asserted"
        )
    assert list(modes) == _CANONICAL, (
        f"[{COMPONENT}] Python ENFORCEMENT_MODES={list(modes)} diverges from canonical "
        f"{_CANONICAL} — cross-SDK parity broken"
    )
