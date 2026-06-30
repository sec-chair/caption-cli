#!/usr/bin/env bash
# audit/regression_tests/R-003__capabilities_json_contract.test.sh
# Pins: `caption capabilities` exists, needs no network/creds, and returns the
#       {tool, version, contract_version, commands[], exit_codes, env_vars} contract.
# Applied in Pass 2. Runs fully offline.
set -euo pipefail
cd "$(dirname "$0")/../../.."

out=$(env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL \
  uv run caption --env-file /dev/null capabilities 2>/dev/null) \
  || { echo "REGRESSION: 'caption capabilities' no longer exits 0 offline (R-003)" >&2; exit 1; }

fail() { echo "REGRESSION: $1" >&2; exit 1; }

echo "$out" | jq -e '.tool == "caption"' >/dev/null || fail "capabilities lost .tool (R-003)"
echo "$out" | jq -e '.contract_version | length > 0' >/dev/null || fail "capabilities lost .contract_version (R-003)"
echo "$out" | jq -e '.commands | length >= 15' >/dev/null || fail "capabilities lost commands[] (R-003)"
echo "$out" | jq -e '.commands[] | select(.name == "search") | .usage | startswith("caption search")' >/dev/null \
  || fail "capabilities command entries lost usage strings (R-003)"
echo "$out" | jq -e '.exit_codes | has("0") and has("2")' >/dev/null || fail "capabilities lost exit_codes dictionary (R-003)"
echo "$out" | jq -e '.env_vars | has("CAPTION_API_URL")' >/dev/null || fail "capabilities lost env_vars dictionary (R-003)"

echo "OK"
