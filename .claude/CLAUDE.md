# CLAUDE.md — e2e-public

Guidance for Claude Code (and humans) working in this repository. This file holds
**repo-specific** context only; universal engineering policy lives in the global
config. When a fact here duplicates `README.md`, `pyproject.toml`, or a script,
treat those as the source of truth and update them, not just this file.

Org-wide baseline: https://github.com/ai-agent-assembly/.github/blob/main/CLAUDE.md
(org-universal conventions this file doesn't repeat).

## What this repo is

The **public cross-repo integration / e2e test harness** for AI Agent Assembly — a
pure-Python verification suite (`aasm-verify`, Python ≥ 3.12, `uv` + `hatchling`)
that proves **cross-repo behavior no single product repo can prove on its own**:
runtime × SDK compatibility, install paths (branch / tag / SHA / published
registry), example-repo flows, and protocol conformance. It does **not** replace
the unit/integration tests inside each product repo. The repos it verifies
(`agent-assembly`, `python-sdk`, `node-sdk`, `go-sdk`, `examples`)
live elsewhere; this one only orchestrates and asserts against them.

## Layout (see `README.md` for the full tree)

| Path | Role |
|---|---|
| `src/aasm_verify/` | The `aasm-verify` CLI (entrypoint `aasm_verify.cli:main`): runners, ref resolution, sanitized run summaries |
| `scripts/` | Bash entry points: `verify-public-stack.sh`, `install-from-{branch,tag,release}.sh`, `summarize-run.sh`, `report-failure.sh` |
| `tests/{install,sdk,examples,conformance}/` | Public smoke tests by area; default mode |
| `tests/live/` | **Live-core tests** — clone + build + run a real `aa-gateway` from source |
| `fixtures/`, `tests/live/fixtures/policies/` | Sample policy files + expected-output snapshots |
| `.github/workflows/` | Five `verify-*.yml` workflows (schedule + `workflow_dispatch` only) |

## Build, test, lint

```bash
uv sync                                 # install deps + dev group
uv run pytest                           # default suite (live tests excluded — see below)
uv run pytest tests/sdk -v              # one area
uv run pytest tests/live/test_live_gateway.py::test_name -v   # one test
uv run pytest -m live                   # opt in to live-core tests (needs cargo + protoc)
uv run ruff check .
uv run ruff format .
```

- `pyproject.toml` sets `addopts = "-m 'not live'"`, so a plain `pytest` run **skips
  the live-core tests by default**. Run `-m live` (or a `tests/live/...` path) to
  exercise them. Markers: `runtime`, `sdk`, `examples`, `conformance`, `release`,
  `live`.
- The Bash entry point is `bash scripts/verify-public-stack.sh` (default `latest`
  mode, refs default to `master`); modes are `latest` / `tag` / `sha` / `release`.

## The live-core harness (`tests/live/`)

These tests obtain the `agent-assembly` core source at a git ref, build the gateway
with `cargo build -p aa-gateway`, launch it, and assert against it. The flow is
composed by the session-scoped `live_gateway` fixture (`conftest.py`):
`core_source.py` (clone/override) → `build.py` (cargo) → `gateway.py` (`LiveGateway`).

- **`LiveGateway` drives the gateway via CLI flags**, not env vars: it spawns the
  built binary with `--policy <file> --listen 127.0.0.1:<free-port> --audit-dir <dir>`
  on a kernel-assigned **free TCP loopback port**, with an isolated `$HOME` so the
  gateway's SQLite store / audit JSONL / budget cache stay in a temp dir.
- **Env vars that actually drive the harness:**
  - `AASM_CORE_REF` — git ref of `agent-assembly` to clone (default `master`).
  - `AASM_CORE_SOURCE_DIR` — point at an existing core checkout (e.g. the sibling
    monorepo) to **skip the network clone**; the default is to clone for CI repro.
  - `AAASM_GATEWAY_URL` — gateway URL the SDK-client smoke (`sdk_client.py`) targets.
- Build prerequisites are `cargo` **and** `protoc` (the gateway pulls in `aa-proto`,
  whose build script invokes protoc). When either is missing the live tests **skip
  cleanly** rather than fail — so a green `pytest` run does not imply live coverage.

## Repo-specific gotchas

- **Minimal PR-gating CI (AAASM-4476).** The only `pull_request` trigger is
  `verify-release-scheduled.yml`'s `harness-self-tests` job — the offline
  `aasm-verify` harness unit tests (`tests/test_*.py`). Every *product*
  verification workflow (the `verify-*` stack) is still `schedule` +
  `workflow_dispatch` only, so opening a PR does **not** build or install any
  product artifact. **Validate locally** (`ruff` + the relevant `pytest` area,
  and `-m live` when you touch the live harness); do not wait on CI to catch a
  product regression.
- **Canonical remote is `origin`** (→ `ai-agent-assembly/e2e-public`);
  confirm with `git remote -v` / `git branch -r` before scoping — a local checkout
  can be behind. Default branch is **`master`**.
- **Scheduled runs open GitHub Issues on failure** (`report-failure.sh`): one issue
  per failing area (`runtime`/`sdk`/`examples`/`install`/`conformance`), labelled
  `test-failure` + `area: <area>`. Summaries are sanitized — **never** emit log
  dumps, private repo names, secrets, or internal endpoints into a summary or issue.
- **No pre-commit / lefthook config** lives here, so there are no commit-time hooks
  to satisfy. Still **never `--no-verify`, never force-push.**

## Project policy

- **JIRA:** project AAASM; set the native **Components** field to this repo
  (`ai-agent-assembly/e2e-public`); Team (`customfield_10001`)
  = Pioneer. Epic → Story → Subtask (one Subtask ≈ one commit) + a `Verify …`
  subtask per Story.
- **Commits:** `<emoji> (<scope>): <imperative summary>` (gitmoji.dev), one logical
  unit per commit, bisectable. **Branch:** `<release-or-phase>/<ticket>/<type>/<short_summary>`.
  **PR title:** `[<ticket>] <emoji> (<scope>): <summary>`; base branch **always
  `master`**; body follows `.github/PULL_REQUEST_TEMPLATE.md`; ≥1 Pioneer approval.
- **Self-hosted deployment is out of scope** product-wide — don't propose
  Helm/Terraform/air-gapped/migration work even if a spec mentions it.
- **Keep summaries public-safe.** This is a *public* repo: no private repo names
  (`agent-assembly-cloud`, `-enterprise`), secrets, or internal SaaS assumptions.

## Verification policy — a diagnosed defect must stay red until it is *fixed*

This harness exists to *find* cross-repo defects. The moment it finds one, the
path of least resistance is to `xfail`/`skip` the failing assertion to get the
suite green again — and that is exactly the mistake this policy exists to stop.

**The rule.** When a verification report (`verification-reports/` or equivalent)
diagnoses a concrete defect, one of these two things must be true — enforced by
convention, not individual diligence:

1. **A tracking ticket is opened, and it stays open until the *defect* is
   fixed.** It is **never** closed by adjusting the harness to stop reporting the
   defect. Only a real fix in the product repo closes it.
2. **If the assertion is converted to an interim marker**, that marker must
   (a) reference the open tracking ticket by key in its `reason=`/adjacent
   comment, and (b) use `xfail(strict=True)` where the assertion is expected to
   raise, so that the day the defect is fixed the marker **xpasses loudly** and
   forces its own removal. A bare `skip`/`xfail(strict=False)` with no ticket is
   a policy violation.

**The quarantine mechanism (`rc_pending`).** For an assertion that is *correct*
but blocked on an rc-pending upstream fix, use the `rc_pending` marker
(`@pytest.mark.rc_pending(reason="AAASM-NNN: …")`, or the
`aasm_verify.rc_pending.rc_pending(ticket, reason)` helper). `tests/conftest.py`
turns it into a non-strict xfail so it is **visible-but-non-blocking**, and the
audit lists it in a dedicated "rc-quarantine registry". This is the single
source of truth the sibling CI-realness tickets (AAASM-4476/4477/4478) attach
their rc-deferred assertions to.

**The forcing function (`aasm-verify markers`).** Run
`uv run aasm-verify markers` to statically enumerate every `skip`/`skipif`/
`xfail`/`rc_pending` marker under `tests/`, extract the adjacent `AAASM-NNN`
ref, and flag (a) markers with **no ticket ref** (policy violation) and
(b) markers whose ticket is already **Done/Closed** (stale — the fix landed, the
marker should have been removed). It is **offline by default** (deterministic,
no Jira creds); pass `--check-jira` with `AASM_VERIFY_JIRA_{URL,EMAIL,TOKEN}` set
to enable the stale-ticket cross-check. It is a *reporting* forcing function, not
a blocking CI gate — treat its output as the standing list of what the suite is
currently masking.

**Justifying an environment-conditional skip — the `classification:` taxonomy.**
Not every skip masks a defect: a build artifact, checkout, or release that is
simply absent in *this* environment is a legitimate prerequisite gate, not a
policy violation. The audit accepts two justifications for a marker — a tracking
ticket (`AAASM-NNN`, for a masked defect) **or** an environment requirement in
the `reason=`. For the latter, prefer the repo's documented classification
taxonomy so the *why* is machine-checkable and consistent across the suite:

- `classification: known_prerequisite` — a build artifact / SDK checkout /
  published release / toolchain that isn't present here (e.g. `dist/` not built,
  a package not yet on PyPI). Justified; **not** a defect.
