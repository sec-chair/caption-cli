# Pass 1 → Pass 2 Regression Alerts

**Hard-stop check (overall weighted drop > 50 pts): NONE.** Largest overall drops are
`env__ORGANIZATION_ID` (−8) and `error__invalid_subcommand` (−8) — well inside
cross-scorer noise; both rows' underlying behavior is unchanged (verified: invalid
subcommand still lists valid choices at exit 2; ORGANIZATION_ID error still names the
env var and now also the flag).

## Why the per-dimension table in uplift_diff.md shows large negative cells

Pass 1 and Pass 2 were scored by *different independent scorers* (by design — the
Pass 2 re-scorers were context-isolated from Pass 1's numbers). Two systematic
calibration differences, not behavior changes:

1. **n/a-convention variance on env/exit/error rows.** Pass 1 scored non-applicable
   dimensions as 1000 ("no burden"); the Pass 2 scorers sometimes treated those
   dimensions as applicable and scored them on the merits (e.g.
   `error__unknown_flag / output_parseability` 1000 → 600). The cell moved; the
   surface didn't.
2. **Tougher `agent_ergonomics` anchoring on read verbs.** Pass 2 scorers anchored
   "needs credentials + 1-2 round-trips" at ~500-550 where Pass 1 used ~600-650.
   Uniform across verbs, direction-consistent, and swamped by the +150..+300 gains
   on the dimensions the pass actually targeted.

## Behavior-level regression check (authoritative)

- All 11 `audit/regression_tests/R-*.test.sh` green against the post-apply binary.
- Full pytest suite: 149 passed.
- Mechanical replay of every Pass 1 baseline transcript
  (`agent_simulations/post_pass_2/replay_of_pre_pass_1.md`): no step got worse; the
  two Pass 1 "stuck" steps and the silent doctor are fixed.
- Intentional exit-code change: missing-config now exits **3** (was 1), per the
  published dictionary — this is R-002's designed behavior, documented in --help,
  capabilities, and robot-docs.

**Conclusion: no true regressions. Loop may proceed.**
