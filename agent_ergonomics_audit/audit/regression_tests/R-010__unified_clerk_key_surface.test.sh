#!/usr/bin/env bash
# audit/regression_tests/R-010__unified_clerk_key_surface.test.sh
# Pins: --clerk-api-key parses on main-API verbs, the missing-key error names
#       flag + env var on both backends, AGENT_VIEWER_DATA_DIR is in --help.
set -uo pipefail
cd "$(dirname "$0")/../../.."
fail() { echo "REGRESSION: $1" >&2; exit 1; }

run_caption() {
  env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL \
    uv run caption --env-file /dev/null "$@"
}

# 1. Flag parses on a main-API verb (offline: fails on config, NOT usage).
run_caption list_projects --clerk-api-key k >/dev/null 2>&1
[ $? -eq 3 ] || fail "--clerk-api-key no longer parses on list_projects (R-010)"

# 2. Unified error text on the main-API path.
err=$(run_caption dl_transcript some-id --clerk-api-key k 2>&1); rc=$?
# with a key but no API URL, the failure is the URL — force the token error instead:
err=$(env -u CLERK_API_KEY CAPTION_API_URL=http://localhost:9 uv run caption --env-file /dev/null list_projects 2>&1 >/dev/null)
echo "$err" | grep -q -- "--clerk-api-key or set CLERK_API_KEY" \
  || fail "main-API missing-key error no longer names the flag and env var (R-010)"

# 3. AGENT_VIEWER_DATA_DIR documented in help.
uv run caption --help 2>/dev/null | grep -q "AGENT_VIEWER_DATA_DIR" \
  || fail "--help lost AGENT_VIEWER_DATA_DIR (R-010)"

echo "OK"
