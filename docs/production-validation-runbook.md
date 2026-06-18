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

## 3. Local prerequisites

Install only what the area you are running needs. Every area **skips cleanly**
(not fails) when its toolchain is absent — see [§6](#6-interpreting-skips-xfails-and-known-gaps).

| Tool | Needed for | Install |
|---|---|---|
| **Python ≥ 3.12 + [uv](https://docs.astral.sh/uv/)** | The harness itself (`aasm-verify`, pytest) | `pip install uv` |
| **Rust (stable) + Cargo** | `install`, `live`, `release` (GitHub-Release binary) | <https://rustup.rs> |
| **protoc** (protobuf-compiler) | Any build of `agent-assembly` (aa-proto's build script invokes `protoc`) — `install`, `live` | `apt-get install -y protobuf-compiler` / `brew install protobuf` |
| **Node ≥ 20 + [pnpm](https://pnpm.io/)** | `sdk` (node), `examples` (node flows) | `corepack enable pnpm` or `npm i -g pnpm` |
| **Go (stable)** | `sdk` (go), `examples` (go flows), `release` (Go module proxy) | <https://go.dev/dl/> |
| **Browser / Playwright** | Not required by any area in this repo today. Only relevant if an `examples` flow ever drives a web UI; see the [browser blocker note](#52-browser--playwright-launch-denied). | n/a |

CI pins (see the workflows): Python `3.14`, Node `24`, Go `stable`, Rust
`stable`, pnpm `latest`, and `protobuf-compiler` via apt.

Bootstrap the harness once:

```bash
uv sync   # installs pytest, pytest-json-report, pytest-xdist, ruff
```

---

## 4. How to run each area

There are two equivalent entry points: the **`aasm-verify` orchestrator** (what
CI uses) and **direct pytest / smoke scripts** (handy for one area in isolation).

### 4.1 Orchestrated (recommended — matches CI)

```bash
# All areas, latest base branches (the scheduled-CI behavior)
uv run aasm-verify public --mode latest --area all

# One area
uv run aasm-verify public --mode latest --area runtime
uv run aasm-verify public --mode latest --area sdk
uv run aasm-verify public --mode latest --area examples
uv run aasm-verify public --mode latest --area install
uv run aasm-verify public --mode latest --area conformance

# Pin specific refs across repos (mirrors verify-public-manual.yml inputs)
uv run aasm-verify public \
  --mode latest --area sdk \
  --agent-assembly-ref master \
  --python-sdk-ref v0.1.0 \
  --node-sdk-ref   master \
  --go-sdk-ref     master \
  --examples-ref   master

# Plan only — print the resolved target matrix and exit (no clone/build)
uv run aasm-verify public --mode latest --area all --dry-run
```

### 4.2 Direct pytest / scripts (one area, no orchestrator)

```bash
uv run pytest -m runtime     -v          # runtime CLI
uv run pytest -m sdk         -v          # SDK init + cross-SDK contract + behavioral
uv run pytest -m examples    -v          # example flows
uv run pytest -m conformance -v          # policy allow/deny conformance
bash tests/install/smoke-test-rust-build.sh   # install area (no marker)
```

`install`, `sdk`, and `examples` smoke scripts honor ref env vars:

```bash
AA_REF=v0.1.0          bash tests/install/smoke-test-rust-build.sh
PYTHON_SDK_REF=v0.1.0  bash tests/sdk/smoke-test-python-sdk.sh
NODE_SDK_REF=master    bash tests/sdk/smoke-test-node-sdk.sh
EXAMPLES_REF=master    bash tests/examples/smoke-test-examples.sh
AA_REF=master          bash tests/conformance/smoke-test-conformance.sh
```

### 4.3 `release` area — published registry install paths

`release` validates what real end users can install. It installs from PyPI/npm/Go
proxy, then runs the `release` marker:

```bash
# Install published SDKs, then run the release suite (mirrors verify-release.yml)
bash scripts/install-from-release.sh --repo python-sdk --version 0.1.0
bash scripts/install-from-release.sh --repo node-sdk   --version 0.1.0
bash scripts/install-from-release.sh --repo go-sdk     --version v0.1.0

AASM_RELEASE_VERSION=0.0.1 uv run pytest -m release -v --tb=short
```

`test_release_artifacts.py` additionally checks the **GitHub Release** has a
platform binary asset for the current platform (the asset suffix is derived from
`platform.system()`/`platform.machine()` in `tests/public/conftest.py`).

### 4.4 `live` area — from-source core interop (opt-in)

`live` builds `aa-runtime` / `aa-gateway` from the `agent-assembly` source and
runs a real SDK against it. It is **excluded by default** and slow (clone +
`cargo build`), so opt in explicitly:

```bash
# Needs cargo + protoc on PATH (REQUIRED_TOOLS in tests/live/build.py); else skips.
uv run pytest -m live -v

# Pin / reuse the core source:
AASM_CORE_REF=master            uv run pytest -m live -v    # git ref to clone
AASM_CORE_SOURCE_DIR=/path/aa   uv run pytest -m live -v    # reuse an existing checkout
```

### 4.5 CI workflow → area mapping

| Workflow | Trigger | Areas / mode |
|---|---|---|
| `verify-latest.yml` | Wed+Sat 02:00 UTC + dispatch | install, sdk, examples, conformance @ base branches (direct smoke scripts) |
| `verify-public-scheduled.yml` | 1st/15th 02:00 UTC + dispatch | `runtime,sdk,examples,install,conformance` matrix via `aasm-verify`, opens failure issues |
| `verify-public-manual.yml` | dispatch | choose `mode` + `test_group` + per-repo refs |
| `verify-tag.yml` | dispatch | per-repo tag inputs, exact-snapshot smoke scripts |
| `verify-release.yml` | release published + dispatch | `release` marker against registry versions |

---

## 5. Strict production validation vs. lightweight dev smoke

The same areas serve two postures. The difference is **how much you install** and
**whether skips are acceptable**.

### Lightweight development smoke (fast inner loop)

Goal: "did I obviously break the harness / one path?" Skips are fine.

```bash
uv run aasm-verify public --mode latest --area all --dry-run   # plan only
uv run pytest -m conformance -v                                # pure-fixture, no network
uv run aasm-verify public --mode latest --area sdk             # skips SDKs you lack
```

- Run only the area(s) you touched.
- Toolchain gaps that cause **skips** are acceptable here.
- No evidence collection required.

### Strict production validation (release gate / QA sign-off)

Goal: "can a real user install and run the published stack, and does the
from-source core interoperate?" **Skips of a relevant area are NOT acceptable** —
a skip means the check did not actually run.

1. Install the **full toolchain** from [§3](#3-local-prerequisites): Rust+Cargo,
   `protoc`, Python/uv, Node/pnpm, Go.
2. Run every area, plus `release` and `live`, with no relevant skips:
   ```bash
   uv run aasm-verify public --mode latest --area all     # runtime/sdk/examples/install/conformance
   uv run pytest -m live -v                                # from-source core interop
   # for a published release:
   AASM_RELEASE_VERSION=<ver> uv run pytest -m release -v --tb=short
   ```
3. For a release cut, run in **`tag`** or **`release`** mode against the exact
   versions (see `verification-modes.md`), not `latest`.
4. Capture a JSON report and produce evidence — see [§7](#7-collecting-evidence-for-jira).
5. Verify the report shows **0 unexpected skips** for areas in scope. If a
   relevant area skipped, fix the environment and re-run before signing off.

---

## 6. Interpreting skips, xfails, and known gaps

The harness distinguishes "the environment couldn't run this" (skip) from "we
expect this to fail until the product is fixed" (xfail).

| Outcome | Meaning | What to do |
|---|---|---|
| **PASS** | The path works. | Nothing. |
| **SKIP** | A prerequisite is absent — binary not on PATH, SDK package not installed, toolchain incomplete (`skip_if_binary_missing`, `skip_if_package_missing` in `tests/public/conftest.py`; `missing_build_tools()` in `tests/live/build.py`). | **Dev smoke:** acceptable. **Strict validation:** install the missing tool and re-run; a skip is *not* a pass. |
| **XFAIL** | A **known product gap** is pinned here so drift is caught. E.g. the cross-SDK init/runtime-mode divergence (`tests/contract/test_enforcement_mode_parity.py`) and live with-core SDK paths (`tests/behavioral/*_with_core.py`). | Expected — do not "fix" the test. Track the gap via its linked Jira ticket. |
| **XPASS** | A test marked xfail unexpectedly **passed** — a product gap may have been closed. | Investigate; the xfail marker (and its Jira reference) likely needs to be removed. |
| **FAIL** | A real regression in the cross-repo path. | Triage: is it a product bug, or an environment blocker ([§8](#8-troubleshooting-qa-environment-blockers))? Only file a product bug if it reproduces in a clean supported environment. |

Where skips/xfails come from:

- **Binary/package missing** → `tests/public/conftest.py` (`skip_if_binary_missing`,
  `skip_if_package_missing`).
- **Build toolchain missing** (`cargo`, `protoc`) → `tests/live/build.py`
  `REQUIRED_TOOLS` / `missing_build_tools()`; the install smoke script also
  `exit 0`s (skip, not fail) when `cargo`/`protoc` are absent.
- **Known cross-SDK gaps** → `@pytest.mark.xfail` in the contract/behavioral
  suites, each citing its Jira ticket in the docstring.

> Classification rule (from Epic [AAASM-3144](https://lightning-dust-mite.atlassian.net/browse/AAASM-3144)):
> a failure is a **validation-environment defect**, not a product bug, unless it
> reproduces in a clean supported developer/CI environment.

---

