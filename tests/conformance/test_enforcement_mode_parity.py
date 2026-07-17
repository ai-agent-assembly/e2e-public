"""Cross-SDK enforcement-mode parity conformance (AC4).

The enforcement-mode constant set is a contract shared by the Python, Node, and
Go SDKs — all three must expose the same ordered modes, and the decision enum
must align with them. The data-parity checks below run offline against
``tests/fixtures/conformance/enforcement-mode-parity.json``.

The offline checks only prove the fixture is *self-consistent*. To keep the
fixture honest, the live cross-SDK tests — which import each installed SDK and
read its exported constants — additionally assert the fixture's *recorded* modes
match what the real SDK actually exports, so a fixture that has drifted from the
source of truth fails loudly instead of passing on its own say-so. Those live
tests still gate on the SDK/runtime being present, but the Python one is a hard
failure (not a skip) under strict mode (``AASM_VERIFY_STRICT``) when the package
is installed yet omits the parity surface — a missing cross-SDK contract stays
red rather than eroding coverage behind a green run.
"""

from __future__ import annotations

import json
import os
import subprocess
import textwrap

import pytest

from aasm_verify.reports import strict_mode_enabled
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
    # Fixture-vs-source cross-check: the offline data-parity tests above only
    # prove the fixture is self-consistent. Whenever the real Node SDK is
    # present, hold the fixture's *recorded* node modes to what the installed
    # SDK actually exports — so a fixture that has drifted from the source of
    # truth (stale after an SDK change) fails loudly instead of passing on its
    # own say-so.
    fixture_node_modes = _DATA["sdk_exposed"]["node"]["modes"]
    assert fixture_node_modes == actual, (
        f"[{COMPONENT}] fixture records node modes {fixture_node_modes} but the "
        f"installed Node SDK exports {actual} — the parity fixture has drifted "
        "from the real SDK and must be regenerated"
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
        # The Python SDK is installed but does not surface the parity constant,
        # so the live cross-check cannot run. Under strict mode this is a hard
        # failure, not a silent skip: the whole point of the harness is that a
        # missing cross-SDK surface (tracked by AAASM-3158) stays red rather
        # than eroding coverage behind a green run. Outside strict mode it
        # degrades to a justified, ticket-referenced skip while the offline
        # data-parity tests above still assert the fixture is self-consistent.
        # The reason strings are kept as literals at each call site so the
        # marker audit (`aasm-verify markers`) statically resolves the AAASM-3158
        # ref rather than flagging a variable as unreferenced.
        if strict_mode_enabled():
            pytest.fail(
                f"[{COMPONENT}] agent_assembly installed but does not expose "
                "ENFORCEMENT_MODES — AAASM-3158 (SDK parity surface); strict mode "
                "refuses to skip a missing cross-SDK contract"
            )
        pytest.skip(
            "agent_assembly package installed but does not expose ENFORCEMENT_MODES — "
            "tracked by AAASM-3158 (SDK parity surface); offline data-parity still asserted"
        )
    actual = list(modes)
    assert actual == _CANONICAL, (
        f"[{COMPONENT}] Python ENFORCEMENT_MODES={actual} diverges from canonical "
        f"{_CANONICAL} — cross-SDK parity broken"
    )
    # Fixture-vs-source cross-check (see the Node test): hold the fixture's
    # recorded python modes to what the installed SDK actually exposes so a
    # drifted fixture cannot pass on its own say-so.
    fixture_python_modes = _DATA["sdk_exposed"]["python"]["modes"]
    assert fixture_python_modes == actual, (
        f"[{COMPONENT}] fixture records python modes {fixture_python_modes} but the "
        f"installed Python SDK exposes {actual} — the parity fixture has drifted "
        "from the real SDK and must be regenerated"
    )
