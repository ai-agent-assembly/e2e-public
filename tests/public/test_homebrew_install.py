"""Homebrew tap and curl installer verification (gated).

Both test groups are explicitly skipped until the upstream prerequisites are
met:

- Homebrew tap tests: require ``homebrew-agent-assembly`` tap to publish a
  formula with a built bottle.  Gate controlled by env var
  ``AASM_HOMEBREW_GATE=1``.
- curl installer tests: require a public static endpoint serving the install
  script.  Gate controlled by env var ``AASM_CURL_INSTALLER_GATE=1``.

Set the respective gate variable to ``1`` (e.g. in CI) to opt the tests in
once the upstream prerequisites are satisfied.
"""

from __future__ import annotations

import os

TAP_NAME = "agent-assembly/agent-assembly"
BREW_FORMULA = "aasm"
CURL_INSTALLER_URL = (
    "https://raw.githubusercontent.com/AI-agent-assembly/agent-assembly/master/install.sh"
)

_HOMEBREW_GATE = os.environ.get("AASM_HOMEBREW_GATE", "0") == "1"
_CURL_GATE = os.environ.get("AASM_CURL_INSTALLER_GATE", "0") == "1"

_HOMEBREW_SKIP_REASON = (
    "Homebrew tap formula not yet published — set AASM_HOMEBREW_GATE=1 to enable"
)
_CURL_SKIP_REASON = (
    "curl installer endpoint not yet available — set AASM_CURL_INSTALLER_GATE=1 to enable"
)
