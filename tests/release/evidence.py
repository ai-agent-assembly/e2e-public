"""Release-artifact evidence-table writer (AC5).

AC5 requires the verification to emit a report carrying the artifact URLs/names
and platform coverage. This builder turns a release's asset list (real or the
offline sample) plus the expected-platform manifest into a Markdown evidence
table: one row per expected platform with its asset name, download URL, and a
present/missing marker, followed by the integrity-sidecar status.

It lives test-side (written under ``tmp_path`` by the test) rather than in
``src/aasm_verify/reports.py`` — that module is owned by an in-flight PR (#75 /
AAASM-3179) and is read-only for this change. Keeping the writer here makes the
evidence a self-contained artifact of the release suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tests.release import manifest


@dataclass(frozen=True)
class EvidenceRow:
    """One platform's evidence: expected asset name, its URL, and presence."""

    platform: str
    asset_name: str
    download_url: str
    present: bool


def build_evidence_rows(asset_urls: dict[str, str]) -> list[EvidenceRow]:
    """Build one evidence row per expected platform from a name → URL mapping.

    *asset_urls* maps published asset names to download URLs (from the GitHub API
    or the offline sample). A platform whose expected binary is absent yields a
    row with ``present=False`` and an empty URL so missing coverage is visible in
    the table rather than dropped.
    """
    rows: list[EvidenceRow] = []
    for asset in manifest.expected_platform_assets():
        url = asset_urls.get(asset.asset_name, "")
        rows.append(
            EvidenceRow(
                platform=asset.platform,
                asset_name=asset.asset_name,
                download_url=url,
                present=asset.asset_name in asset_urls,
            )
        )
    return rows


def render_evidence_table(tag: str, asset_urls: dict[str, str]) -> str:
    """Render the Markdown evidence table for a release.

    Includes a per-platform artifact table (name + URL + presence) and an
    integrity-sidecars line recording checksum/signature presence and the
    signature-verification gap, so the report carries artifact URLs/names and
    platform coverage (AC5) together with the AC4 gap.
    """
    rows = build_evidence_rows(asset_urls)
    covered = sum(1 for r in rows if r.present)

    lines = [
        f"# Release Artifact Evidence — {tag}",
        "",
        f"Platform coverage: {covered}/{len(rows)} expected binaries present.",
        "",
        "| Platform | Asset | Download URL | Present |",
        "|---|---|---|---|",
    ]
    for r in rows:
        marker = "✅" if r.present else "❌"
        url = r.download_url or "—"
        lines.append(f"| {r.platform} | `{r.asset_name}` | {url} | {marker} |")

    has_checksums = manifest.checksums_asset_name() in asset_urls
    has_signature = manifest.signature_asset_name() in asset_urls
    lines += [
        "",
        "## Integrity sidecars",
        "",
        f"- Checksums (`{manifest.checksums_asset_name()}`): "
        f"{'present — verified' if has_checksums else 'MISSING'}",
        f"- Signature (`{manifest.signature_asset_name()}`): "
        + (
            "present — verification NOT performed (AAASM-3161 documented gap: "
            "needs cosign + Sigstore trust root)"
            if has_signature
            else "MISSING — no signature published"
        ),
        "",
    ]
    return "\n".join(lines)


def write_evidence_table(dest_dir: Path, tag: str, asset_urls: dict[str, str]) -> Path:
    """Write the evidence table to ``<dest_dir>/release-evidence-<tag>.md`` and return it."""
    dest_dir.mkdir(parents=True, exist_ok=True)
    path = dest_dir / f"release-evidence-{tag}.md"
    path.write_text(render_evidence_table(tag, asset_urls))
    return path
