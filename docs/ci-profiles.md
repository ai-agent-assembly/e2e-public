# CI Validation Profiles

`agent-assembly-integration-tests` exposes its verification as five named **profiles**
that trade speed against depth. A profile bundles a real `aasm-verify` (or `pytest`)
invocation with a `doctor` preflight and per-profile report artifacts, so CI clearly
separates fast smoke from deeper production validation.

The profiles are implemented once in the reusable workflow
[`verify-profiles.yml`](../.github/workflows/verify-profiles.yml) (`workflow_call`) and
selected through the [`verify.yml`](../.github/workflows/verify.yml) dispatcher.

> The existing `verify-latest.yml`, `verify-public-manual.yml`,
> `verify-public-scheduled.yml`, `verify-tag.yml`, and `verify-release.yml` workflows
> are unchanged and keep their own schedule / release / tag triggers. The profile
> dispatcher is **additive** — a single, documented, selectable front door.

## Profiles

| Profile | Speed | What it does | Real command |
|---|---|---|---|
| `smoke` | fast | runtime + SDK import/init + basic conformance at latest source refs | `aasm-verify public --mode latest --area {runtime,sdk,conformance}` |
| `full` | medium | install + examples + conformance + reporting, all areas (strict) | `aasm-verify public --mode latest --area all` + `aasm-verify report` |
| `live` | slow | builds + starts `aa-gateway`/`aa-runtime` from source, drives the SDK against it | `pytest -m live` |
| `release` | medium | verifies published registry packages + GitHub release artifacts for a version (strict) | `install-from-release.sh` + `pytest -m release` |
| `dashboard` | medium | examples area with a real browser for dashboard screenshot smoke | `aasm-verify public --area examples` (Playwright Chromium) |

Each profile:

- runs **`aasm-verify doctor --json`** as an early step so the host's per-area
  capability (tools, localhost bind, network, caches, browser) is visible in the log
  *before* any build or network work (AAASM-3159);
- uploads its reports (`doctor.json`, the pytest JSON, and — for `full` — the rendered
  `report.md`/`summary.json`) as a per-profile artifact named
  `verify-<profile>-reports`.

### Strict profiles

`full` and `release` export **`AASM_VERIFY_STRICT=1`** (the contract from AAASM-3155):
in strict mode a tolerated skip (a missing artifact, an unavailable dependency) is
treated as a failure rather than passing silently. `smoke`, `live`, and `dashboard`
run non-strict so missing optional capabilities skip cleanly.

### Clean-skip behaviour

Profiles that need a host capability the runner may lack do **not** hard-fail when it
is missing:

- **`live`** needs `cargo` + `protoc`. The `-m live` suite skips cleanly when the
  toolchain is absent; `doctor` reports the `runtime`/`install`/`conformance` areas as
  `FAIL`/`WARN` so the reason is explicit.
- **`dashboard`** needs a browser. Playwright Chromium install is best-effort; when a
  browser cannot be provisioned the `doctor` `browser` capability `WARN`s and the
  screenshot tests skip rather than fail.

These supply the supported network / port / browser validation lanes that address Epic
AAASM-3144.

## Selecting a profile

### On demand (`workflow_dispatch`)

Run the **Verify** workflow and pick:

- **profile** — `smoke` | `full` | `live` | `release` | `dashboard`
- **area** — area selector for `smoke`/`full` (`all`, `runtime`, `sdk`, `examples`,
  `install`, `conformance`); ignored by `live`/`release`/`dashboard`
- **ref inputs** — `agent_assembly_ref`, `python_sdk_ref`, `node_sdk_ref`,
  `go_sdk_ref`, `examples_ref` (branch / tag / SHA, default `master`)
- **release_version** — required by the `release` profile (e.g. `0.0.1`)

### Scheduled

`verify.yml` schedules **only** the fast `smoke` profile (weekly, Mondays 03:00 UTC).
The expensive profiles stay opt-in: run them via `workflow_dispatch` or their dedicated
`verify-*.yml` workflows. This keeps unattended cost low while still catching cross-repo
drift early.

## Local equivalents

You can run the same checks locally:

```bash
# preflight — what can this machine run?
uv run aasm-verify doctor

# smoke
uv run aasm-verify public --mode latest --area runtime
uv run aasm-verify public --mode latest --area sdk
uv run aasm-verify public --mode latest --area conformance

# full (strict)
AASM_VERIFY_STRICT=1 uv run aasm-verify public --mode latest --area all

# live (needs cargo + protoc)
uv run pytest -m live

# release (needs a published version)
uv run pytest -m release   # with AASM_RELEASE_VERSION set

# dashboard (needs Playwright Chromium)
uv run aasm-verify public --mode latest --area examples
```
