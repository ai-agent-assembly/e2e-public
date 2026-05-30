# Verification Modes

`agent-assembly-integration-tests` supports four verification modes that target different
states of the public stack. Choose the mode that matches what you are trying to verify.

## Modes

### `latest` — base branch integration health

Verifies the current state of all `master` branches across repos.

**When to use:** PR integration checks, scheduled nightly/weekly health monitoring, detecting
cross-repo drift before a release.

**How to run:**
```bash
bash scripts/verify-public-stack.sh
# or explicitly:
bash scripts/verify-public-stack.sh --mode latest
```

**CI workflow:** `.github/workflows/verify-latest.yml` (scheduled weekly + `workflow_dispatch`)

---

### `tag` — exact source snapshot reproducibility

Checks out a precise git tag on each repo and verifies the stack at that exact snapshot.

**When to use:** Release verification, regression reproduction, confirming a known-good state.

**How to run:**
```bash
bash scripts/verify-public-stack.sh \
  --agent-assembly v0.1.0 \
  --python-sdk v0.1.0 \
  --node-sdk v0.1.0 \
  --go-sdk v0.1.0 \
  --examples v0.1.0 \
  --mode tag
```

Or per-repo:
```bash
bash scripts/install-from-tag.sh --repo agent-assembly --tag v0.1.0
```

**CI workflow:** `.github/workflows/verify-tag.yml` (`workflow_dispatch` with tag inputs)

---

### `sha` — exact commit reproduction

Checks out a specific commit SHA for incident triage or debug reproduction.

**When to use:** Reproducing a production incident, bisecting a regression, verifying a
specific hotfix commit before it is tagged.

**How to run:**
```bash
bash scripts/install-from-branch.sh --repo agent-assembly --ref <full-40-char-sha>
```

`verify-public-stack.sh` also accepts full SHAs as ref args:
```bash
bash scripts/verify-public-stack.sh \
  --agent-assembly abc1234def5678... \
  --mode sha
```

**CI workflow:** Not automated. Run manually via `workflow_dispatch` on `verify-tag.yml`
and pass a full SHA as the tag input.

---

### `release` — public registry install path

Installs packages from public registries (PyPI, npm, Go module proxy) and verifies
that end users can install and use the SDK at a published version.

**When to use:** Verifying a release publication, checking install path health,
confirming a hotfix patch is available on registries.

**How to run:**
```bash
bash scripts/install-from-release.sh \
  --python-sdk 0.1.0 \
  --node-sdk 0.1.0 \
  --go-sdk v0.1.0
```

Or via the main script:
```bash
bash scripts/verify-public-stack.sh \
  --python-sdk 0.1.0 \
  --node-sdk 0.1.0 \
  --go-sdk v0.1.0 \
  --mode release
```

**CI workflow:** `.github/workflows/verify-release.yml` (triggered on GitHub release publish
and `workflow_dispatch`)

---

## Mode selection summary

| Scenario | Mode | Script |
|---|---|---|
| PR integration check | `latest` | `verify-public-stack.sh` |
| Scheduled nightly health check | `latest` | `verify-latest.yml` CI |
| Release cut verification | `tag` | `verify-public-stack.sh --mode tag` |
| Regression reproduction | `tag` or `sha` | `install-from-tag.sh` / `install-from-branch.sh` |
| Incident triage | `sha` | `install-from-branch.sh --ref <sha>` |
| Post-publish registry check | `release` | `verify-public-stack.sh --mode release` |
