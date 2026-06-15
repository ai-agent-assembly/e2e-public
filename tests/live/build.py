"""Build the ``aa-gateway`` binary from a core source tree.

Ensures the build prerequisites (``cargo``, ``protoc``) are present,
runs ``cargo build -p aa-gateway`` inside the given source tree, and
returns the path to the built binary.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

#: Tools required to compile aa-gateway. ``protoc`` is needed because the
#: gateway depends on aa-proto, whose build script invokes protoc.
REQUIRED_TOOLS = ("cargo", "protoc")


def missing_build_tools() -> list[str]:
    """Return the subset of :data:`REQUIRED_TOOLS` not found on ``PATH``."""
    return [tool for tool in REQUIRED_TOOLS if shutil.which(tool) is None]


def build_gateway(source_dir: Path, *, release: bool = False) -> Path:
    """Build ``aa-gateway`` in *source_dir*; return the binary path.

    Runs ``cargo build -p aa-gateway`` (debug by default). Raises
    ``RuntimeError`` if required tools are missing and
    ``subprocess.CalledProcessError`` if the build itself fails. The
    returned path is ``<source_dir>/target/<profile>/aa-gateway``.
    """
    missing = missing_build_tools()
    if missing:
        raise RuntimeError(
            f"cannot build aa-gateway — missing tools: {', '.join(missing)}"
        )

    source_dir = Path(source_dir)
    cmd = ["cargo", "build", "-p", "aa-gateway"]
    if release:
        cmd.append("--release")
    subprocess.run(cmd, cwd=source_dir, check=True)

    profile = "release" if release else "debug"
    binary = source_dir / "target" / profile / "aa-gateway"
    if not binary.is_file():
        raise RuntimeError(f"aa-gateway build reported success but {binary} is absent")
    return binary


def build_runtime(source_dir: Path, *, release: bool = False) -> Path:
    """Build ``aa-runtime`` in *source_dir*; return the binary path.

    Runs ``cargo build -p aa-runtime`` (debug by default). ``aa-runtime`` is
    the always-present local sidecar the SDKs reach over a Unix socket — the
    real SDK→core path. Raises ``RuntimeError`` if required tools are missing
    and ``subprocess.CalledProcessError`` if the build itself fails. The
    returned path is ``<source_dir>/target/<profile>/aa-runtime``.
    """
    missing = missing_build_tools()
    if missing:
        raise RuntimeError(
            f"cannot build aa-runtime — missing tools: {', '.join(missing)}"
        )

    source_dir = Path(source_dir)
    cmd = ["cargo", "build", "-p", "aa-runtime"]
    if release:
        cmd.append("--release")
    subprocess.run(cmd, cwd=source_dir, check=True)

    profile = "release" if release else "debug"
    binary = source_dir / "target" / profile / "aa-runtime"
    if not binary.is_file():
        raise RuntimeError(f"aa-runtime build reported success but {binary} is absent")
    return binary
