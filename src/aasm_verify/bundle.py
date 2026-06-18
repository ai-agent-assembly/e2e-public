"""Evidence-bundle assembler for QA signoff (AAASM-3162).

A production-validation run proves cross-repo behavior; QA then needs a single,
self-contained artifact to review and to attach to a Jira ticket. This module
turns one run into a reusable **evidence bundle** — a folder (optionally zipped)
that gathers, in one place:

* ``summary.md`` — the curated public-integration ``report.md`` (from
  :mod:`aasm_verify.reports`), the human entry point.
* ``report.json`` — the normalized ``summary.json`` for machine consumption.
* ``pytest-report.json`` — the raw pytest-json-report the summary was built from.
* ``env.json`` — **sanitized** run environment: OS, language/tool versions and
  git refs only. Tokens, keys, and private endpoints are never copied in.
* ``commands.txt`` — the command transcript that reproduces the run.
* ``ci-links.txt`` — the workflow-run / issue links for the run.
* ``jira-summary.txt`` — Jira-ready text QA can paste straight into a ticket.
* ``screenshots/`` — best-effort copy of any browser-test screenshots; absent
  when no browser tests ran.

The bundle is identical for local and CI runs (AC1): the only difference is
what the caller passes in (``--run-url``, CI env). Everything written here is
built from normalized data and an **allow-listed** env snapshot, so — like the
report generators — no secrets or internal endpoints are echoed (AC5).
"""

from __future__ import annotations

# Environment keys copied verbatim into ``env.json``. The list is an ALLOW-LIST,
# not a deny-list: anything not named here is dropped, so a newly-introduced
# secret env var can never leak into a bundle by default (AC5).
ENV_ALLOW_LIST: tuple[str, ...] = (
    "RUNNER_OS",
    "RUNNER_ARCH",
    "GITHUB_REF",
    "GITHUB_SHA",
    "GITHUB_RUN_ID",
    "GITHUB_WORKFLOW",
    "GITHUB_REPOSITORY",
    "AASM_CORE_REF",
    "AREA",
    "AASM_VERIFY_STRICT",
)

# Substrings whose presence in an env *key* marks the value as sensitive. Even
# inside the allow-list, a matching key is redacted — defense in depth so a
# rename or accidental allow-list edit cannot leak a credential (AC5).
_SECRET_KEY_HINTS: tuple[str, ...] = (
    "TOKEN",
    "SECRET",
    "KEY",
    "PASSWORD",
    "PASSWD",
    "CREDENTIAL",
    "AUTH",
    "PRIVATE",
    "SESSION",
    "COOKIE",
)

REDACTED: str = "[redacted]"


def _key_is_sensitive(key: str) -> bool:
    """Return True when an env key name looks like it holds a credential."""
    upper = key.upper()
    return any(hint in upper for hint in _SECRET_KEY_HINTS)
