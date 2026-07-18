#!/usr/bin/env python3
"""Regenerate sentinel-bounded blocks in the harness install/verify scripts.

The single source of truth is ``metadata/harness.yaml`` at the repository
root. This generator reads that file and rewrites each ``# BEGIN GENERATED:
<id>`` / ``# END GENERATED: <id>`` block in the affected shell scripts so
they cannot drift out of lockstep.

Ticket: AAASM-4337 (Wave-3 shared-metadata).

Design notes
------------
* Python stdlib only — the harness has ``dependencies = []`` in
  ``pyproject.toml`` and this drift check must run in a plain
  ``actions/setup-python`` step without extra installs.
* YAML parsing is intentionally hand-rolled: the SoT schema is fixed and
  shallow (top-level keys, one level of string-valued children), so a
  full YAML dependency would be overkill.
* Idempotent: running the generator twice must produce no diff. CI
  enforces this with ``git diff --exit-code``.

Usage
-----
    python scripts/generate_harness_metadata.py         # rewrite in place
    python scripts/generate_harness_metadata.py --check # exit 1 on drift
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent.parent
METADATA_PATH = REPO_ROOT / "metadata" / "harness.yaml"

SENTINEL_RE = re.compile(
    r"^(?P<indent>[ \t]*)# BEGIN GENERATED: (?P<id>[a-z0-9\-]+)[ \t]*\n"
    r"(?P<body>.*?)"
    r"^(?P=indent)# END GENERATED: (?P=id)[ \t]*$",
    re.MULTILINE | re.DOTALL,
)


# ---------------------------------------------------------------------------
# Minimal YAML loader (top-level keys with string-valued children).
# ---------------------------------------------------------------------------

def _strip_comment(line: str) -> str:
    """Drop a trailing ``#`` comment that is not inside quotes."""
    in_quote: str | None = None
    for i, ch in enumerate(line):
        if in_quote:
            if ch == in_quote:
                in_quote = None
        elif ch in ('"', "'"):
            in_quote = ch
        elif ch == "#":
            return line[:i].rstrip()
    return line.rstrip()


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def load_metadata(path: Path) -> dict[str, dict[str, str]]:
    """Parse the fixed-schema SoT: ``top_key: { child_key: "string", ... }``."""
    data: dict[str, dict[str, str]] = {}
    current: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = _strip_comment(raw_line)
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            # Top-level ``key:`` — no scalar values expected at this level.
            key, _, remainder = line.partition(":")
            if remainder.strip():
                raise ValueError(
                    f"{path}: top-level key '{key}' must have nested children, "
                    f"not a scalar value"
                )
            current = key.strip()
            data[current] = {}
        else:
            if current is None:
                raise ValueError(f"{path}: indented line before any top-level key")
            stripped = line.lstrip()
            child_key, sep, value = stripped.partition(":")
            if not sep:
                raise ValueError(f"{path}: expected 'key: value', got: {line!r}")
            data[current][child_key.strip()] = _unquote(value)
    return data


# ---------------------------------------------------------------------------
# Block renderers — one per sentinel id.
# ---------------------------------------------------------------------------

def _bash_dq(value: str) -> str:
    """Quote a value for bash double-quoted string context (no expansion needed)."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def render_install_defaults_github_org(meta: dict[str, dict[str, str]]) -> str:
    org = meta["github"]["org"]
    return f"ORG={_bash_dq(org)}\n"


def render_install_defaults_package_ids(meta: dict[str, dict[str, str]]) -> str:
    pkgs = meta["packages"]
    return (
        f"PYTHON_PACKAGE_NAME={_bash_dq(pkgs['python_pypi'])}\n"
        f"NODE_PACKAGE_NAME={_bash_dq(pkgs['node_npm'])}\n"
        f"GO_MODULE_PATH={_bash_dq(pkgs['go_module'])}\n"
    )


def render_harness_verify_command(meta: dict[str, dict[str, str]]) -> str:
    cli = meta["verify_cli"]
    return (
        f"VERIFY_BIN={_bash_dq(cli['binary'])}\n"
        f"VERIFY_SUBCOMMAND={_bash_dq(cli['subcommand'])}\n"
    )


RENDERERS: dict[str, Callable[[dict[str, dict[str, str]]], str]] = {
    "install-defaults-github-org": render_install_defaults_github_org,
    "install-defaults-package-ids": render_install_defaults_package_ids,
    "harness-verify-command": render_harness_verify_command,
}


# Files the generator is allowed to rewrite. Any BEGIN GENERATED sentinel
# discovered outside this allow-list is an error — we do not touch
# verification-reports/ or fixtures/ history.
TARGET_SCRIPTS = (
    "scripts/install-from-branch.sh",
    "scripts/install-from-tag.sh",
    "scripts/install-from-release.sh",
    "scripts/resolve-refs.sh",
    "scripts/verify-public-stack.sh",
)


# ---------------------------------------------------------------------------
# Rewrite engine.
# ---------------------------------------------------------------------------

def rewrite_file(path: Path, meta: dict[str, dict[str, str]]) -> bool:
    """Rewrite sentinel blocks in ``path``. Return True if content changed."""
    original = path.read_text(encoding="utf-8")

    def _replace(match: re.Match[str]) -> str:
        block_id = match.group("id")
        indent = match.group("indent")
        renderer = RENDERERS.get(block_id)
        if renderer is None:
            raise ValueError(
                f"{path}: unknown sentinel id '{block_id}' — "
                f"add a renderer in generate_harness_metadata.py"
            )
        body = renderer(meta)
        # Re-indent each non-empty line to match the sentinel indent so the
        # generator plays nicely with (hypothetical) indented blocks.
        if indent:
            body = "".join(
                (indent + line if line.strip() else line)
                for line in body.splitlines(keepends=True)
            )
        return (
            f"{indent}# BEGIN GENERATED: {block_id}\n"
            f"{body}"
            f"{indent}# END GENERATED: {block_id}"
        )

    updated = SENTINEL_RE.sub(_replace, original)
    if updated != original:
        path.write_text(updated, encoding="utf-8")
        return True
    return False


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if any target file would change (CI drift gate).",
    )
    args = parser.parse_args(argv)

    meta = load_metadata(METADATA_PATH)
    changed: list[str] = []
    for rel in TARGET_SCRIPTS:
        path = REPO_ROOT / rel
        if not path.exists():
            print(f"warning: {rel} not found; skipping", file=sys.stderr)
            continue
        if rewrite_file(path, meta):
            changed.append(rel)

    if args.check and changed:
        print("Harness metadata drift detected in:", file=sys.stderr)
        for rel in changed:
            print(f"  {rel}", file=sys.stderr)
        print(
            "Run `python scripts/generate_harness_metadata.py` and commit the diff.",
            file=sys.stderr,
        )
        return 1

    for rel in changed:
        print(f"regenerated: {rel}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
