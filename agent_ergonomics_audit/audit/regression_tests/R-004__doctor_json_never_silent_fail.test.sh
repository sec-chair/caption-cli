#!/usr/bin/env bash
# audit/regression_tests/R-004__doctor_json_never_silent_fail.test.sh
# Pins: doctor never silent-fails — failed probes print reasons to stderr,
#       --output json emits {organization, features, probes}, --strict exits non-zero.
# Applied in Pass 2. Runs fully offline (unset creds + --env-file /dev/null).
set -euo pipefail
cd "$(dirname "$0")/../../.."

run_caption() {
  env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL \
    uv run caption --env-file /dev/null "$@"
}

fail() { echo "REGRESSION: $1" >&2; exit 1; }

# 1. Failed probes must be loud on stderr (never-silent-fail), exit 0 without --strict.
stderr_file=$(mktemp); stdout_file=$(mktemp)
trap 'rm -f "$stderr_file" "$stdout_file"' EXIT
run_caption doctor >"$stdout_file" 2>"$stderr_file" || fail "doctor without --strict must exit 0"
grep -q "doctor: probe 'core' failed:" "$stderr_file" \
  || fail "failed core probe no longer reports its reason on stderr (R-004)"
grep -q "doctor: probe 'agentsview' failed:" "$stderr_file" \
  || fail "failed agentsview probe no longer reports its reason on stderr (R-004)"

# 2. --output json must emit the structured contract on stdout.
run_caption --output json doctor >"$stdout_file" 2>/dev/null || fail "json doctor must exit 0"
jq -e '.probes | type == "array" and length == 2' "$stdout_file" >/dev/null \
  || fail "doctor --output json no longer returns probes[] (R-004)"
jq -e '.probes[0] | has("name") and has("available") and has("reason")' "$stdout_file" >/dev/null \
  || fail "doctor probe objects lost the {name, available, reason} shape (R-004)"
jq -e 'has("organization") and has("features")' "$stdout_file" >/dev/null \
  || fail "doctor json lost organization/features fields (R-004)"

# 3. --strict must exit non-zero when a probe fails.
if run_caption doctor --strict >/dev/null 2>&1; then
  fail "doctor --strict no longer exits non-zero on probe failure (R-004)"
fi

echo "OK"
