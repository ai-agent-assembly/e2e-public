#!/usr/bin/env bash
# Reads a pytest JSON report and writes a sanitized summary.json.
#
# Usage:
#   summarize-run.sh --area AREA --mode MODE [--run-url URL] \
#                    [--pytest-json PATH] [--output PATH]
#
# Inputs (in priority order):
#   --pytest-json PATH  explicit path to pytest --json-report output
#   $PYTEST_JSON        env var pointing to the same file
#   (empty)             produces status: unknown
#
# Output (stdout or --output PATH):
#   { "area": "...", "mode": "...", "status": "pass|failure|unknown", ... }
set -euo pipefail

AREA=""
MODE=""
RUN_URL=""
OUTPUT="-"
PYTEST_JSON_PATH="${PYTEST_JSON:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --area)        AREA="$2";             shift 2 ;;
    --mode)        MODE="$2";             shift 2 ;;
    --run-url)     RUN_URL="$2";          shift 2 ;;
    --output)      OUTPUT="$2";           shift 2 ;;
    --pytest-json) PYTEST_JSON_PATH="$2"; shift 2 ;;
    *) echo "error: unknown argument: $1" >&2; exit 1 ;;
  esac
done

[[ -z "$AREA" ]] && { echo "error: --area is required" >&2; exit 1; }
[[ -z "$MODE" ]] && { echo "error: --mode is required" >&2; exit 1; }

# Fall back to $PYTEST_JSON env var if --pytest-json was not supplied
if [[ -z "$PYTEST_JSON_PATH" && -n "${PYTEST_JSON:-}" && -f "${PYTEST_JSON}" ]]; then
  PYTEST_JSON_PATH="${PYTEST_JSON}"
fi

python3 - "$AREA" "$MODE" "$RUN_URL" "$PYTEST_JSON_PATH" "$OUTPUT" <<'PYEOF'
import json
import os
import sys

area, mode, run_url, json_path, output = (
    sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
)

data: dict = {}
if json_path and os.path.isfile(json_path):
    try:
        with open(json_path) as fh:
            data = json.load(fh)
    except Exception:
        pass

if data:
    summary = data.get("summary", {})
    passed = int(summary.get("passed", 0))
    failed = int(summary.get("failed", 0))

    failed_tests: list[str] = []
    for test in data.get("tests", []):
        if test.get("outcome") in ("failed", "error"):
            nodeid: str = test.get("nodeid", "")
            name = nodeid.split("::")[-1] if "::" in nodeid else nodeid
            failed_tests.append(name)

    status = "failure" if failed > 0 else "pass"
    n = len(failed_tests)
    short = (
        f"{n} test(s) failed in area: {area}"
        if n > 0
        else f"All {passed} test(s) passed in area: {area}"
    )
    result = {
        "area": area,
        "mode": mode,
        "run_url": run_url,
        "passed": passed,
        "failed": failed,
        "status": status,
        "failed_tests": failed_tests[:20],
        "short_summary": short,
    }
else:
    result = {
        "area": area,
        "mode": mode,
        "run_url": run_url,
        "passed": 0,
        "failed": 0,
        "status": "unknown",
        "failed_tests": [],
        "short_summary": f"No pytest report available for area: {area}",
    }

out = json.dumps(result, indent=2)
if output == "-":
    print(out)
else:
    with open(output, "w") as fh:
        fh.write(out)
        fh.write("\n")
    print(f"summary written to {output}", file=sys.stderr)
PYEOF
