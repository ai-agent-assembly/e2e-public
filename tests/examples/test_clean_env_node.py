"""Clean-environment validation for Node examples (AAASM-3153, AC2).

Each representative Node example is copied into a pristine tempdir (no cached
``node_modules``), installed from clean with ``pnpm install --frozen-lockfile``,
then type-checked / smoke-built with its documented script. The test **skips**
(with a justified env reason) when ``pnpm``/``node`` is absent, no committed
lockfile exists for the frozen install, the examples checkout is missing, the
host is offline, or a framework-heavy example's service is not opted in; it
**fails** only when a present example install or build actually breaks (AC5).
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

_NODE_EXAMPLES = examples_for_language("node")
_IDS = [e.id for e in _NODE_EXAMPLES]


@pytest.mark.examples
@pytest.mark.parametrize("example", _NODE_EXAMPLES, ids=_IDS)
def test_node_example_clean_setup_and_run(
    example: Example, clean_example_copy, tmp_path: Path
) -> None:
    """A Node example installs (frozen lockfile) and type-checks from clean."""
    src = require_clean_run_env(example)
    clean_dir = clean_example_copy(src)
    env = clean_subprocess_env(tmp_path)
    validate_example_clean(example, clean_dir, env)
