"""Clean-environment validation for Python examples (AAASM-3153, AC1).

Each representative Python example is copied into a pristine tempdir (no cached
``.venv``), installed from clean with the documented ``uv sync`` command, then
run with its documented run command. The test **skips** (with a justified env
reason) when ``uv`` is absent, the examples checkout is missing, the host is
offline, or a framework-heavy example's service is not opted in; it **fails**
only when a present example install or run actually breaks (AC5).
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

_PYTHON_EXAMPLES = examples_for_language("python")
_IDS = [e.id for e in _PYTHON_EXAMPLES]


@pytest.mark.examples
@pytest.mark.parametrize("example", _PYTHON_EXAMPLES, ids=_IDS)
def test_python_example_clean_setup_and_run(
    example: Example, clean_example_copy, tmp_path: Path
) -> None:
    """A Python example installs (``uv sync``) and runs from a clean checkout."""
    src = require_clean_run_env(example)
    clean_dir = clean_example_copy(src)
    env = clean_subprocess_env(tmp_path)
    validate_example_clean(example, clean_dir, env)
