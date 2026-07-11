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

import ast
import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Static marker enumeration + rc-quarantine audit (AAASM-4479)
# ---------------------------------------------------------------------------
#
# The functions above audit a *pytest run* (a json-report of what actually
# skipped). The functions below audit the *source tree statically* — they parse
# every ``tests/`` file with :mod:`ast` and enumerate every skip/xfail/rc_pending
# marker, whether or not a run exercised it. This is the forcing function behind
# the AAASM-4479 verification policy: a report-diagnosed defect converted to an
# xfail/skip must carry an open tracking ticket, and a `rc_pending`-quarantined
# assertion must stay visible until its blocking ticket is fixed. Enumerating
# statically (not from a run) means a marker on a test that never *ran* — because
# its env guard skipped it first — is still surfaced.

# Skip/xfail marker kinds recognized under ``@pytest.mark.<kind>``. ``rc_pending``
# is this repo's quarantine marker (AAASM-4479): an assertion that is CORRECT but
# blocked on an rc-pending upstream fix — listed here, not failed. It is the
# single source of truth the sibling CI-realness tickets (AAASM-4476/4477/4478)
# attach their rc-deferred assertions to.
_DECORATOR_KINDS: frozenset[str] = frozenset({"skip", "skipif", "xfail", "rc_pending"})

# Jira status names that mean a tracking ticket is closed. An interim marker
# pinned to such a ticket is stale — the underlying fix landed and the marker
# should have been removed but wasn't.
_DONE_STATUSES: frozenset[str] = frozenset(
    {"done", "closed", "resolved", "cancelled", "canceled", "won't do", "won't fix"}
)

# Opt-in Jira status cross-check. All three must be present; otherwise the audit
# runs fully offline (deterministic, no network) and reports markers + refs +
# no-ref flags only — so it is testable and CI-runnable without Jira creds.
JIRA_URL_ENV: str = "AASM_VERIFY_JIRA_URL"
JIRA_EMAIL_ENV: str = "AASM_VERIFY_JIRA_EMAIL"
JIRA_TOKEN_ENV: str = "AASM_VERIFY_JIRA_TOKEN"

# A resolver maps a ticket key to its current Jira status name (or ``None`` when
# it can't be determined). Injectable so the audit is testable offline.
JiraResolver = Callable[[str], "str | None"]


@dataclass(frozen=True)
class Marker:
    """One statically-discovered skip/xfail/rc_pending marker in the test tree."""

    path: str
    lineno: int
    kind: str  # skip | skipif | xfail | rc_pending | skip_call | xfail_call
    reason: str
    ticket: str | None
    strict: bool | None = None

    @property
    def is_rc_pending(self) -> bool:
        return self.kind == "rc_pending"

    @property
    def justified(self) -> bool:
        """A marker is justified when it names a tracked ticket OR (for a runtime
        skip) an environment requirement. Everything else is a policy violation:
        a masked assertion with no forcing function to ever revisit it."""
        return self.ticket is not None or is_justified(self.reason)

    def as_dict(self) -> dict:
        return {
            "path": self.path,
            "lineno": self.lineno,
            "kind": self.kind,
            "reason": self.reason,
            "ticket": self.ticket,
            "strict": self.strict,
        }


def extract_ticket(text: str) -> str | None:
    """Return the first ``AAASM-NNN`` ticket key in *text*, or None."""
    match = _JIRA_RE.search(text or "")
    return match.group(0) if match else None


