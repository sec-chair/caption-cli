#!/usr/bin/env bash
# audit/regression_tests/R-012__pagination_honesty.test.sh
# Pins: list_projects/list_folders no longer fabricate totalPages/totalCount,
#       and no code path claims pagination it doesn't perform.
set -uo pipefail
cd "$(dirname "$0")/../../.."

fail() { echo "REGRESSION: $1" >&2; exit 1; }

# 1. The fabricated metadata keys must not reappear in the command layer.
grep -rn --exclude-dir=__pycache__ '"totalPages"' caption_cli/ && fail "totalPages metadata reappeared in caption_cli (R-012)"
grep -rn --exclude-dir=__pycache__ '"totalCount"' caption_cli/ && fail "totalCount metadata reappeared in caption_cli (R-012)"

# 2. No signature advertises page/limit params for the workspace list fetch.
grep -rn --exclude-dir=__pycache__ "fetch_workspace_items_page" caption_cli/ && fail "lying paginated fetch signature reappeared (R-012)"

# 3. Help must not claim pagination for these verbs.
help_out=$(uv run caption --help 2>/dev/null)
echo "$help_out" | grep -i "paginates projects" && fail "--help claims pagination for list_projects again (R-012)"
echo "$help_out" | grep -i "paginates folders" && fail "--help claims pagination for list_folders again (R-012)"

# 4. Unit contract.
uv run pytest -q \
  tests/test_caption.py::test_command_list_projects_fetches_workspace_and_all_projects \
  tests/test_caption.py::test_command_list_folders_fetches_workspace_and_all_folders \
  >/dev/null 2>&1 || fail "pagination-honesty pytest contract failing (R-012)"

echo "OK"
