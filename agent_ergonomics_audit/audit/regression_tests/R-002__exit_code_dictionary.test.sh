#!/usr/bin/env bash
# audit/regression_tests/R-002__exit_code_dictionary.test.sh
# Pins: the exit-code dictionary — 3 for missing config, 2 for usage errors,
#       and the dictionary published in --help and capabilities.
# Applied in Pass 2. Runs fully offline.
set -uo pipefail
cd "$(dirname "$0")/../../.."

fail() { echo "REGRESSION: $1" >&2; exit 1; }

run_caption() {
  env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL \
    uv run caption --env-file /dev/null "$@"
}

# 1. Missing config env → exit 3 (was exit 1 pre-R-002).
run_caption list_projects >/dev/null 2>&1
[ $? -eq 3 ] || fail "missing CAPTION_API_URL no longer exits 3 (R-002)"

run_caption list_md >/dev/null 2>&1
[ $? -eq 3 ] || fail "missing CLERK_API_KEY (history) no longer exits 3 (R-002)"

# 2. Usage error stays 2 (argparse).
run_caption not_a_command >/dev/null 2>&1
[ $? -eq 2 ] || fail "unknown command no longer exits 2 (R-002)"

# 3. Dictionary is published in --help and capabilities.
run_caption --help 2>/dev/null | grep -q "Exit codes" || fail "--help lost the 'Exit codes' section (R-002)"
run_caption capabilities 2>/dev/null | jq -e '.exit_codes | has("3") and has("4") and has("5")' >/dev/null \
  || fail "capabilities lost the full exit-code dictionary (R-002)"

echo "OK"
