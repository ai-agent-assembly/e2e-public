# AAASM-3331 — Regression suite for previously-fixed high-risk bugs (base-branch 2026-06)

## Summary

Consolidated regression verification for previously-fixed high-risk defects, run
against base-branch HEAD (not a release tag). **Pass bar met:** every tracked
regression is non-reproducing on current master, the two release-gated xfail items
are explicitly recorded with their tracking tickets, and the version-metadata drift
is resolved on the beta.3 release line.

**Verdict: PASS (5/5 test cases).** Two documented xfails remain (in-harness cosign
verification, and the separate-repo live `_core` deadlock test) — both tracked, neither
is a regression recurrence.

## Per-test-case results

| TC subtask | Tracked defect | Result | Observed | Evidence |
|---|---|---|---|---|
| AAASM-3335 | AAASM-3073 — audit consumer no event loss on restart (`AckPolicy::Explicit`) | **Pass** | `gateway_restart_loses_zero_acked_audit_events` publishes 4,000 events to a file-storage JetStream stream, kills consumer #1 mid-drain, restarts consumer #2 on the same durable, and asserts every event lands exactly once (per-message ack only after Postgres write). No gaps/dupes. | `aa-integration-tests::e2e_gateway_restart_durability gateway_restart_loses_zero_acked_audit_events` PASS [3.325s] in the Linux **Coverage** job (`--all-features`, 3968/3968 passed), master CI run [27835257358 (#1161)](https://github.com/ai-agent-assembly/agent-assembly/actions/runs/27835257358). Companion `aa-gateway::audit_consumer_e2e consumer_drains_all_events_and_dedupes_by_event_id` also PASS. |
| AAASM-3337 | AAASM-3000 — SDK⇄runtime IPC no deadlock on close (heartbeat/ack) | **Pass** (+1 xfail, tracked) | `shutdown_is_clean_when_runtime_never_acks` stands up a mock UDS server that never acks, ships fire-and-forget events, and asserts `shutdown()`/`thread.join()` returns within 5s — the exact no-deadlock-on-close contract. Runs unconditionally (no `#[ignore]`, no env/cfg guard). | `aa-sdk-client::ipc::tests shutdown_is_clean_when_runtime_never_acks` PASS [0.006s] in the Linux **Test** job (`cargo nextest run --workspace`), master CI run [27835257358 (#1161)](https://github.com/ai-agent-assembly/agent-assembly/actions/runs/27835257358). Companion `ipc_loop_with_mock_server` also PASS. |
| AAASM-3338 | AAASM-3021 — SDK pre-execution check wired (deny blocks) | **Pass** (xfail→pass **flipped**) | `runtime_forwards_per_tool_deny_to_gateway` spawns a real aa-gateway (policy: `read_file` allow / `delete_file` deny) + a real aa-runtime, sends `CheckActionRequest` frames over the runtime UDS (the SDK wire), and asserts `read_file`→Allow, `delete_file`→Deny end-to-end. Root cause (runtime passed `gateway_client=None` in production) fixed via AAASM-3430 (merged `fc0b40b7`). | `aa-integration-tests::e2e_runtime_gateway_deny runtime_forwards_per_tool_deny_to_gateway` PASS in the Linux **Test** job, master CI runs [27835257358 (#1161)](https://github.com/ai-agent-assembly/agent-assembly/actions/runs/27835257358) and 27836561173 (#1162). |
| AAASM-3340 | AAASM-3161 — release signature verification (cosign) | **Pass** (8 passed, 1 xfail tracked) | Release `v0.0.1-beta.3` ships `SHA256SUMS` + `SHA256SUMS.cosign.bundle` (Sigstore bundle v0.3: Fulcio cert + 1 Rekor entry + RFC3161 timestamp + messageSignature). The bundle's signed `messageDigest` (`a9737ec8…a539`) equals `sha256(SHA256SUMS)` exactly; SHA256SUMS matches each binary tarball checksum, which matches the homebrew formula sha256s — full integrity chain (bundle → SHA256SUMS → binaries → tap) verified. | integration-tests release-integrity suite run with `AASM_RELEASE_VERSION=0.0.1-beta.3`: **8 passed, 1 xfailed** — live release asset-list + integrity checks now execute (no longer skip-guarded). |
| AAASM-3342 | Version-metadata drift — Cargo/docs vs release line | **Pass** | The prior drift (Cargo at `0.0.1-alpha.5` / docs at alpha.4–5 vs the release line) is gone now that beta.3 is cut: agent-assembly `[workspace.package] version = "0.0.1-beta.3"` matches the `v0.0.1-beta.3` tag (`e2396595…`) and crates.io `aa-core` 0.0.1-beta.3. Per AAASM-3375 PR #1172, docs compatibility-matrix + installation.md/README live-install examples bumped to 0.0.1-beta.3; `scripts/check-docs-versions.sh 0.0.1-beta.3` exits 0. SDK registries consistent (PyPI 0.0.1b4, npm 0.0.1-beta.4, go-sdk v0.0.1-beta.3). | QA verification comment on AAASM-3342 (2026-06-20); see version-drift subsection below. |

## Base-branch SHAs tested

| Repo | Branch | SHA |
|---|---|---|
| agent-assembly | master | `30294709` |
| agent-assembly-integration-tests | master | `988a318` |
| python-sdk | master | `a9a7f2c` |
| node-sdk | master | `7ce05a7` |
| go-sdk | master | `77038c9` |
| agent-assembly-docs | main | `7b44c96` |

Release-line cross-checks (AAASM-3340 / AAASM-3342) were validated against the published
`v0.0.1-beta.3` release tag (`e2396595…`).

## xfail flips tracked

Two xfails remain after this pass. Neither is a regression recurrence; both are tracked:

- **AAASM-3161 — in-harness cosign verification gap (1 xfail in the release-integrity suite).**
  The harness validates the Sigstore-bundle integrity chain manually (above) but cannot run
  full `cosign verify` end-to-end — it lacks the cosign tool + a Sigstore trust root in the
  test environment. `test_integrity.py` records this as a documented xfail. Implementing
  in-test cosign verification (the xfail→pass flip) is a harness code change tracked as
  **AAASM-3172** (release-gated). The release-gate condition this TC asserts (signed
  artifacts published + integrity chain valid) is met.
- **AAASM-3000 — separate-repo live `_core` deadlock test (`tests/live/test_sdk_runtime.py`, AAASM-2989).**
  This live integration test is xfail and is not on agent-assembly PR-gating CI; it flips to
  XPASS once the SDK pins advance. The fix's always-green proof on Linux is the
  `aa-sdk-client::ipc::tests shutdown_is_clean_when_runtime_never_acks` unit regression above,
  which directly exercises the heartbeat/ack-never-arrives close path.

Note: release artifacts for `v0.0.1-beta.3` have shipped, so the signed `SHA256SUMS` +
`SHA256SUMS.cosign.bundle` assets now exist and the release-integrity suite executes live
(no longer skip-guarded).

## Version-drift subsection

**The drift:** at the time the TC was written, the agent-assembly Cargo workspace declared
`0.0.1-alpha.5` and docs `compatibility.md` referenced alpha.4/alpha.5, while the SDKs were
already on the beta line — a skew between Cargo/docs and the actual release line.

**Resolution (beta.3 line):** with `v0.0.1-beta.3` cut, all metadata is now consistent:

- agent-assembly `Cargo.toml` `[workspace.package] version = "0.0.1-beta.3"` matches the tag and crates.io `aa-core` 0.0.1-beta.3.
- Docs compatibility-matrix + installation.md/README live-install examples bumped to 0.0.1-beta.3 (AAASM-3375 PR #1172); `scripts/check-docs-versions.sh 0.0.1-beta.3` exits 0.
- SDK registries consistent: PyPI 0.0.1b4, npm 0.0.1-beta.4, go-sdk v0.0.1-beta.3.

Cargo / tag / crates.io / docs / SDK versions are all consistent with the published release line.

## Acceptance criteria

> AAASM-3073, AAASM-3000, AAASM-3021, AAASM-3161 regressions are non-reproducing (or current
> xfail status explicitly recorded); version-metadata drift between Cargo/docs and the release
> line is confirmed and reported.

**Met.** AAASM-3073, AAASM-3000, AAASM-3021 are non-reproducing on current master with green
Linux CI evidence. AAASM-3161's release-signature integrity chain is verified on the published
beta.3 release; its one remaining in-harness cosign xfail is explicitly recorded and tracked
(AAASM-3172). The version-metadata drift is resolved on the beta.3 release line. All five
test-case subtasks (AAASM-3335 / 3337 / 3338 / 3340 / 3342) are Done.