- `classification: external_flake` — a transient network/registry error
  (proxy unreachable, GitHub API hiccup). Justified; **not** a defect.
- `classification: release_blocker` — a real defect. This tag does **not**
  justify a skip on its own; it must carry a tracking ticket (or be a hard
  `pytest.fail`, not a skip). The audit deliberately keeps flagging a bare
  `release_blocker` skip.

Because the audit reads reasons statically (via `ast`, never a live run), the
classifying phrase must survive as a **string literal** at the marker site: an
f-string's literal parts count, but an interpolated value (`str(exc)`) does not —
so tag the literal, e.g. `pytest.skip(f"{exc} (classification: known_prerequisite)")`.
A `reason=` factored into a **module-level string constant**
(`reason=DENY_XFAIL_REASON`) is resolved to that constant's literal, so a shared
reason constant carrying a ticket key or env phrase stays classifiable without
duplicating it at every marker.

**Case study — why this rule exists.** In June 2026,
`verification-reports/AAASM-2985-sdk-transport-investigation.md` correctly
diagnosed that the SDK's gRPC registration transport had no matching endpoint in
the documented local-gateway deployment (naming `aa-api` as "a library-only
crate with no binary"). AAASM-2985 was then marked **Done** and its follow-on
AAASM-2989/3000 re-pointed the harness at a different transport path behind an
`xfail`/`skip` — closing the *finding* without fixing the *defect*. Six months
later the org re-discovered the identical production-impacting gap from scratch,
at higher cost, as **AAASM-4447/4449**. A real bug was found once, masked by a
marker, and lost. The marker audit above is the check that makes that
disappearance impossible to do silently again.

## Documentation conventions — document the WHY, not the WHAT

Comments and docstrings exist to capture intent that the code cannot: rationale,
constraints, invariants, and non-obvious decisions. Restating what the code already
says is noise that rots out of sync — avoid it.

- **Module docstrings:** yes — the module's role in the harness, what it composes,
  and where it sits (e.g. "builds + runs a real `aa-gateway` from source").
- **Public functions / fixtures:** yes — the contract: behavior, what it returns,
  side effects, and the surprising bits (e.g. "session-scoped so the clone + cargo
  build happen once", "skips cleanly when `cargo`/`protoc` are absent", "isolated
  `$HOME` keeps the gateway's SQLite store out of `~/.aa`").
- **Inline `#` why-comments:** for workarounds, the inherent free-port race, env-var
  overrides, and anything security- or sanitization-sensitive (why a summary is
  scrubbed, not just that it is).
- **Skip:** trivial private helpers, getters, type-restating, and anything a reader
  infers from the signature.
- **Big decisions → docs**, not scattered docstrings. `docs/verification-modes.md`
  and `docs/evidence-template.md` already exist — reference them, don't duplicate.

> Net: a new contributor (human or LLM) should read a module's docstring and a
> public function's docstring and understand *why it is the way it is* without
> reverse-engineering it. If a comment only says *what*, delete it.
