"""Offline route-manifest checks for the dashboard smoke suite (AAASM-3154).

These always run — no toolchain, no dashboard checkout, no network. They prove
the route/page manifest derived from ``agent-assembly/design/v1/hi-fi/`` is
parseable and schema-valid, and that the static-asset expectation list is
well-formed, so the build/serve/browser checks downstream have a stable,
validated target list to work against.
"""

from __future__ import annotations

import pytest

from tests.dashboard.manifest import (
    DASHBOARD_ROUTES,
    DESIGN_PAGES,
    EXPECTED_BUILD_ASSETS,
    ROUTE_GROUPS,
    DashboardRoute,
    validate_manifest,
    validate_route,
)


def test_manifest_is_non_empty() -> None:
    """The route manifest enumerates the canonical dashboard routes."""
    assert len(DASHBOARD_ROUTES) == 12


def test_manifest_schema_is_valid() -> None:
    """The whole manifest is schema-valid (ids/paths unique, nums contiguous)."""
    problems = validate_manifest()
    assert not problems, "manifest schema violations:\n" + "\n".join(
        f"  {p.route_id}: {p.problem}" for p in problems
    )


@pytest.mark.parametrize("route", DASHBOARD_ROUTES, ids=lambda r: r.id)
def test_each_route_is_well_formed(route: DashboardRoute) -> None:
    """Each individual route passes per-entry schema validation."""
    problems = validate_route(route)
    assert not problems, f"{route.id}: " + "; ".join(p.problem for p in problems)


@pytest.mark.parametrize("route", DASHBOARD_ROUTES, ids=lambda r: r.id)
def test_each_route_references_a_design_page(route: DashboardRoute) -> None:
    """Every route traces back to a design-spec ``.jsx`` mockup (dev-rule 6)."""
    assert route.design_page.endswith(".jsx")
    assert route.group in ROUTE_GROUPS


def test_route_groups_are_covered() -> None:
    """Every declared nav section has at least one route under it."""
    used_groups = {route.group for route in DASHBOARD_ROUTES}
    assert used_groups == set(ROUTE_GROUPS)


def test_design_pages_are_traceable() -> None:
    """The design-page list mirrors the routes one-to-one (no orphan refs)."""
    assert len(DESIGN_PAGES) == len(DASHBOARD_ROUTES)
    assert all(page.endswith(".jsx") for page in DESIGN_PAGES)


def test_expected_build_assets_are_well_formed() -> None:
    """The Vite production-output expectation list is non-empty + relative."""
    assert EXPECTED_BUILD_ASSETS
    assert "index.html" in EXPECTED_BUILD_ASSETS
    assert all(not asset.startswith("/") for asset in EXPECTED_BUILD_ASSETS)


def test_validate_route_flags_a_malformed_route() -> None:
    """A malformed route is rejected (proves the validator is not vacuous)."""
    bad = DashboardRoute(
        id="", num="1", label="", group="nope", path="overview", design_page="overview.txt"
    )
    problems = validate_route(bad)
    assert problems, "validator must reject a malformed route"
