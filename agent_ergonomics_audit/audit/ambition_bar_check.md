# Ambition Bar Check — Pass 2 (full)

(Pass 1's audit-only check is preserved in git history at f2fec36.)

## Soft-target evaluation

| Gate | Target | Actual | Met |
|------|--------|--------|-----|
| Substantive landed changes | ≥ 10 (non-trivial CLI) | **14** (11 recommendation commits covering all 12 recs, 2 fresh-eyes fix commits, 1 simulation-driven fix commit) | ✅ |
| Dimensions covered by applied set | ≥ 3 | **7+** (intent_inference, error_pedagogy, output_parseability, self_documentation, composability, safety_with_recovery, determinism) | ✅ |
| Mega-command (when missing) | 1 | `caption capabilities` (CAPABILITIES shape) + `caption --output json doctor --strict` (DIAGNOSE shape) | ✅ |
| capabilities / robot-docs (when missing) | 1 each | both added (R-003, R-007) | ✅ |
| `--json` / full-fidelity structured output | 1 | doctor JSON (R-004) + `--full` fidelity across 5 verbs, JSON never truncated (R-005) | ✅ |
| Error-message rewrite naming the exact fix | 1 | unknown-flag did-you-mean (R-001), unified credential message (R-010), sync wildcard refusal naming --yes/--test (R-008), misplaced-global-flag placement hint (fresh-eyes) | ✅ |
| Intent-inference handler for most common wrong invocation | 1 | difflib close-match over global+subcommand flags; all 4 Pass 1 wedge cases now hint (R-001) | ✅ |
| Regression tests per applied rec | all | 11 tests in `audit/regression_tests/`, each green post-apply; pytest suite 150 green | ✅ |
| Phase 6 median uplift | ≥ 50 pts | **+168 median** across 30 re-scored surfaces; no overall regression > 8 pts | ✅ |

## "That's it??" self-prompt

**Not triggered** — every gate is met and the applied set covers all 12 Pass 1
recommendations plus 3 issues found during Phase 7/9 (misplaced-global-flag hint,
doctor honoring --output-file, sync --dry-run alias).

## Not counted as substantive

- Baseline test-assertion fix (2 stale search-header pins) — hygiene.
- README discovery section — documentation (half-credit at most; excluded).
- audit/ bookkeeping commits — excluded by definition.

## Deferred (see HANDOFF.md)

Real pagination for list_projects/list_folders (feature work), doctor --strict
dedicated exit code, regression tests for --cache-path/--env-file contracts.
