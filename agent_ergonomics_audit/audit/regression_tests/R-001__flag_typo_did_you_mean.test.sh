#!/usr/bin/env bash
# audit/regression_tests/R-001__flag_typo_did_you_mean.test.sh
# Pins: unknown flags produce a 'did you mean' hint + subcommand-scoped usage
#       (exit 2), instead of the top-level usage with no suggestion.
# Applied in Pass 2. Runs fully offline (parse-time behavior only).
set -uo pipefail
cd "$(dirname "$0")/../../.."

fail() { echo "REGRESSION: $1" >&2; exit 1; }

check_case() {
  local desc="$1"; shift
  local expect="$1"; shift
  local stderr rc
  stderr=$(uv run caption "$@" 2>&1 >/dev/null); rc=$?
  [ "$rc" -eq 2 ] || fail "$desc: exit code $rc != 2 (R-001)"
  echo "$stderr" | grep -qF "$expect" || fail "$desc: stderr lost '$expect' (R-001)"
}

check_case "typo --liimt"        "did you mean --limit?"       search q --liimt 5
check_case "underscore spelling" "did you mean --show-token?"  token --show_token
check_case "abbreviation --lim"  "did you mean --limit?"       search q --lim 5
check_case "subcommand usage"    "usage: caption search"       search q --liimt 5
check_case "no-match flag list"  "Valid flags:"                search q --jsno

echo "OK"
