#!/bin/sh
# Run the sh and Python kit tests (the PowerShell suites are run by run-tests.ps1). Exit 1 if any fails.
here=$(cd "$(dirname "$0")" && pwd)
bad=0
for t in "$here"/test_*.py; do
  [ -f "$t" ] || continue
  if python3 -I "$t" >/dev/null 2>&1 || python -I "$t" >/dev/null 2>&1; then echo "OK     $(basename "$t" .py)"; else echo "FAIL   $(basename "$t" .py)"; bad=$((bad + 1)); fi
done
if bash "$here/scripts.tests.sh" >/dev/null 2>&1; then echo 'OK     scripts.tests.sh'; else echo 'FAIL   scripts.tests.sh (run it directly for details)'; bad=$((bad + 1)); fi
echo "[TESTS] $bad suite(s) failed"
[ "$bad" -eq 0 ]
