# Release QA reports

This subtree holds **release-versioned** QA verification reports — one report per
released artifact, capturing the full-product QA pass that gates a release.

It complements the per-ticket reports in the parent `verification-reports/`
directory (the `AAASM-*-verification.md` files), which document acceptance
verification for an individual Story/Subtask. Release reports instead summarize
QA for a whole release across every product area.

## Layout

```
verification-reports/
├── AAASM-*-verification.md      # per-ticket acceptance reports
└── releases/
    ├── README.md                # this file
    ├── TEMPLATE.md              # fill-in-the-blanks release QA report
    └── <version>/
        └── <repo>-<version>-qa.md
```

Each release gets its own `<version>/` directory (e.g. `v0.0.1-beta.4/`), and each
repo verified for that release gets one report named `<repo>-<version>-qa.md`
(e.g. `agent-assembly-integration-tests-v0.0.1-beta.4-qa.md`).

## How to author a release QA report

1. Copy [`TEMPLATE.md`](./TEMPLATE.md) to
   `verification-reports/releases/<version>/<repo>-<version>-qa.md`.
2. Fill in every placeholder: header (repo, version, exact git SHA, date, QA owner,
   environment), scope & method, results matrix, docs verification (correctness /
   human-readability / LLM-readability, per AAASM-3547), defects found, CI evidence,
   sign-off, and reproducibility commands.
3. Cite evidence the way the per-ticket reports do — CI run URLs, exact test counts,
   and tracking Jira keys for any xfail / deferred item.
4. Open the report in the same PR (or a follow-up PR) that records the release QA pass.

The template is the source of truth for the required sections; keep it and this
README in sync if the convention changes.
