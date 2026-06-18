"""Skip-reason auditing and area classification for verification reports.

This module is the production-grade-reporting half of AAASM-3155. It answers
two questions about a pytest-json-report run that the existing pass/fail
rollup in :mod:`aasm_verify.reports` cannot:

* **Which area does a test belong to?** — every test is classified into one of
  :data:`aasm_verify.runners.AREAS` (``runtime``/``sdk``/``examples``/
  ``install``/``conformance``) so the report can carry per-area counts.
* **Is a skip justified?** — an integration suite legitimately skips when a
  build artifact, binary, or release version is absent, but an *un-justified*
  skip silently erodes coverage. A skip is justified only when its reason
  carries an **environment requirement** or a **linked Jira issue**. In strict
  mode (``AASM_VERIFY_STRICT=1``) an un-justified skip fails the run.

Everything here is stdlib-only and operates on the normalized
``pytest-json-report`` test records (``nodeid``/``outcome``/``keywords``/
``call``/``setup``), never on raw log text — so no secrets are echoed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The strict-mode environment toggle. This name is a CONTRACT shared with
# AAASM-3160, whose CI profiles export it — keep it exactly.
STRICT_ENV_VAR: str = "AASM_VERIFY_STRICT"

# pytest marker -> verification area. ``release`` is not an area of its own;
# release-mode tests are classified by their file name (see _NODEID_AREAS).
_MARKER_AREAS: dict[str, str] = {
    "runtime": "runtime",
    "sdk": "sdk",
    "examples": "examples",
    "conformance": "conformance",
}

# Fallback: classify by test-file stem when no area marker is present. Ordered
# substrings are matched against the file stem of the nodeid.
_NODEID_AREAS: tuple[tuple[str, str], ...] = (
    ("runtime", "runtime"),
    ("policy_conformance", "conformance"),
    ("conformance", "conformance"),
    ("examples", "examples"),
    ("python_sdk", "sdk"),
    ("node_sdk", "sdk"),
    ("go_sdk", "sdk"),
    ("homebrew_install", "install"),
    ("package_install", "install"),
    ("release_artifacts", "install"),
    ("install", "install"),
    ("sdk", "sdk"),
)

# A skip reason is justified when it references a Jira issue ...
_JIRA_RE = re.compile(r"\bAAASM-\d+\b")
# ... or names an environment requirement (a binary/package/repo/env var that
# must be present). These are the phrasings the conftest skip helpers emit:
# "X not found in PATH", "package X not installed", "requires Y", "clone Z
# alongside this repo", "set ENV_VAR", "ENV_VAR=value".
_ENV_REQ_RE = re.compile(
    r"not found"
    r"|not installed"
    r"|not available"
    r"|requires?\b"
    r"|\bclone\b"
    r"|\binstall\b"
    r"|set [A-Z][A-Z0-9_]+"
    r"|\b[A-Z][A-Z0-9_]{2,}=\S+"  # matches an uppercase env-var assignment
    r"|\bAASM_[A-Z0-9_]+\b"
    r"|environment",
    re.IGNORECASE,
)

# pytest prefixes captured skip messages with "Skipped: ".
_SKIPPED_PREFIX = "Skipped: "

# The outcome values pytest-json-report emits.
OUTCOMES: tuple[str, ...] = (
    "passed",
    "failed",
    "error",
    "skipped",
    "xfailed",
    "xpassed",
)


def nodeid_stem(nodeid: str) -> str:
    """Return the test-file stem of a pytest nodeid (no path, no ``.py``)."""
    head = nodeid.split("::", 1)[0]
    stem = head.rsplit("/", 1)[-1]
    if stem.endswith(".py"):
        stem = stem[:-3]
    return stem


def area_for_test(test: dict) -> str:
    """Classify a pytest-json-report test record into a verification area.

    Prefers an explicit area marker in ``keywords``; falls back to the file
    stem of the nodeid. Returns ``"other"`` when nothing matches.
    """
    keywords = test.get("keywords") or []
    for kw in keywords:
        area = _MARKER_AREAS.get(kw)
        if area is not None:
            return area
    stem = nodeid_stem(test.get("nodeid", ""))
    for needle, area in _NODEID_AREAS:
        if needle in stem:
            return area
    return "other"


def _phase_longrepr(test: dict, phase: str) -> str:
    """Return the ``longrepr`` text for a test phase (setup/call), if any."""
    section = test.get(phase)
    if not isinstance(section, dict):
        return ""
    longrepr = section.get("longrepr")
    if isinstance(longrepr, (list, tuple)) and len(longrepr) >= 3:
        # pytest serializes skips as (file, lineno, "Skipped: <reason>").
        return str(longrepr[2])
    if isinstance(longrepr, str):
        return longrepr
    return ""


def extract_skip_reason(test: dict) -> str:
    """Extract the human-readable skip reason from a skipped test record.

    Returns an empty string when no reason text is available.
    """
    for phase in ("call", "setup"):
        text = _phase_longrepr(test, phase)
        if text:
            if text.startswith(_SKIPPED_PREFIX):
                text = text[len(_SKIPPED_PREFIX) :]
            return text.strip()
    return ""


def is_justified(reason: str) -> bool:
    """Return True when a skip reason carries an env requirement or Jira ref.

    An empty/whitespace-only reason is never justified.
    """
    if not reason or not reason.strip():
        return False
    return bool(_JIRA_RE.search(reason) or _ENV_REQ_RE.search(reason))


@dataclass(frozen=True)
class UnjustifiedSkip:
    """One skipped test whose reason names no env requirement or Jira ref."""

    nodeid: str
    area: str
    reason: str

    def as_dict(self) -> dict:
        return {"nodeid": self.nodeid, "area": self.area, "reason": self.reason}


def find_unjustified_skips(data: dict) -> list[UnjustifiedSkip]:
    """Return every skipped test in *data* whose skip reason is not justified.

    *data* is a parsed ``pytest-json-report`` mapping. Tests are scanned in
    file order so output is deterministic.
    """
    result: list[UnjustifiedSkip] = []
    for test in data.get("tests", []):
        if test.get("outcome") != "skipped":
            continue
        reason = extract_skip_reason(test)
        if is_justified(reason):
            continue
        result.append(
            UnjustifiedSkip(
                nodeid=test.get("nodeid", ""),
                area=area_for_test(test),
                reason=reason,
            )
        )
    return result
