"""Repo-wide pytest hooks.

Currently home to the ``rc_pending`` quarantine mechanism (AAASM-4479): an
``@pytest.mark.rc_pending`` assertion is correct but blocked on an rc-pending
upstream fix, so it must be *visible but non-blocking*. This hook translates the
marker into a non-strict xfail at collection time — a still-broken assertion
xfails (green, listed) and a since-fixed one xpasses (a loud prompt to remove
the marker). See ``src/aasm_verify/rc_pending.py`` for the full rationale.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """Quarantine every ``rc_pending`` item as a non-strict xfail (AAASM-4479)."""
    for item in items:
        marker = item.get_closest_marker("rc_pending")
        if marker is None:
            continue
        reason = marker.kwargs.get("reason")
        if reason is None and marker.args:
            reason = str(marker.args[0])
        item.add_marker(pytest.mark.xfail(reason=reason or "rc_pending", strict=False, run=True))
