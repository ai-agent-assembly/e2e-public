# Production Validation Runbook

This runbook explains how to use `agent-assembly-integration-tests` as the
**production validation harness** for the Agent Assembly public stack. It is the
practical companion to [`verification-modes.md`](verification-modes.md) (which
explains *which ref/mode to target*) and [`evidence-template.md`](evidence-template.md)
(which provides the Jira/release evidence form).

Read this when you need to:

- decide whether a check belongs in **this repo** or in a **product repo**,
- run a specific validation **area** locally or in CI,
- choose between **strict production validation** and a **lightweight dev smoke**,
- interpret **skips / xfails / known product gaps**,
- collect **evidence for a Jira ticket**, or
- work around a **QA-environment blocker** (sandbox port bind, browser launch,
  offline install, Go cache).

---

## 1. What belongs here vs. in the product repos

This repository verifies **cross-repo, production-path behavior that no single
product repo can prove on its own** — runtime × SDK compatibility, public install
paths, example flows, and protocol conformance across the published stack.

It does **not** replace unit or integration tests that live inside each product
repo.

| Concern | Owned by | Lives in |
|---|---|---|
| A function/module behaves correctly | The product repo | `agent-assembly`, `python-sdk`, `node-sdk`, `go-sdk` unit suites |
| One crate's gRPC handler returns the right response | `agent-assembly` | `cargo nextest` in that repo |
| The SDK's wrapper logic denies a blocked action | The SDK repo | that SDK's own test suite |
| **Runtime built from source + a real SDK interoperate** | **this repo** | `tests/live/`, `tests/behavioral/` |
| **A published SDK installs from PyPI/npm/Go proxy and runs** | **this repo** | `tests/public/`, `scripts/install-from-release.sh` |
| **The release artifacts exist for every target platform** | **this repo** | `tests/public/test_release_artifacts.py` (`release` marker) |
| **Example repo flows still work against the current stack** | **this repo** | `tests/examples/`, `tests/public/test_examples.py` |
| **All SDKs agree on the wire-level enforcement-mode vocabulary** | **this repo** | `tests/contract/test_enforcement_mode_parity.py` |

> Rule of thumb: if proving the behavior requires **two or more public repos at
> specific refs** (e.g. "does node-sdk `v0.1.0` work against agent-assembly
> `master`?"), it belongs here. If it can be proven inside one repo's checkout,
> it belongs in that repo.

---

## 2. Validation areas

The orchestrator (`aasm-verify public --area <area>`) and the pytest markers
share the same five area names, plus two opt-in areas:

| Area | Marker / script | What it proves |
|---|---|---|
| `runtime` | `-m runtime` (`tests/public/test_runtime_cli.py`) | The `aasm` runtime CLI binary runs and responds |
| `sdk` | `-m sdk` (`tests/public/`, `tests/contract/`, `tests/behavioral/`) | Each SDK initializes and the SDKs agree on the enforcement contract |
| `examples` | `-m examples` (`tests/public/test_examples.py`) | Example repo flows run against the stack |
| `install` | `tests/install/smoke-test-rust-build.sh` (no pytest marker) | The core Rust monorepo clones and `cargo check`s |
| `conformance` | `-m conformance` (`tests/public/test_policy_conformance.py`) | Policy allow/deny conformance against fixtures |
| `release` | `-m release` (`tests/public/test_release_artifacts.py`, `test_package_install.py`) | Published registry packages + GitHub Release artifacts install/exist |
| `live` | `-m live` (`tests/live/`, with-core `tests/behavioral/`) | A from-source `aa-runtime`/`aa-gateway` interoperates with a real SDK |

Note the asymmetry, taken from `src/aasm_verify/runners.py`:

- `install` is the **only** area with no pytest marker — `aasm-verify public
  --area install` shells out directly to the Rust build smoke script.
- In **`release` mode** *every* selected area runs the `release` marker (driven
  by `AASM_RELEASE_VERSION`), not its own marker.
- `live` is **excluded by default** — `pyproject.toml` sets
  `addopts = "-m 'not live'"`. You must opt in with `-m live`.

---

