"""Integration test for the public-conftest skip-reason audit hook.

Drives a throwaway pytest session (via the ``pytester`` fixture) that loads
the real ``tests/public/conftest.py`` and asserts the hook warns on an
un-justified skip but stays silent on env- and Jira-justified skips.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest_plugins = ["pytester"]

_CONFTEST = Path(__file__).parent / "public" / "conftest.py"


@pytest.fixture
def public_conftest(pytester: pytest.Pytester) -> None:
    pytester.makeconftest(_CONFTEST.read_text())


def test_hook_warns_on_unjustified_skip(pytester: pytest.Pytester, public_conftest) -> None:
    pytester.makepyfile(
        """
        import pytest

        def test_bare_skip():
            pytest.skip("just because")
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(skipped=1)
    out = result.stdout.str()
    assert "UnjustifiedSkipWarning" in out
    assert "un-justified skip" in out


def test_hook_silent_on_justified_skips(pytester: pytest.Pytester, public_conftest) -> None:
    pytester.makepyfile(
        """
        import pytest

        def test_env_skip():
            pytest.skip("aasm binary not found in PATH")

        def test_jira_skip():
            pytest.skip("blocked by AAASM-3000")
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(skipped=2)
    assert "UnjustifiedSkipWarning" not in result.stdout.str()


def test_hook_does_not_change_pass_fail(pytester: pytest.Pytester, public_conftest) -> None:
    pytester.makepyfile(
        """
        import pytest

        def test_ok():
            assert True

        def test_skip():
            pytest.skip("anything at all")
        """
    )
    result = pytester.runpytest("-p", "no:cacheprovider")
    result.assert_outcomes(passed=1, skipped=1)
