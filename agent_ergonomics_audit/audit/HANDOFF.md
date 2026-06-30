# HANDOFF — caption-cli agent-ergonomics, Pass 2 → Pass 3

**Pass 2.** mode `full`, target `caption` on `main` (started at `f2fec36`). All 12
Pass 1 recommendations applied as individual commits on `main`, plus 3 additional
fixes found by fresh-eyes/simulation. No new branch, no sibling workspace.

(Pass 1's handoff is preserved in git history at f2fec36.)

## What landed (one commit per item, each with a regression test)

| Rec | Commit | Change |
|-----|--------|--------|
| R-004 | 554b0f5 | doctor: structured result, stderr reasons, `--output json`, `--strict` |
| R-003 | 3d68f1f | `caption capabilities` — machine-readable contract |
| R-002 | 7ac24ff | exit-code dictionary (0/1/2/3/4/5), published in --help + capabilities |
| R-001 | 465b950 | unknown-flag "did you mean", subcommand-scoped usage |
| R-005+R-011 | e4a4336 | `--full` fidelity, JSON never truncated, condensed views warn on stderr, Saved-line → stderr |
| R-012 | 8e43de3 | pagination honesty: fake totalPages/totalCount removed |
| R-009 | 9d285c6 | per-subcommand -h gets notes/examples; Agent quick start in --help |
| R-007 | 1f78f02 | `caption robot-docs guide` — in-tool agent handbook |
| R-006 | (main) | bare `caption` → full help, exit 0 |
| R-010 | (main) | `--clerk-api-key` on all authenticated verbs; unified error message |
| R-008 | (main) | `--dry-run` on mutators; `sync --session-id '*'` requires `--yes` |
| fresh-eyes | 7d4d965 | misplaced-global-flag placement hint; capabilities usage fix |
| fresh-eyes | 96b028b | doctor honors `--output-file` |
| simulation | 21743fd | `sync --dry-run` alias for `--test` |

## Verification state

- pytest: **150 passed** (baseline was 116 passing + 2 stale failures, fixed first).
- `audit/regression_tests/`: 11 tests, all green.
- ruff: clean. stdout/stderr split, non-TTY, byte-determinism: verified clean.
- Phase 6 re-score (2 context-isolated scorers, 36 surfaces, evidence-validated):
  **median +168 pts** across the 30 pre-existing surfaces; worst overall delta −8
  (scorer noise; see `regression_alerts.md`). New surfaces: capabilities 864,
  robot-docs 818, bare_invocation 832, exit 3/4/5 (914/836/841).
- Phase 9 simulation (fresh, context-isolated agent): 3/3 canonical tasks, **zero
  stuck steps** (Pass 1: two stuck steps + unreadable capability probe). Replay of
  Pass 1 transcripts: `agent_simulations/post_pass_2/replay_of_pre_pass_1.md`.

## Queued for Pass 3 (no Beads tracker installed; tracked here)

1. **Real pagination** for `list_projects`/`list_folders` — feature work, coordinate
   with the maintainer. The honesty fix (R-012) landed; the endpoint may still
   return only a first page and the tool can't tell.
2. **doctor --strict exit-code semantics** — currently exits 1 (documented carve-out).
   Consider a dedicated diagnostic mapping (3 when all failures are config, else 4).
3. **Regression tests for `--cache-path` / `--env-file` contracts** — the two lowest-
   scoring surfaces in Pass 2 (691/700), mostly on regression_resistance.
4. **`sync --test` → `--dry-run` full rename** with deprecation path (alias landed;
   docs still lead with --test).
5. **README lag** — README documents commands sparsely vs. the now-rich in-tool help;
   consider generating a command reference from `capabilities`.

## How to resume

1. Read `scorecard_pass_2.md` + `uplift_diff.md` + `regression_alerts.md`.
2. `tools/validate_scorecard.sh agent_ergonomics_audit/audit/agent_surfaces_pass_2.jsonl` → OK.
3. A Pass 3 `re-score-only` against a future HEAD diffs with
   `scripts/diff_scorecards.sh` over the concatenated pass files.
4. All work stays on `main`; the workspace is in-tree at `agent_ergonomics_audit/`.
