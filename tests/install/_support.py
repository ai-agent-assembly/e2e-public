"""Test-local helpers for the install-path matrix suite.

Two concerns live here, both deliberately kept out of ``src/aasm_verify`` so
they touch only this suite:

* :func:`isolated_install_dir` — a fresh, empty working directory under the
  test's ``tmp_path`` so an install case never mutates global state (the home
  directory, a shared ``/tmp`` clone, or the repo checkout).
* :func:`write_install_evidence` — records the resolved version/ref an install
  reported into a JSON file under ``tmp_path`` (AAASM-3151 AC4). This is a
  *test-local* artifact writer; it intentionally does **not** route through
  ``aasm_verify.reports`` (owned by other in-flight work) — the evidence is a
  side file the test emits and asserts on directly.

The evidence is public-safe: it records the case id, mode, target, the
resolved ref/version string, and the verify argv — never raw log dumps, env
contents, or secrets.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


def isolated_install_dir(tmp_path: Path, case_id: str) -> Path:
    """Return a fresh empty directory under *tmp_path* for one install case.

    Named by *case_id* so a parametrized run keeps each case's working tree
    separate and inspectable. Created fresh (the parent ``tmp_path`` is already
    unique per test), so an install never sees state from another case.
    """
    work = tmp_path / "install" / case_id
    work.mkdir(parents=True, exist_ok=True)
    return work


@dataclass(frozen=True)
class InstallEvidence:
    """The resolved-version/ref evidence one install case reports (AC4)."""

    case_id: str
    target: str
    mode: str
    expected_ref_kind: str
    expected_ref: str
    # The version/ref string the verify command actually reported.
    resolved: str
    verify_argv: list[str]


def write_install_evidence(
    tmp_path: Path,
    *,
    case_id: str,
    target: str,
    mode: str,
    expected_ref_kind: str,
    expected_ref: str,
    resolved: str,
    verify_argv: tuple[str, ...],
) -> Path:
    """Write one install case's resolved ref/version to ``tmp_path`` as JSON.

    Returns the evidence file path. The file is the AC4 artifact: a durable,
    test-local record that *this install reported this version/ref*. Stored
    under ``tmp_path/evidence/<case_id>.json`` so a parametrized run produces
    one file per case without collision.
    """
    evidence = InstallEvidence(
        case_id=case_id,
        target=target,
        mode=mode,
        expected_ref_kind=expected_ref_kind,
        expected_ref=expected_ref,
        resolved=resolved,
        verify_argv=list(verify_argv),
    )
    out_dir = tmp_path / "evidence"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{case_id}.json"
    out_file.write_text(json.dumps(asdict(evidence), indent=2, sort_keys=True))
    return out_file


def read_install_evidence(path: Path) -> InstallEvidence:
    """Read back an evidence file written by :func:`write_install_evidence`."""
    data = json.loads(Path(path).read_text())
    return InstallEvidence(**data)
