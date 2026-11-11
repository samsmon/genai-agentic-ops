#!/bin/sh
# genai-agentic-ops installer (sh entry). The behaviour lives in install.py so the PowerShell and sh entries cannot drift.
# Dry run by default; add --apply to write. Options: see `sh install.sh --help`.
here=$(cd "$(dirname "$0")" && pwd)
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(0 if sys.version_info[0] >= 3 else 1)' >/dev/null 2>&1; then
    exec "$py" -B "$here/install.py" "$@"
  fi
done
echo "install: python 3 not found (the guard hooks need it too)" >&2
exit 2
