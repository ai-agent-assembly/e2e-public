"""SHA256SUMS parsing for release-artifact checksum verification (AC4).

A ``SHA256SUMS`` file is the standard ``<hexdigest>␠␠<filename>`` format (two
spaces in binary mode). This is the pure parser used by the offline checksum
tests and by the live checksum-verification test; keeping it separate from the
network/IO lets the parsing logic be exercised with no download.
"""

from __future__ import annotations


def parse_sha256sums(text: str) -> dict[str, str]:
    """Parse SHA256SUMS text into ``{filename: hexdigest}``.

    Tolerates the ``*`` binary-mode marker GNU coreutils prefixes to filenames
    and ignores blank lines. A malformed line (no digest + name) is skipped
    rather than raising, since a release's checksum file should not crash the
    verifier on an unexpected comment line.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            continue
        digest, name = parts
        result[name.lstrip("*").strip()] = digest.lower()
    return result
