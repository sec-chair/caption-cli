# Pass 1 Pre-Pass (Baseline) Simulation Summary

**Stage.** pre · **Pass.** 1 · **Mode.** audit-only (baseline only; no post-pass since no changes are applied)

**Constraint.** All steps were run **offline** with an empty `--env-file` and unset `CAPTION_*` / `CLERK_API_KEY` / `ORGANIZATION_ID`, so no network calls and no use of the repo's real `.env`. Tasks whose *successful* completion requires live Caption/Meilisearch/history credentials (the happy path of `search`, `list_*`, `create_*`, `edit_*`, `get_md`, a real `sync` send) are **not** fully simulated; their first-try ergonomics (discovery, flag-shape, error-on-missing-input) are still observable and captured here.

| Task | First-try success | Round-trips to value | Stuck? | Notes |
|------|-------------------|----------------------|--------|-------|
| task-01 discover-and-search | ❌ | blocked at step 4 (creds) | yes (typo wall) | `--help` is rich and discoverable (step 1 ✅). But `search … --liimt 5` (step 2) and the `--lim` abbreviation (step 3) both dead-end on `unrecognized arguments` with the **top-level** usage and no "did you mean". Only after manually fixing the spelling does the agent reach the (expected) credentials gate. |
| task-02 probe-capabilities | ⚠️ partial | 2 | no | `doctor` is the only "what can this tool do" surface. It returns a plain-text feature list; with no creds the list is **empty, exit 0, no stderr** (can't tell "degraded" from "healthy"). `--output json doctor` is **ignored** — still prints plain text — so there is no machine-readable capability probe. |
| task-03 dry-run-sync | ✅ | 1 | no | `sync --session-id … --test` is a clean, true dry-run: deterministic JSON (`[]` for no match), exit 0, nothing on stderr. The tool's best safety/composability story. |

**Overall (offline-reachable subset).** 1/3 first-try success. The dominant friction is **unknown-flag handling** (no typo correction, no abbreviation, subcommand-flag errors dump top-level usage) and the **absence of a machine-readable capability/contract surface** (doctor is plain-text-only and silent on failure). Discovery via `--help` and recovery from wrong *subcommands*/*values* are good; recovery from wrong *flags* is the cliff.

**Transcripts.** `task-01-discover-and-search.transcript.jsonl`, `task-02-probe-capabilities.transcript.jsonl`, `task-03-dry-run-sync.transcript.jsonl` (re-runnable; argv[0] = `caption`).
