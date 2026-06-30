#!/usr/bin/env bash
# audit/regression_tests/R-009__subcommand_help_injection.test.sh
# Pins: per-subcommand -h shows default output + notes + example; top-level
#       --help has the 'Agent quick start' section.
set -uo pipefail
cd "$(dirname "$0")/../../.."
fail() { echo "REGRESSION: $1" >&2; exit 1; }

sub_help=$(uv run caption search -h 2>/dev/null)
echo "$sub_help" | grep -q "default output: table" || fail "search -h lost 'default output' (R-009)"
echo "$sub_help" | grep -q "Uses cached token" || fail "search -h lost CommandSpec notes (R-009)"
echo "$sub_help" | grep -q "example: caption search" || fail "search -h lost CommandSpec example (R-009)"

top_help=$(uv run caption --help 2>/dev/null)
echo "$top_help" | grep -q "Agent quick start" || fail "--help lost 'Agent quick start' section (R-009)"

echo "OK"
