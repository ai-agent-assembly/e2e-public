"""Route/page manifest for the dashboard, derived from the design spec.

The manifest is the offline, toolchain-free backbone of the dashboard smoke
suite: it enumerates the routes the production dashboard is expected to serve
so the build/serve/browser checks have a stable target list even when no
``pnpm`` toolchain is present.

Source of truth
---------------
The 12 canonical routes mirror ``agent-assembly/design/v1/hi-fi/shell.jsx``
(the ``ROUTES`` const in the hi-fi prototype), which the dashboard itself
re-encodes in ``dashboard/src/routes.ts`` (``CANONICAL_ROUTES``). We pin a
*copy* here rather than parse the sibling repo so the manifest stays valid
offline and when the dashboard checkout is absent — a parse of the live
``routes.ts`` is a deeper coupling than a production smoke check needs. The
referenced design pages are listed in :data:`DESIGN_PAGES` so a reviewer can
trace each route back to its mockup.

The expected built static assets (:data:`EXPECTED_BUILD_ASSETS`) encode the
Vite production-output contract used by the AC2 static/serve check.
"""

from __future__ import annotations

from dataclasses import dataclass

# Section headers the nav groups routes under (design/v1/hi-fi/shell.jsx).
ROUTE_GROUPS: tuple[str, ...] = ("monitor", "control", "manage")


@dataclass(frozen=True)
class DashboardRoute:
    """One navigable dashboard route, mirrored from the hi-fi ``ROUTES`` const.

    ``design_page`` names the ``design/v1/hi-fi/*.jsx`` mockup the route is
    translated from, so the manifest carries a traceable link from each route
    to the design spec it implements (dev-rule 6).
    """

    id: str
    num: str
    label: str
    group: str
    path: str
    design_page: str


# The 12 canonical routes. Mirrors design/v1/hi-fi/shell.jsx ROUTES and the
# dashboard's src/routes.ts CANONICAL_ROUTES — keep id/num/path in lockstep.
DASHBOARD_ROUTES: tuple[DashboardRoute, ...] = (
    DashboardRoute("overview", "01", "Overview", "monitor", "/overview", "overview.jsx"),
    DashboardRoute("fleet", "02", "Fleet", "monitor", "/agents", "fleet.jsx"),
    DashboardRoute("topology", "03", "Topology", "monitor", "/topology", "topology.jsx"),
    DashboardRoute("live", "04", "Live Ops", "monitor", "/live", "live-ops.jsx"),
    DashboardRoute("alerts", "05", "Alerts", "monitor", "/alerts", "alerts.jsx"),
    DashboardRoute("audit", "06", "Audit Log", "monitor", "/audit/violations", "audit-log.jsx"),
    DashboardRoute("capability", "07", "Capability", "control", "/capability", "capability.jsx"),
    DashboardRoute("policy", "08", "Policy", "control", "/policies", "policy-editor.jsx"),
    DashboardRoute("scrub", "09", "Secret Scrubbing", "control", "/scrub", "scrub.jsx"),
    DashboardRoute("costs", "10", "Cost & Budget", "manage", "/costs", "costs.jsx"),
    DashboardRoute("teams", "11", "Agent Groups", "manage", "/teams", "teams.jsx"),
    DashboardRoute("identity", "12", "Members & Access", "manage", "/identity", "identity.jsx"),
)

# Distinct design-spec pages referenced by the manifest (dev-rule 6 evidence).
DESIGN_PAGES: tuple[str, ...] = tuple(route.design_page for route in DASHBOARD_ROUTES)

# Vite production-output contract. After a successful ``pnpm build`` the
# dashboard's ``dist/`` must contain at least the HTML entry point and a hashed
# asset bundle directory — this is what the AC2 static/serve check asserts.
EXPECTED_BUILD_ASSETS: tuple[str, ...] = (
    "index.html",
    "assets",
)


@dataclass(frozen=True)
class ManifestProblem:
    """One schema violation found in the route manifest."""

    route_id: str
    problem: str


# Sentinel route_id for manifest-level problems that belong to no single route.
_MANIFEST_SCOPE = "<manifest>"


def validate_route(route: DashboardRoute) -> list[ManifestProblem]:
    """Return schema problems for a single route (empty list when well-formed).

    A route is well-formed when every field is non-empty, the path is rooted at
    ``/``, the two-digit ``num`` is numeric, the ``group`` is a known section,
    and the ``design_page`` names a ``.jsx`` mockup.
    """
    problems: list[ManifestProblem] = []
    rid = route.id or "<unnamed>"
    if not route.id:
        problems.append(ManifestProblem(rid, "id is empty"))
    if not route.label:
        problems.append(ManifestProblem(rid, "label is empty"))
    if not route.num.isdigit() or len(route.num) != 2:
        problems.append(ManifestProblem(rid, f"num {route.num!r} is not two digits"))
    if route.group not in ROUTE_GROUPS:
        problems.append(ManifestProblem(rid, f"group {route.group!r} is not a known section"))
    if not route.path.startswith("/"):
        problems.append(ManifestProblem(rid, f"path {route.path!r} is not rooted at '/'"))
    if not route.design_page.endswith(".jsx"):
        problems.append(
            ManifestProblem(rid, f"design_page {route.design_page!r} is not a .jsx mockup")
        )
    return problems


def validate_manifest() -> list[ManifestProblem]:
    """Return every schema problem across the whole route manifest.

    Also enforces manifest-level invariants: route ids and paths are unique and
    the ``num`` prefixes form a contiguous ``01..NN`` sequence (the design
    spec's numbered nav).
    """
    problems: list[ManifestProblem] = []
    for route in DASHBOARD_ROUTES:
        problems.extend(validate_route(route))

    ids = [r.id for r in DASHBOARD_ROUTES]
    if len(set(ids)) != len(ids):
        problems.append(ManifestProblem(_MANIFEST_SCOPE, "duplicate route id(s) present"))

    paths = [r.path for r in DASHBOARD_ROUTES]
    if len(set(paths)) != len(paths):
        problems.append(ManifestProblem(_MANIFEST_SCOPE, "duplicate route path(s) present"))

    expected_nums = [f"{i:02d}" for i in range(1, len(DASHBOARD_ROUTES) + 1)]
    if [r.num for r in DASHBOARD_ROUTES] != expected_nums:
        problems.append(
            ManifestProblem(_MANIFEST_SCOPE, "num prefixes are not a contiguous 01..NN sequence")
        )
    return problems
