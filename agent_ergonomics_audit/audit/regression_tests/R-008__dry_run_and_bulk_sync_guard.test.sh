#!/usr/bin/env bash
# audit/regression_tests/R-008__dry_run_and_bulk_sync_guard.test.sh
# Pins: --dry-run previews mutations offline (exit 0, {dry_run, method, path,
#       body}); sync --session-id '*' without --test refuses and names --yes.
set -uo pipefail
cd "$(dirname "$0")/../../.."
fail() { echo "REGRESSION: $1" >&2; exit 1; }

run_caption() {
  env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL \
    uv run caption --env-file /dev/null "$@"
}

out=$(run_caption create_project Demo --dry-run 2>/dev/null) || fail "create_project --dry-run no longer exits 0 offline (R-008)"
echo "$out" | jq -e '.dry_run == true and .method == "POST" and (.body.name == "Demo")' >/dev/null \
  || fail "create_project --dry-run lost the {dry_run, method, path, body} shape (R-008)"

out=$(run_caption edit_folder f-uuid --clear-parent --dry-run 2>/dev/null) || fail "edit_folder --dry-run failed (R-008)"
echo "$out" | jq -e '.method == "PATCH" and .path == "/folders/f-uuid"' >/dev/null \
  || fail "edit_folder --dry-run preview wrong (R-008)"

err=$(run_caption sync --session-id '*' 2>&1 >/dev/null); rc=$?
[ "$rc" -ne 0 ] || fail "sync '*' without --yes/--test no longer refuses (R-008)"
echo "$err" | grep -q -- "--yes" || fail "sync '*' refusal no longer names --yes (R-008)"
echo "$err" | grep -q -- "--test" || fail "sync '*' refusal no longer names the --test safe alternative (R-008)"

echo "OK"
