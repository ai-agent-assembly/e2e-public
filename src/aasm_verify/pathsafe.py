"""Path-containment guard for operator-supplied file paths.

The ``report`` subcommand takes input/output paths straight from the operator
(``--summary``, ``--out``, ``--pytest-json``, ``--jira``). A scheduled run feeds
these from workflow inputs, so a *relative* value such as ``../../etc/passwd``
could otherwise read or clobber a file outside the run's working tree (path
traversal, CWE-22). :func:`safe_path` resolves the value and, for relative
inputs, rejects anything that escapes the base directory.

An *absolute* path is treated as the operator's deliberate, explicit choice
(e.g. a CI artifact dir or a test ``tmp_path``) and is allowed — but it is still
fully resolved so the value handed to ``open`` has no unresolved ``..`` segments.
The traversal vector this closes is the relative ``..`` escape from the working
tree, which is exactly the untrusted-input case Sonar S8707 flags.
"""

from __future__ import annotations

import os
from pathlib import Path


class PathTraversalError(ValueError):
    """Raised when a relative user path resolves outside its allowed base."""


def safe_path(user_path: str, *, base: str | os.PathLike[str] | None = None) -> Path:
    """Resolve *user_path*, blocking relative escapes outside *base*.

    *base* defaults to the current working directory — the run's working tree.
    The returned path is always fully resolved (symlinks and ``..`` collapsed)
    so the caller opens exactly the vetted location.

    * A **relative** *user_path* must stay within *base*; one whose resolved
      form is neither *base* itself nor a descendant of it raises
      :class:`PathTraversalError`.
    * An **absolute** *user_path* is the operator's explicit choice and is
      permitted anywhere, after resolution.
    """
    candidate = Path(user_path)
    if candidate.is_absolute():
        return candidate.resolve()

    # A relative path is resolved *against the base* (not the process cwd, which
    # may differ), then required to stay within it — so ``..`` cannot climb out.
    base_resolved = Path(base).resolve() if base is not None else Path.cwd().resolve()
    resolved = (base_resolved / candidate).resolve()
    if resolved != base_resolved and not resolved.is_relative_to(base_resolved):
        raise PathTraversalError(
            f"path {user_path!r} resolves outside the allowed base directory {str(base_resolved)!r}"
        )
    return resolved
