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

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from aasm_verify import reports
from aasm_verify.reports import Summary

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


# Image suffixes copied into ``screenshots/`` when browser tests produced them.
_SCREENSHOT_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".webp"})


@dataclass
class EvidenceBundle:
    """One production-validation run, assembled into a QA-review folder.

    Construct from a :class:`aasm_verify.reports.Summary` plus the run's
    reproduction inputs (commands, CI links, the raw pytest JSON, optional
    screenshots) and call :meth:`write` to materialize the folder. The same
    object serves local and CI runs (AC1) — the caller supplies whatever context
    it has; everything is optional except the summary.
    """

    summary: Summary
    commands: list[str] = field(default_factory=list)
    ci_links: list[str] = field(default_factory=list)
    pytest_json_path: Path | None = None
    screenshot_dirs: list[Path] = field(default_factory=list)
    env: dict[str, str] | None = None

    def jira_summary(self) -> str:
        """Return the Jira-ready evidence text (AC3), reusing the report writer."""
        return reports.render_jira_report(self.summary)

    def _copy_pytest_json(self, dest_dir: Path) -> bool:
        """Copy the raw pytest JSON into the bundle; tolerate a missing source."""
        src = self.pytest_json_path
        if src is None or not src.is_file():
            return False
        shutil.copyfile(src, dest_dir / "pytest-report.json")
        return True

    def _copy_screenshots(self, dest_dir: Path) -> list[str]:
        """Best-effort copy of any browser-test screenshots (AC4).

        Returns the relative paths copied. Missing source dirs and the
        no-browser-tests case both yield an empty list — absence is tolerated,
        never an error.
        """
        copied: list[str] = []
        shots_dir = dest_dir / "screenshots"
        for src_dir in self.screenshot_dirs:
            if not src_dir.is_dir():
                continue
            for path in sorted(src_dir.rglob("*")):
                if path.is_file() and path.suffix.lower() in _SCREENSHOT_SUFFIXES:
                    shots_dir.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(path, shots_dir / path.name)
                    copied.append(f"screenshots/{path.name}")
        return copied

    def write(self, outdir: str | Path) -> Path:
        """Materialize the bundle under *outdir* and return its path.

        Writes ``summary.md``, ``report.json``, ``env.json``, ``commands.txt``,
        ``ci-links.txt``, ``jira-summary.txt``, the raw ``pytest-report.json``
        (when available), and ``screenshots/`` (when present). The folder is
        created if missing. Every file is built from normalized data or the
        sanitized env snapshot, so the bundle carries no secrets (AC5).
        """
        out = Path(outdir)
        out.mkdir(parents=True, exist_ok=True)

        reports.write_report_md(str(out / "summary.md"), self.summary)
        reports.write_summary_json(str(out / "report.json"), self.summary)

        env_snapshot = collect_env(self.env)
        (out / "env.json").write_text(
            json.dumps(env_snapshot, indent=2, sort_keys=False) + "\n",
            encoding="utf-8",
        )

        (out / "commands.txt").write_text(
            "".join(f"{line}\n" for line in self.commands), encoding="utf-8"
        )
        (out / "ci-links.txt").write_text(
            "".join(f"{link}\n" for link in self.ci_links), encoding="utf-8"
        )
        (out / "jira-summary.txt").write_text(self.jira_summary(), encoding="utf-8")

        self._copy_pytest_json(out)
        self._copy_screenshots(out)
        return out
