#!/usr/bin/env bash
# audit/regression_tests/R-007__guide_markdown.test.sh
# Pins: `caption guide` exists, works offline, and covers the global options,
#       exit-code dictionary, env vars, and per-command sections.
set -uo pipefail
cd "$(dirname "$0")/../../.."
fail() { echo "REGRESSION: $1" >&2; exit 1; }

out=$(env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL \
  uv run caption --env-file /dev/null guide 2>/dev/null) \
  || fail "'caption guide' no longer exits 0 offline (R-007)"

echo "$out" | grep -q "agent guide" || fail "guide lost its title (R-007)"
echo "$out" | grep -q "## Global options" || fail "guide lost the global-options section (R-007)"
echo "$out" | grep -q "## Exit codes" || fail "guide lost the exit-code section (R-007)"
echo "$out" | grep -q "## Environment" || fail "guide lost the environment section (R-007)"
echo "$out" | grep -q "### search" || fail "guide lost per-command sections (R-007)"

echo "OK"
