"""The ``rc_pending`` quarantine marker (AAASM-4479).

`rc_pending` means: *this assertion is CORRECT, but the fix it asserts is blocked
on an rc-pending upstream change — keep it visible, do not fail the suite on it.*
It is the shared quarantine mechanism the sibling CI-realness tickets
(AAASM-4476/4477/4478) attach their rc-deferred assertions to, so a
report-diagnosed defect stays on a standing list instead of silently vanishing
behind a bare skip (the exact failure mode AAASM-2985/2989/3000 exhibited — see
the "Verification policy" section of ``.claude/CLAUDE.md``).

Two moving parts back this marker, both intentionally minimal:

* The marker is *registered* in ``pyproject.toml`` (``[tool.pytest.ini_options]
  markers``) so ``@pytest.mark.rc_pending`` is a first-class, warning-free marker.
* A ``pytest_collection_modifyitems`` hook (``tests/conftest.py``) turns every
  ``rc_pending`` item into a non-strict xfail at collection time, so a currently
  rc-blocked assertion does not fail the run — but an xpass (the fix landed)
  surfaces loudly as a prompt to remove the marker.

The static marker audit (``aasm-verify markers``) enumerates every
``rc_pending`` decorator into a dedicated "rc-quarantine registry" section, which
is why authors should always reach for :func:`rc_pending` (or a literal
``@pytest.mark.rc_pending``) rather than an anonymous ``@pytest.mark.xfail``.
"""

from __future__ import annotations

import re

import pytest

MARKER_NAME: str = "rc_pending"

_TICKET_RE = re.compile(r"AAASM-\d+")


def rc_pending(ticket: str, reason: str) -> pytest.MarkDecorator:
    """Return an ``@pytest.mark.rc_pending`` marker for an rc-blocked assertion.

    *ticket* is the blocking Jira key (``AAASM-NNN``) and is **required** — the
    whole point of the quarantine mechanism is that every deferred assertion is
    traceable to an open ticket. The key is folded into the marker ``reason`` so
    both the collection hook and the static audit can recover it.

    Raises :class:`ValueError` if *ticket* is not a well-formed ``AAASM-NNN`` key.
    """
    if not _TICKET_RE.fullmatch(ticket):
        raise ValueError(
            f"rc_pending requires a blocking Jira ticket key like 'AAASM-1234', got {ticket!r}"
        )
    return pytest.mark.rc_pending(reason=f"{ticket}: {reason}")
