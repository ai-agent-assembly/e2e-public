"""Offline tests for the clean-tempdir copy and env helpers (AAASM-3153).

These run with no network/binary/checkout: they build a synthetic source tree
and assert the clean-copy strips dependency artifacts and the hermetic env
redirects caches. This is what backs the suite's core promise — a clean-env run
cannot pass because of stray local ``node_modules`` / cached venvs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.examples import conftest


def _make_dirty_tree(root: Path) -> None:
    """Create a source tree polluted with dependency/build artifacts."""
    (root / "src").mkdir(parents=True)
    (root / "src" / "main.py").write_text("print('hello')\n")
    (root / "package.json").write_text("{}\n")
    # Pollution that a clean copy must strip:
    (root / "node_modules").mkdir()
    (root / "node_modules" / "left-pad.js").write_text("// cached dep\n")
    (root / ".venv").mkdir()
    (root / ".venv" / "pyvenv.cfg").write_text("home = /usr\n")
    (root / "src" / "__pycache__").mkdir()
    (root / "src" / "__pycache__" / "main.pyc").write_text("x")
    (root / "target").mkdir()
    (root / "target" / "debug").mkdir()


@pytest.mark.examples
def test_clean_copy_strips_dependency_artifacts(tmp_path: Path) -> None:
    """A clean copy keeps source but removes node_modules/.venv/__pycache__/target."""
    src = tmp_path / "src_example"
    _make_dirty_tree(src)
    dest = tmp_path / "clean"

    conftest._copy_clean(src, dest)

    # Source survives.
    assert (dest / "src" / "main.py").is_file()
    assert (dest / "package.json").is_file()
    # Every artifact is gone — a run here cannot reuse cached deps.
    assert not (dest / "node_modules").exists()
    assert not (dest / ".venv").exists()
    assert not (dest / "src" / "__pycache__").exists()
    assert not (dest / "target").exists()


@pytest.mark.examples
def test_clean_example_copy_fixture_produces_clean_tree(clean_example_copy, tmp_path: Path) -> None:
    """The fixture factory returns a copy with artifacts stripped."""
    src = tmp_path / "src_example"
    _make_dirty_tree(src)

    dest = clean_example_copy(src)

    assert (dest / "src" / "main.py").is_file()
    assert not (dest / "node_modules").exists()
    assert not (dest / ".venv").exists()


@pytest.mark.examples
def test_clean_subprocess_env_redirects_caches(tmp_path: Path) -> None:
    """The hermetic env points every toolchain cache under the work dir."""
    env = conftest.clean_subprocess_env(tmp_path)

    for key in ("GOCACHE", "GOMODCACHE", "UV_CACHE_DIR", "npm_config_cache", "PNPM_HOME"):
        assert key in env, f"{key} missing from clean subprocess env"
        assert str(tmp_path) in env[key], f"{key}={env[key]} is not under {tmp_path}"
        assert Path(env[key]).is_dir(), f"{key} dir was not created"
    # HOME is redirected so real caches/config never leak in.
    assert str(tmp_path) in env["HOME"]


@pytest.mark.examples
def test_gocache_is_writable_for_go_runs(tmp_path: Path) -> None:
    """The redirected GOCACHE is a writable dir (AAASM-3149 requirement)."""
    env = conftest.clean_subprocess_env(tmp_path)
    gocache = Path(env["GOCACHE"])
    probe = gocache / ".write-probe"
    probe.write_text("ok")
    assert probe.read_text() == "ok"
