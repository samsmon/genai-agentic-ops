#!/bin/sh
# agentic-ops doctor (sh entry): read-only report, one PASS/WARN/FAIL/UNKNOWN line per check. The behaviour lives in doctor.py.
# Usage: doctor.sh [--project DIR] [--pin SHA]
here=$(cd "$(dirname "$0")" && pwd)
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' >/dev/null 2>&1; then
    exec "$py" -B "$here/doctor.py" "$@"
  fi
done
echo "doctor: python 3 not found" >&2
exit 2
