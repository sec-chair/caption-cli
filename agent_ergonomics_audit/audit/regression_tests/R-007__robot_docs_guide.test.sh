#!/usr/bin/env bash
# audit/regression_tests/R-007__robot_docs_guide.test.sh
# Pins: `caption robot-docs guide` exists, works offline, and covers the
#       exit-code dictionary, env vars, and per-command sections.
set -uo pipefail
cd "$(dirname "$0")/../../.."
fail() { echo "REGRESSION: $1" >&2; exit 1; }

out=$(env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL \
  uv run caption --env-file /dev/null robot-docs guide 2>/dev/null) \
  || fail "'caption robot-docs guide' no longer exits 0 offline (R-007)"

echo "$out" | grep -q "agent guide" || fail "robot-docs lost its title (R-007)"
echo "$out" | grep -q "## Exit codes" || fail "robot-docs lost the exit-code section (R-007)"
echo "$out" | grep -q "## Environment" || fail "robot-docs lost the environment section (R-007)"
echo "$out" | grep -q "### search" || fail "robot-docs lost per-command sections (R-007)"

# bare `robot-docs` defaults to the guide topic
env -u CAPTION_API_URL uv run caption --env-file /dev/null robot-docs >/dev/null 2>&1 \
  || fail "bare 'caption robot-docs' no longer defaults to guide (R-007)"

echo "OK"
