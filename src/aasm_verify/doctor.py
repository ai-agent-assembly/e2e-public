"""Environment preflight checks for production validation runs (AAASM-3159).

Before the public verification suite touches the network or builds anything,
``aasm-verify doctor`` answers a single question per machine: *can this host run
each validation area at all?* It probes the local environment — required tools,
network reachability, localhost bind permission, cache writability, and browser
availability — and reports **pass / warn / fail by area** so a CI summary (or a
human) can decide what to skip before a single test starts.

Design notes:

* **Offline-safe.** Every probe runs without a working network. Network
  reachability *degrades* to ``warn`` when offline rather than failing — being
  offline is information, not an error.
* **Stdlib-only.** Tool detection uses :func:`shutil.which` plus a short version
  subprocess; the bind probe is a real :func:`socket.socket` bind on
  ``127.0.0.1:0``; cache writability writes a temp file under each cache dir;
  browser detection looks for a Playwright/Chromium install without launching.
* **Capability → area mapping.** Each probe is a *capability*; a capability maps
  to the verification area(s) it gates (see :data:`runners.AREAS`). An area's
  status is the worst status of the capabilities it depends on.
* **Machine-readable.** ``--json`` emits the full structure for a CI summary.

This module is a standalone CLI command. Wiring it into ``conftest.py`` and the
CI workflows is intentionally deferred to AAASM-3160 to avoid shared-file churn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

# Verification areas mirror aasm_verify.runners.AREAS. Kept as a local literal so
# the doctor command stays importable without constructing a runner, and so the
# area-status report is stable even if runner ordering changes.
AREAS: tuple[str, ...] = ("runtime", "sdk", "examples", "install", "conformance")


class Status(str, Enum):
    """Tri-state outcome for a capability check or an aggregated area.

    String-valued so it serializes directly into ``--json`` output.

    * ``PASS`` — the capability is fully available.
    * ``WARN`` — degraded but not fatal (e.g. network unreachable, missing tool
      that only gates an optional area).
    * ``FAIL`` — the capability is required and unavailable; the gated area
      cannot run on this machine.
    """

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


# Severity ordering for aggregation: an area is as bad as its worst capability.
_SEVERITY: dict[Status, int] = {Status.PASS: 0, Status.WARN: 1, Status.FAIL: 2}


def worst(statuses: list[Status]) -> Status:
    """Return the most severe status in ``statuses`` (``PASS`` if empty)."""
    if not statuses:
        return Status.PASS
    return max(statuses, key=lambda s: _SEVERITY[s])


@dataclass
class CheckResult:
    """The outcome of one capability probe.

    Attributes:
        name: Stable capability identifier (e.g. ``"tool:cargo"``, ``"bind"``).
        status: Tri-state :class:`Status`.
        detail: Human-readable explanation (version string, error message).
        areas: Verification areas this capability gates.
        recommend_env: Recommended environment variables to remediate, e.g.
            ``{"GOCACHE": "/tmp/aasm-gocache"}``. Empty when no action helps.
    """

    name: str
    status: Status
    detail: str = ""
    areas: tuple[str, ...] = ()
    recommend_env: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "detail": self.detail,
            "areas": list(self.areas),
            "recommend_env": dict(self.recommend_env),
        }


def area_statuses(checks: list[CheckResult]) -> dict[str, Status]:
    """Aggregate capability checks into a per-area status map.

    Each area's status is the worst status among the checks that gate it. Areas
    with no gating check default to ``PASS``.
    """
    by_area: dict[str, list[Status]] = {area: [] for area in AREAS}
    for check in checks:
        for area in check.areas:
            if area in by_area:
                by_area[area].append(check.status)
    return {area: worst(statuses) for area, statuses in by_area.items()}
