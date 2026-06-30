#!/usr/bin/env bash
# audit/regression_tests/R-006__bare_invocation_help.test.sh
# Pins: bare `caption` prints the full cheat-sheet help on stdout and exits 0.
set -uo pipefail
cd "$(dirname "$0")/../../.."
fail() { echo "REGRESSION: $1" >&2; exit 1; }

out=$(uv run caption 2>/dev/null); rc=$?
[ "$rc" -eq 0 ] || fail "bare 'caption' no longer exits 0 (rc=$rc) (R-006)"
echo "$out" | grep -q "Command Cheat Sheet" || fail "bare 'caption' lost the cheat sheet (R-006)"
echo "$out" | grep -q "Agent quick start" || fail "bare 'caption' lost the agent quick start (R-006)"

echo "OK"