def _dotted_name(node: ast.AST) -> str | None:
    """Return the dotted attribute path of a call target (``pytest.mark.skip``)."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _literal_str(node: ast.AST | None) -> str:
    """Best-effort reconstruction of a string literal (plain, f-string, or +).

    f-string interpolations contribute their literal parts only — enough to
    recover an env-requirement phrase or an ``AAASM-NNN`` ref without evaluating
    anything.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(_literal_str(v) for v in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _literal_str(node.left) + _literal_str(node.right)
    return ""


def _call_reason(call: ast.Call, positional: bool) -> str:
    """Extract the ``reason=`` kwarg (or first positional, when *positional*)."""
    for kw in call.keywords:
        if kw.arg == "reason":
            return _literal_str(kw.value)
    if positional and call.args:
        return _literal_str(call.args[0])
    return ""


def _call_strict(call: ast.Call) -> bool | None:
    """Extract a constant ``strict=`` kwarg from an xfail marker call."""
    for kw in call.keywords:
        if kw.arg == "strict" and isinstance(kw.value, ast.Constant):
            return bool(kw.value.value)
    return None


def _ticket_near(lines: list[str], start: int, end: int) -> str | None:
    """Scan the marker's own source lines plus the line above (a leading
    ``# AAASM-NNN`` comment) for a ticket ref the ``reason=`` didn't carry."""
    lo = max(0, start - 2)
    hi = min(len(lines), end)
    for line in lines[lo:hi]:
        found = extract_ticket(line)
        if found:
            return found
    return None


def _marker_from_decorator(dec: ast.expr, path: str, lines: list[str]) -> Marker | None:
    """Build a :class:`Marker` from a ``@pytest.mark.<kind>`` decorator, if it is one."""
    call = dec if isinstance(dec, ast.Call) else None
    func = dec.func if isinstance(dec, ast.Call) else dec
    dotted = _dotted_name(func)
    if dotted is None:
        return None
    parts = dotted.split(".")
    if len(parts) < 3 or parts[0] != "pytest" or parts[-2] != "mark":
        return None
    kind = parts[-1]
    if kind not in _DECORATOR_KINDS:
        return None
    positional = kind in ("skip", "rc_pending")
    reason = _call_reason(call, positional) if call is not None else ""
    strict = _call_strict(call) if call is not None and kind == "xfail" else None
    end = getattr(dec, "end_lineno", dec.lineno) or dec.lineno
    ticket = extract_ticket(reason) or _ticket_near(lines, dec.lineno, end)
    return Marker(
        path=path, lineno=dec.lineno, kind=kind, reason=reason, ticket=ticket, strict=strict
    )


def _marker_from_call(call: ast.Call, path: str, lines: list[str]) -> Marker | None:
    """Build a :class:`Marker` from an inline ``pytest.skip(...)``/``pytest.xfail(...)``."""
    dotted = _dotted_name(call.func)
    if dotted not in ("pytest.skip", "pytest.xfail"):
        return None
    kind = "skip_call" if dotted.endswith("skip") else "xfail_call"
    reason = _call_reason(call, positional=True)
    end = getattr(call, "end_lineno", call.lineno) or call.lineno
    ticket = extract_ticket(reason) or _ticket_near(lines, call.lineno, end)
    return Marker(path=path, lineno=call.lineno, kind=kind, reason=reason, ticket=ticket)


def collect_markers_from_source(source: str, path: str) -> list[Marker]:
    """Enumerate every skip/xfail/rc_pending marker in one file's *source*.

    Marker decorators are read from every function/class ``decorator_list``;
    inline ``pytest.skip``/``pytest.xfail`` calls are read from the call graph.
    Results are sorted by line for deterministic output.
    """
    tree = ast.parse(source)
    lines = source.splitlines()
    out: list[Marker] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            for dec in node.decorator_list:
                marker = _marker_from_decorator(dec, path, lines)
                if marker is not None:
                    out.append(marker)
        elif isinstance(node, ast.Call):
            marker = _marker_from_call(node, path, lines)
            if marker is not None:
                out.append(marker)
    out.sort(key=lambda m: (m.path, m.lineno))
    return out


def collect_markers(tests_dir: str | Path, root: str | Path | None = None) -> list[Marker]:
    """Walk *tests_dir* for ``*.py`` files and enumerate all markers.

    *root* is the base for the reported relative paths (defaults to *tests_dir*).
    Files that fail to read or parse are skipped rather than aborting the audit.
    """
    tests_path = Path(tests_dir)
    root_path = Path(root) if root is not None else tests_path
    out: list[Marker] = []
    for py in sorted(tests_path.rglob("*.py")):
        try:
            source = py.read_text(encoding="utf-8")
        except OSError:
            continue
        try:
            rel = str(py.relative_to(root_path))
        except ValueError:
            rel = str(py)
        try:
            out.extend(collect_markers_from_source(source, rel))
        except SyntaxError:
            continue
    out.sort(key=lambda m: (m.path, m.lineno))
    return out


def stale_tickets(tickets: object, resolver: JiraResolver) -> frozenset[str]:
    """Return the subset of *tickets* whose Jira status is Done/Closed/etc."""
    found: set[str] = set()
    for ticket in sorted(set(tickets)):  # type: ignore[arg-type]
        status = resolver(ticket)
        if status and status.strip().lower() in _DONE_STATUSES:
            found.add(ticket)
    return frozenset(found)


@dataclass
class MarkerAudit:
    """The result of a static marker sweep, with the AAASM-4479 classifications."""

    markers: list[Marker]
    stale: frozenset[str] = field(default_factory=frozenset)
    jira_checked: bool = False

    @property
    def unreferenced(self) -> list[Marker]:
        """Markers with neither a tracking ticket nor an env-requirement reason —
        the policy violations (a masked assertion no one is forced to revisit)."""
        return [m for m in self.markers if not m.justified]

    @property
    def rc_quarantine(self) -> list[Marker]:
        """Every ``rc_pending``-marked assertion — the rc-quarantine registry."""
        return [m for m in self.markers if m.is_rc_pending]

    @property
    def ticketed(self) -> list[Marker]:
        return [m for m in self.markers if m.ticket]

    @property
    def stale_markers(self) -> list[Marker]:
        """Markers whose referenced ticket is already closed (stale — remove them)."""
        return [m for m in self.markers if m.ticket in self.stale]

    def as_dict(self) -> dict:
        return {
            "markers": [m.as_dict() for m in self.markers],
            "unreferenced": [m.as_dict() for m in self.unreferenced],
            "rc_quarantine": [m.as_dict() for m in self.rc_quarantine],
            "stale": [m.as_dict() for m in self.stale_markers],
            "jira_checked": self.jira_checked,
            "counts": {
                "markers": len(self.markers),
                "unreferenced": len(self.unreferenced),
                "rc_quarantine": len(self.rc_quarantine),
                "stale": len(self.stale_markers),
            },
        }


def audit_markers(
    tests_dir: str | Path,
    root: str | Path | None = None,
    resolver: JiraResolver | None = None,
) -> MarkerAudit:
    """Enumerate markers under *tests_dir* and classify them (AAASM-4479).

    When *resolver* is None the audit is fully offline: markers + refs + no-ref
    flags only, no stale check. Pass a resolver (see :func:`jira_resolver_from_env`)
    to additionally flag markers pinned to already-closed tickets.
    """
    markers = collect_markers(tests_dir, root)
    stale: frozenset[str] = frozenset()
    if resolver is not None:
        stale = stale_tickets({m.ticket for m in markers if m.ticket}, resolver)
    return MarkerAudit(markers=markers, stale=stale, jira_checked=resolver is not None)


def _make_jira_resolver(base_url: str, email: str, token: str) -> JiraResolver:
    """Build a resolver that queries the Jira REST API for an issue's status name."""
    import base64
    import urllib.request

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    base = base_url.rstrip("/")

    def resolve(ticket: str) -> str | None:
        req = urllib.request.Request(  # noqa: S310 — fixed https Jira host from env
            f"{base}/rest/api/3/issue/{ticket}?fields=status",
            headers={"Authorization": f"Basic {auth}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310
                payload = json.loads(resp.read().decode("utf-8"))
            return payload["fields"]["status"]["name"]
        except Exception:  # network/auth/shape errors → unknown status, never fatal
            return None

    return resolve


def jira_resolver_from_env(environ: dict | None = None) -> JiraResolver | None:
    """Return a Jira resolver when all AASM_VERIFY_JIRA_* env vars are set, else None."""
    env = os.environ if environ is None else environ
    url = env.get(JIRA_URL_ENV)
    email = env.get(JIRA_EMAIL_ENV)
    token = env.get(JIRA_TOKEN_ENV)
    if not (url and email and token):
        return None
    return _make_jira_resolver(url, email, token)


def render_marker_audit(audit: MarkerAudit) -> str:
    """Render a human-readable marker-audit report (markdown-flavored text)."""
    out: list[str] = []
    add = out.append
    add("# Marker Audit (AAASM-4479)")
    add("")
    add(f"- markers found:                    {len(audit.markers)}")
    add(f"- unreferenced (policy violations): {len(audit.unreferenced)}")
    add(f"- rc-quarantine (rc_pending):       {len(audit.rc_quarantine)}")
    if audit.jira_checked:
        add(f"- stale (ticket Done/Closed):       {len(audit.stale_markers)}")
    else:
        add("- stale (ticket Done/Closed):       not checked "
            "(offline — set AASM_VERIFY_JIRA_{URL,EMAIL,TOKEN} to enable)")
    add("")

    add("## Unreferenced markers (policy violations)")
    add("A skip/xfail with neither a tracking ticket nor an environment "
        "requirement in its reason. Add an open AAASM-NNN ticket key, or justify "
        "the env guard.")
    if not audit.unreferenced:
        add("- none")
    for m in audit.unreferenced:
        add(f"- {m.path}:{m.lineno} [{m.kind}] {m.reason or '<no reason>'}")
    add("")

    add("## rc-quarantine registry (rc_pending)")
    add("Assertions that are correct but blocked on an rc-pending upstream fix — "
        "visible-but-non-blocking. Single source of truth for AAASM-4476/4477/4478.")
    if not audit.rc_quarantine:
        add("- none")
    for m in audit.rc_quarantine:
        ticket = m.ticket or "<NO TICKET — policy violation>"
        add(f"- {m.path}:{m.lineno} → {ticket}: {m.reason or '<no reason>'}")
    add("")

    add("## Stale markers (ticket already closed)")
    if not audit.jira_checked:
        add("- not checked (offline)")
    elif not audit.stale_markers:
        add("- none")
    else:
        for m in audit.stale_markers:
            add(f"- {m.path}:{m.lineno} [{m.kind}] {m.ticket} is Done/Closed — "
                "remove the marker (the defect it masked is fixed)")
    add("")
    return "\n".join(out)
