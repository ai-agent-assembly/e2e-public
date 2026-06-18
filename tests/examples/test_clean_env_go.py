"""Clean-environment validation for Go examples (AAASM-3153, AC3).

Each representative Go example is copied into a pristine tempdir and run with
``go test ./...`` under a **writable, redirected ``GOCACHE``/``GOMODCACHE``**
(AAASM-3149) so the run does not depend on — or pollute — the developer's real
Go caches. The test **skips** (with a justified env reason) when ``go`` is
absent, the examples checkout is missing, the host is offline, or a
framework-heavy example's service is not opted in; it **fails** only when a
present example's tests actually break (AC5).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.examples.conftest import (
    clean_subprocess_env,
    require_clean_run_env,
    validate_example_clean,
)
from tests.examples.manifest import Example, examples_for_language

_GO_EXAMPLES = examples_for_language("go")
_IDS = [e.id for e in _GO_EXAMPLES]


@pytest.mark.examples
@pytest.mark.parametrize("example", _GO_EXAMPLES, ids=_IDS)
def test_go_example_clean_setup_and_run(
    example: Example, clean_example_copy, tmp_path: Path
) -> None:
    """A Go example runs ``go test ./...`` from clean with a writable GOCACHE."""
    src = require_clean_run_env(example)
    clean_dir = clean_example_copy(src)
    env = clean_subprocess_env(tmp_path)
    validate_example_clean(example, clean_dir, env)
