"""AC5: the evidence table records artifact URLs/names and platform coverage.

Runs fully offline against the sample release data. Asserts the written table
(under ``tmp_path``) names every expected platform asset, carries its download
URL, reports platform coverage, and records the integrity-sidecar status
including the AC4 signature-verification gap. Also drives the missing-asset path
so a coverage hole shows in the table rather than being silently dropped.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.release import evidence, manifest


def _urls(sample_release_data: dict) -> dict[str, str]:
    return {a["name"]: a["browser_download_url"] for a in sample_release_data["assets"]}


@pytest.mark.release
def test_evidence_table_written_to_tmp_path(tmp_path: Path, sample_release_data: dict) -> None:
    """The writer produces a Markdown file under tmp_path for the release tag."""
    tag = sample_release_data["tag_name"]
    path = evidence.write_evidence_table(tmp_path, tag, _urls(sample_release_data))
    assert path.is_file()
    assert path.parent == tmp_path
    assert tag in path.name


@pytest.mark.release
def test_evidence_table_lists_every_platform_asset(
    tmp_path: Path, sample_release_data: dict
) -> None:
    """Every expected platform's asset name and URL appears in the table (AC5)."""
    tag = sample_release_data["tag_name"]
    urls = _urls(sample_release_data)
    text = evidence.write_evidence_table(tmp_path, tag, urls).read_text()
    for asset in manifest.expected_platform_assets():
        assert asset.platform in text, f"platform {asset.platform!r} missing from evidence"
        assert asset.asset_name in text, f"asset {asset.asset_name!r} missing from evidence"
        assert urls[asset.asset_name] in text, (
            f"download URL for {asset.asset_name!r} missing from evidence"
        )


@pytest.mark.release
def test_evidence_table_reports_full_platform_coverage(
    tmp_path: Path, sample_release_data: dict
) -> None:
    """The table reports coverage as N/N when all expected binaries are present."""
    tag = sample_release_data["tag_name"]
    text = evidence.write_evidence_table(tmp_path, tag, _urls(sample_release_data)).read_text()
    total = len(manifest.expected_platform_assets())
    assert f"{total}/{total} expected binaries present" in text


@pytest.mark.release
def test_evidence_table_records_signature_gap(tmp_path: Path, sample_release_data: dict) -> None:
    """The table records the AC4 signature-verification gap, not a silent pass."""
    tag = sample_release_data["tag_name"]
    text = evidence.write_evidence_table(tmp_path, tag, _urls(sample_release_data)).read_text()
    assert "verification NOT performed" in text
    assert "AAASM-3161" in text


@pytest.mark.release
def test_evidence_table_flags_missing_platform(tmp_path: Path, sample_release_data: dict) -> None:
    """A missing platform binary is shown as not-present, lowering coverage (AC5)."""
    tag = sample_release_data["tag_name"]
    urls = _urls(sample_release_data)
    dropped = manifest.expected_platform_assets()[0].asset_name
    urls.pop(dropped)

    rows = evidence.build_evidence_rows(urls)
    dropped_row = next(r for r in rows if r.asset_name == dropped)
    assert dropped_row.present is False
    assert dropped_row.download_url == ""

    total = len(manifest.expected_platform_assets())
    text = evidence.render_evidence_table(tag, urls)
    assert f"{total - 1}/{total} expected binaries present" in text
