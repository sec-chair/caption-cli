#!/usr/bin/env bash
# audit/regression_tests/R-005__full_fidelity_and_lossiness_signal.test.sh
# Pins: --full exists on the condensing verbs, condensed views announce
#       themselves on stderr, and the --output-file 'Saved' line lives on
#       stderr (R-011, bundled). Parse-time + unit-level checks, fully offline.
set -uo pipefail
cd "$(dirname "$0")/../../.."

fail() { echo "REGRESSION: $1" >&2; exit 1; }

# 1. --full is accepted by all four condensing list verbs + create_md.
for verb_args in "list_projects --full" "list_folders --full" "list_matters --full" "list_md --full"; do
  # shellcheck disable=SC2086
  stderr=$(env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID \
    uv run caption --env-file /dev/null $verb_args 2>&1 >/dev/null)
  rc=$?
  # Offline these exit 3 (missing config) — the point is argparse ACCEPTS --full (not exit 2).
  [ "$rc" -eq 3 ] || fail "'caption $verb_args' no longer parses (rc=$rc; --full flag lost?) (R-005)"
  echo "$stderr" | grep -q "unrecognized" && fail "'--full' rejected on '$verb_args' (R-005)"
done

# 2. The unit-level fidelity contract is pinned by pytest tests; run just those.
uv run pytest -q \
  tests/test_caption.py::test_list_projects_full_returns_raw_payload_without_note \
  tests/test_agentsview_md.py::test_create_md_json_output_never_truncates \
  tests/test_agentsview_md.py::test_create_md_full_flag_never_truncates \
  tests/test_agentsview_md.py::test_create_md_truncated_view_warns_on_stderr \
  tests/test_agentsview_md.py::test_list_md_full_returns_raw_documents \
  tests/test_caption.py::test_run_list_projects_writes_rendered_output_file_and_saved_line \
  >/dev/null 2>&1 || fail "fidelity/lossiness pytest contract failing (R-005/R-011)"

echo "OK"
