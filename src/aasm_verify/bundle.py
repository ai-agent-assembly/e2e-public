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

import os
import platform
import shutil
import subprocess

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


def _tool_version(executable: str, *args: str) -> str | None:
    """Return the first line of ``executable <args>`` output, or None if absent.

    Stdlib-only probe (mirrors :mod:`aasm_verify.doctor`): missing tools and
    non-zero exits degrade to ``None`` rather than raising, so a bundle builds
    on any host regardless of which toolchains are installed.
    """
    if shutil.which(executable) is None:
        return None
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [executable, *args],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    out = (proc.stdout or proc.stderr).strip()
    return out.splitlines()[0].strip() if out else None


def collect_env(env: dict[str, str] | None = None) -> dict[str, object]:
    """Collect a SANITIZED snapshot of the run environment for ``env.json``.

    Includes only non-sensitive metadata: OS/arch, Python and (when present)
    Rust/Node/Go tool versions, and the allow-listed CI/run env vars
    (:data:`ENV_ALLOW_LIST`). Allow-listed keys are still redacted when the key
    name looks credential-bearing (:func:`_key_is_sensitive`), so no token, key,
    or private endpoint can reach the bundle (AC5).
    """
    source = os.environ if env is None else env

    ci_env: dict[str, str] = {}
    for key in ENV_ALLOW_LIST:
        if key not in source:
            continue
        ci_env[key] = REDACTED if _key_is_sensitive(key) else source[key]

    tools: dict[str, str | None] = {
        "python": platform.python_version(),
        "rustc": _tool_version("rustc", "--version"),
        "cargo": _tool_version("cargo", "--version"),
        "node": _tool_version("node", "--version"),
        "go": _tool_version("go", "version"),
        "protoc": _tool_version("protoc", "--version"),
    }

    return {
        "os": platform.system(),
        "os_release": platform.release(),
        "arch": platform.machine(),
        "tools": tools,
        "ci_env": ci_env,
    }
