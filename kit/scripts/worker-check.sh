#!/bin/sh
# agentic-ops worker-check (sh entry): scope and verify checks after a worker reports DONE. The behaviour lives in worker-check.py.
# Usage: worker-check.sh snapshot --out FILE [--root DIR]
#        worker-check.sh check --allow 'a,b,dir/' --verify 'COMMAND' [--since FILE] [--root DIR] [--timeout SEC] [--stat]
here=$(cd "$(dirname "$0")" && pwd)
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' >/dev/null 2>&1; then
    exec "$py" -B "$here/worker-check.py" "$@"
  fi
done
echo "worker-check: python 3 not found" >&2
exit 2
