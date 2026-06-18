"""Offline validation of the clean-environment examples manifest (AAASM-3153).

These tests never touch the network, a binary, or the examples checkout — they
validate the *manifest itself*, so they always run and pass in any environment
(that is what makes them the offline backbone of this suite). They guard:

* **schema** — every entry has the fields the clean-env runner relies on, in
  the right shape (AC1/AC2/AC3 commands are well-formed argv);
* **classification** — every entry is quick or framework_heavy, and a
  representative quick set exists per language (AC1/AC2/AC3 coverage); and
* **AC4 optional-reason** — every optional / framework-heavy example carries a
  non-empty reason, so the optionality is auditable rather than silent.
"""

from __future__ import annotations

import pytest

from tests.examples import manifest
from tests.examples.manifest import (
    CLASSIFICATIONS,
    FRAMEWORK_HEAVY,
    LANGUAGES,
    QUICK,
    Example,
)

# Parametrize over every manifest entry by its stable id.
_ALL = manifest.EXAMPLES
_IDS = [e.id for e in _ALL]


@pytest.mark.examples
def test_manifest_is_non_empty() -> None:
    """The manifest lists at least one example to validate."""
    assert _ALL, "examples manifest is empty — nothing to validate"


@pytest.mark.examples
def test_example_ids_are_unique() -> None:
    """Every example has a unique ``<language>-<name>`` parametrization id."""
    ids = [e.id for e in _ALL]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    assert not duplicates, f"duplicate example ids in manifest: {duplicates}"


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_example_language_is_known(example: Example) -> None:
    """Each example's language is one of the supported languages."""
    assert example.language in LANGUAGES, (
        f"{example.id}: language {example.language!r} not in {LANGUAGES}"
    )


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_example_rel_path_is_under_language(example: Example) -> None:
    """Each example's rel_path is forward-slashed and rooted at its language dir."""
    assert "\\" not in example.rel_path, (
        f"{example.id}: rel_path must use forward slashes, got {example.rel_path!r}"
    )
    assert example.rel_path.startswith(f"{example.language}/"), (
        f"{example.id}: rel_path {example.rel_path!r} must start with "
        f"{example.language!r}/"
    )


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_example_run_cmd_is_nonempty_argv(example: Example) -> None:
    """Each example has a non-empty run command of plain string tokens.

    A well-formed argv is what lets the runner spawn the documented clean-setup
    run command without a shell.
    """
    assert example.run_cmd, f"{example.id}: run_cmd must not be empty"
    assert all(isinstance(tok, str) and tok for tok in example.run_cmd), (
        f"{example.id}: run_cmd tokens must be non-empty strings: {example.run_cmd!r}"
    )


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_example_install_cmd_tokens_are_strings(example: Example) -> None:
    """The install command (when present) is plain string-token argv."""
    assert all(isinstance(tok, str) and tok for tok in example.install_cmd), (
        f"{example.id}: install_cmd tokens must be non-empty strings: "
        f"{example.install_cmd!r}"
    )


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_example_declares_required_tools(example: Example) -> None:
    """Each example names at least one required tool for its env-skip guard."""
    assert example.required_tools, (
        f"{example.id}: required_tools is empty — the env-skip guard needs at "
        "least one tool to probe (AC5)"
    )


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_example_classification_is_known(example: Example) -> None:
    """Each example is classified quick or framework_heavy (AC4)."""
    assert example.classification in CLASSIFICATIONS, (
        f"{example.id}: classification {example.classification!r} not in "
        f"{CLASSIFICATIONS}"
    )


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_optional_or_heavy_examples_state_a_reason(example: Example) -> None:
    """Optional / framework-heavy examples carry a non-empty reason (AC4).

    This is the auditability guarantee: an example may be excluded from the
    required clean run only when the manifest *says why*.
    """
    needs_reason = example.optional or example.classification == FRAMEWORK_HEAVY
    if needs_reason:
        assert example.optional_reason.strip(), (
            f"{example.id}: optional/framework_heavy example must state an "
            "optional_reason (AC4)"
        )


@pytest.mark.examples
@pytest.mark.parametrize("example", _ALL, ids=_IDS)
def test_quick_examples_are_not_optional(example: Example) -> None:
    """Quick examples form the required set, so none may be marked optional."""
    if example.classification == QUICK:
        assert not example.optional, (
            f"{example.id}: a quick example must not be optional — it is part "
            "of the required clean-env baseline (AC1/AC2/AC3)"
        )


@pytest.mark.examples
@pytest.mark.parametrize("language", LANGUAGES)
def test_each_language_has_a_quick_representative(language: str) -> None:
    """Every language has at least one required quick example (AC1/AC2/AC3)."""
    quick = [e for e in manifest.quick_examples() if e.language == language]
    assert quick, (
        f"language {language!r} has no quick (required) example — clean-env "
        "validation for that language would never run"
    )
