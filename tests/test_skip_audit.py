"""Unit tests for aasm_verify.skip_audit (area + skip-reason auditing)."""

from __future__ import annotations

from aasm_verify import skip_audit


def test_area_from_marker_keyword() -> None:
    test = {"nodeid": "tests/public/test_anything.py::t", "keywords": ["sdk"]}
    assert skip_audit.area_for_test(test) == "sdk"


def test_area_marker_takes_precedence_over_nodeid() -> None:
    # runtime marker wins even though the file stem suggests sdk.
    test = {"nodeid": "tests/public/test_python_sdk.py::t", "keywords": ["runtime"]}
    assert skip_audit.area_for_test(test) == "runtime"


def test_area_falls_back_to_nodeid_stem() -> None:
    test = {"nodeid": "tests/public/test_homebrew_install.py::t", "keywords": []}
    assert skip_audit.area_for_test(test) == "install"


def test_area_unknown_is_other() -> None:
    test = {"nodeid": "tests/misc/test_zzz.py::t", "keywords": []}
    assert skip_audit.area_for_test(test) == "other"


def test_extract_skip_reason_strips_skipped_prefix() -> None:
    test = {
        "outcome": "skipped",
        "call": {"longrepr": ["f.py", 3, "Skipped: requires the aasm binary"]},
    }
    assert skip_audit.extract_skip_reason(test) == "requires the aasm binary"


def test_extract_skip_reason_reads_setup_phase() -> None:
    test = {
        "outcome": "skipped",
        "setup": {"longrepr": ["f.py", 1, "Skipped: package not installed"]},
    }
    assert skip_audit.extract_skip_reason(test) == "package not installed"


def test_is_justified_true_for_jira_ref() -> None:
    assert skip_audit.is_justified("blocked by AAASM-3000 deadlock")


def test_is_justified_true_for_env_requirement() -> None:
    assert skip_audit.is_justified("'aasm' not found in PATH")
    assert skip_audit.is_justified("Python package 'foo' not installed")
    assert skip_audit.is_justified("set AASM_RELEASE_VERSION to run this")
    assert skip_audit.is_justified("clone the examples repo alongside this one")


def test_is_justified_true_for_known_prerequisite_classification() -> None:
    # The repo's documented taxonomy: a self-tagged known_prerequisite /
    # external_flake skip is a justified environment-conditional skip.
    assert skip_audit.is_justified("aasm@1.2.3 not on PyPI — classification: known_prerequisite")
    assert skip_audit.is_justified("GitHub API unreachable (classification: external_flake)")


def test_is_justified_false_for_release_blocker_classification() -> None:
    # release_blocker names a real defect — its classification alone must NOT
    # justify a skip; it still needs a tracking ticket or env requirement.
    assert not skip_audit.is_justified(
        "binary reports wrong version — classification: release_blocker"
    )


def test_is_justified_false_for_bare_reason() -> None:
    assert not skip_audit.is_justified("temporarily disabled")
    assert not skip_audit.is_justified("just because")


def test_is_justified_false_for_empty_reason() -> None:
    assert not skip_audit.is_justified("")
    assert not skip_audit.is_justified("   ")


def test_find_unjustified_skips_returns_only_bare_skips() -> None:
    data = {
        "tests": [
            {
                "nodeid": "tests/public/test_a.py::ok_env",
                "keywords": ["sdk"],
                "outcome": "skipped",
                "call": {"longrepr": ["a.py", 1, "Skipped: binary not found in PATH"]},
            },
            {
                "nodeid": "tests/public/test_a.py::ok_jira",
                "keywords": ["sdk"],
                "outcome": "skipped",
                "call": {"longrepr": ["a.py", 2, "Skipped: blocked by AAASM-1"]},
            },
            {
                "nodeid": "tests/public/test_a.py::bad",
                "keywords": ["sdk"],
                "outcome": "skipped",
                "call": {"longrepr": ["a.py", 3, "Skipped: meh"]},
            },
            {
                "nodeid": "tests/public/test_a.py::passing",
                "keywords": ["sdk"],
                "outcome": "passed",
            },
        ]
    }
    offenders = skip_audit.find_unjustified_skips(data)
    assert [o.nodeid for o in offenders] == ["tests/public/test_a.py::bad"]
    assert offenders[0].area == "sdk"
    assert offenders[0].reason == "meh"
