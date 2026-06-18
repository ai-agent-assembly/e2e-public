"""Shared plumbing for the live SDK→runtime policy-enforcement E2E (AAASM-3152).

This module is the language-agnostic half of the enforcement E2E. It owns:

* the **allow/deny policy fixture** the live gateway loads (path + a stdlib-only
  parser/validator so the policy's *structure* can be asserted offline, with no
  cargo/protoc/SDK), and
* **SDK availability probes** for the Node and Go SDKs — which, unlike the Python
  SDK's importable ``_core`` extension, are reached by spawning their own
  toolchains (``node``/``pnpm``, ``go``). A probe lets each per-language E2E skip
  cleanly with a *justified* reason (env requirement) when a toolchain or SDK is
  absent, exactly as the existing live tests do.

The two product gaps that make the deny path unprovable today live in the
per-language test modules as ``strict=True`` xfails, not here — this module only
supplies the shared fixtures so those tests stay small. See ``test_sdk_runtime.py``
for the Python native-FFI transport the allow path reuses.
"""

from __future__ import annotations

import shutil
from pathlib import Path

#: The allow/deny policy the live gateway loads for the enforcement E2E. One
#: deny rule (``tool.restricted``) plus a catch-all allow, so a single fixture
#: drives both the allow and the deny path through a real core.
ENFORCEMENT_POLICY = (
    Path(__file__).parent / "fixtures" / "policies" / "allow-deny-enforcement.yaml"
)

#: The action the policy denies — the deny-path tests must see this BLOCKED.
RESTRICTED_ACTION = "tool.restricted"

#: An action the policy allows via the catch-all — the allow-path tests run it.
ALLOWED_ACTION = "tool.search"


def _assign_rule_field(
    current: dict[str, object], stripped: str, indent: int, in_match: bool
) -> bool:
    """Apply one ``key: value`` line to *current*; return the next ``in_match``.

    A nested ``match`` field (indented past the rule keys) lands in the rule's
    ``match`` map; an ``id``/``effect``/``priority`` key lands on the rule itself
    and ends any in-progress ``match`` block. Other lines are ignored.
    """
    if ":" not in stripped:
        return in_match
    key, _, value = stripped.partition(":")
    key = key.strip()
    value = value.strip().strip('"')
    if in_match and indent > 6:
        match_map = current["match"]
        assert isinstance(match_map, dict)
        match_map[key] = value
        return in_match
    if key in {"id", "effect", "priority"}:
        current[key] = value
        return False
    return in_match


def load_policy_rules(policy_path: Path = ENFORCEMENT_POLICY) -> list[dict[str, object]]:
    """Parse the enforcement policy's ``spec.rules`` with a stdlib-only reader.

    The fixture is a tightly-constrained subset of YAML (flat scalars + a
    ``spec.rules`` list of ``id``/``effect``/``priority``/``match`` maps), so we
    parse it by hand rather than take a PyYAML dependency this pure-stdlib repo
    does not carry. This lets the offline structural assertions run with no
    third-party package. Raises ``ValueError`` if the expected shape is absent.
    """
    rules: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    in_match = False
    seen_rules_key = False

    for raw in Path(policy_path).read_text().splitlines():
        line = raw.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip())
        stripped = line.strip()

        if stripped == "rules:":
            seen_rules_key = True
            continue
        if not seen_rules_key:
            continue

        if stripped.startswith("- "):
            # A new rule item: "- id: <value>".
            current = {}
            rules.append(current)
            in_match = False
            stripped = stripped[2:]
        if current is None:
            continue

        if stripped == "match:":
            in_match = True
            current["match"] = {}
            continue

        in_match = _assign_rule_field(current, stripped, indent, in_match)

    if not rules:
        raise ValueError(f"{policy_path} has no spec.rules — not a usable enforcement policy")
    return rules


def policy_denies(rules: list[dict[str, object]], action: str) -> bool:
    """Return True when *rules* resolve *action* to ``deny`` (priority-first).

    Mirrors the public conformance contract (``tests/conformance``): the
    highest-priority rule whose action glob matches decides; no match is
    fail-closed deny. Used by the offline structural assertion that the fixture
    genuinely blocks the restricted action and permits the allowed one.
    """
    ordered = sorted(rules, key=lambda r: -int(str(r.get("priority", 0))))
    for rule in ordered:
        match = rule.get("match", {})
        pattern = str(match.get("action", "")) if isinstance(match, dict) else ""
        if pattern == "*" or pattern == action or (
            pattern.endswith("*") and action.startswith(pattern[:-1])
        ):
            return str(rule.get("effect")) == "deny"
    return True


def node_sdk_available() -> bool:
    """Return True when the Node toolchain needed to drive the Node SDK is present.

    The Node SDK is reached by spawning ``node``/``pnpm`` against a checkout, not
    by importing it into this Python process, so availability is a toolchain
    probe. A per-language test skips cleanly (justified env requirement) when
    this is False.
    """
    return shutil.which("node") is not None and shutil.which("pnpm") is not None


def go_sdk_available() -> bool:
    """Return True when the Go toolchain needed to drive the Go SDK is present.

    Like :func:`node_sdk_available`, the Go SDK is exercised via its own
    toolchain (``go``) rather than imported here, so this is a toolchain probe
    that lets the Go E2E skip cleanly when ``go`` is absent.
    """
    return shutil.which("go") is not None
