#!/bin/sh
# Run the sh and Python kit tests (the PowerShell suites are run by run-tests.ps1). Exit 1 if any fails.
here=$(cd "$(dirname "$0")" && pwd)
bad=0
for t in "$here"/test_*.py; do
  [ -f "$t" ] || continue
  if python3 -I "$t" >/dev/null 2>&1 || python -I "$t" >/dev/null 2>&1; then echo "OK     $(basename "$t" .py)"; else echo "FAIL   $(basename "$t" .py)"; bad=$((bad + 1)); fi
done
for t in "$here"/*.tests.sh; do
  [ -f "$t" ] || continue
  n=$(basename "$t")
  if bash "$t" >/dev/null 2>&1; then echo "OK     $n"; else echo "FAIL   $n (run it directly for details)"; bad=$((bad + 1)); fi
done
echo "[TESTS] $bad suite(s) failed"
[ "$bad" -eq 0 ]
