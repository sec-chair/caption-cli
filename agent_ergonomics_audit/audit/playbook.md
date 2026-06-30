# caption-cli — Agent-Ergonomics Playbook (Pass 1, audit-only)

**Target.** `caption` @ `8821c1d` on `main` · **Mode.** audit-only (no code changed) · **Date.** 2026-06-30
**Rubric.** v1.0.0 · **Surfaces scored.** 30 · **Recommendations.** 12 · **Triangulation.** peer-claude (folded in; changed several scores + the apply order)

> **The One Rule lens.** Design every surface so the first thing an agent instinctively tries "just works," and when it's wrong-but-legible, the tool infers intent or refuses with the exact fix. `caption` is *already a thoughtful tool* for agents — clean stdout/stderr split, no color to leak, a `--output json` switch, a token-stripping transcript default, a real `sync --test` dry-run, and a 118-test suite. The gaps are concentrated and high-leverage.

## Scoreboard

- Verb weighted scores cluster **536–636** (median ~600). No surface is a disaster; none is great.
- Weakest cross-cutting dimensions (verb medians): **intent_inference 300**, regression_resistance 550, self_documentation/error_pedagogy/intuitiveness/ergonomics 600, output_parseability 650.
- **Two worst surfaces (by applicable dims):** `error__unknown_flag` (error_pedagogy 250 / intent 200) and `error__doctor_silent` (error_pedagogy 200 / composability 300).
- **A correction the peer forced:** `--output json` is **not** full-fidelity — `list_projects/list_folders/list_md/list_matters` stay condensed and `create_md` truncates content to 100 chars *even in JSON*. The agent's usual escape hatch silently fails for 5 verbs.

## The two highest-leverage fixes

1. **A flag typo wedges the agent.** 4/20 intent-corpus invocations dead-ended on `useless_error` — *all four* unknown-flag cases (`--liimt`, `--lim` abbreviation [`allow_abbrev=False`], `--jsno`, `--show_token`). Response: argparse's bare `unrecognized arguments: --liimt 5` + the **top-level** usage, no "did you mean". Wrong *subcommands* and bad *values* recover fine (argparse lists the valid set). **→ R-001.** Highest by frequency×gap×blast (0.392).
2. **`doctor` lies green.** It's the only discovery surface, yet on probe failure (no creds / backend down) it prints an empty feature list, **exit 0, nothing on stderr** — indistinguishable from a healthy tool — and `--output json doctor` is *ignored* (plain text only). **→ R-004** (0.297). **The peer reviewer argues R-004 should be fixed FIRST:** a confidently-wrong "healthy" sends an agent down a broken path, which is worse than R-001's loud, visible failure. We agree on apply order even though R-001 still ranks higher numerically (it's far more *frequent*).

---

## Priority-ranked recommendations

### P0 — top of the list

**R-001 · Flag typo "did you mean" (+ subcommand-scoped usage) · 0.392 · ⟁ 🩹**
intent_inference +400 (300→~700), error_pedagogy +250, intuitiveness +150. Ship in two parts: (a) CHEAP — wrap `parse_known_args`, Levenshtein-1 over the union of known flags, print `did you mean --limit?` to stderr; (b) HARDER (peer-flagged) — argparse bubbles unrecognized optionals to the *top* parser, so re-attributing them to the chosen subcommand and printing *its* usage needs post-processing the leftovers. No existing test pins unrecognized-arg behavior, so (a) won't fight tests.

**R-004 · `doctor` → JSON + never-silent-fail (peer's #1 to ship) · 0.297 · 🩻 🚫 🪧**
output_parseability +400, error_pedagogy +300, composability +300. Stop special-casing doctor in `run()`; return `{organization, features[], probes:[{name, available, reason}]}` via `emit_output` (keep a plain default); populate `reason` on each failed probe; add `--strict` to exit non-zero when an expected probe fails.

**R-005 · Make dropped data recoverable (`--full`) + signal lossiness on stderr · 0.189 · 🪧**
output_parseability +200, intuitiveness +100. The lossiness is in the **command layer**, not the renderer, so `--output json` doesn't save you: `_project_view`/`_folder_view` (7/6 fields), `_condense_list` (list_md/list_matters), and especially `create_md`'s unconditional 100-char clip. Add `--full` (raw, no-condense) to those verbs; make create_md's truncation apply only to the human view, never JSON; emit a stderr note when a view drops fields.

**R-012 · Stop reporting pagination the tool doesn't perform · 0.175 · 🔢 🚫** *(peer-surfaced)*
output_parseability +150, determinism +150, error_pedagogy +100. `fetch_workspace_items_page` ignores page+limit; `_command_list_workspace_items` hardcodes `totalPages:1`; the spec note claims it "paginates." So `list_projects`/`list_folders` silently return only the first page while telling the agent (via `totalPages:1`) that it's complete. Either implement real pagination or drop the misleading metadata + "paginates" claim. (Overlaps a pure bug, but the *misleading metadata* is an agent-trust failure, so it's a rec.)

### P1 — foundational enablers

**R-002 · Exit-code dictionary; stop overloading exit 1 · 0.16 · 🚦**
output_parseability +250, composability +250. Today exit 1 = missing-env, HTTP error, Meili-auth, file/DB error; bad input splits between 1 (hand-validation) and 2 (argparse). `CliError.exit_code` is never set to anything but 1 (peer-verified). Give subclasses distinct codes (1 user-input, 2 usage, 3 config, 4 upstream, 5 not-found), move hand-validations to argparse-time, and publish the dictionary in `--help` + capabilities.

**R-003 · `caption capabilities --json` · 0.15 · 📜 📐**
self_documentation +350, output_parseability +150. No capabilities surface → every session re-reads `--help`. Generate JSON {tool, version, contract_version, commands[], exit_codes{}, env_vars[]} straight from the `_command_specs()` table (no duplicate source of truth). This is also the natural home for R-002's exit-code dictionary — build it early.

### P2 — polish

- **R-006 · Bare `caption` → help (exit 0)** · 0.084 · ① 🧭. Today bare → argparse error (exit 2), short usage only, no cheat-sheet.
- **R-007 · `caption robot-docs guide`** · 0.072 · 📖. In-tool agent handbook: output-default-per-command, "pass `--output json`", exit codes, env map, auth order, `sync --test`, capabilities pointer.
- **R-010 · Unify the CLERK_API_KEY surface across both backends; document AGENT_VIEWER_DATA_DIR** · 0.072 · 🛂 🩹 *(peer-deepened)*. Main-API verbs read the key from env ONLY (no `--clerk-api-key` flag); history verbs accept both flag + env, with a different error string. Same credential, two surfaces — a flag learned on `sync` fails on `create_project`. Add a global `--clerk-api-key`/`--org-id` (or document the split) and unify the message. `AGENT_VIEWER_DATA_DIR` is README-only — add it to `--help`.
- **R-008 · `--dry-run` for create_*/edit_* + guard `sync --session-id '*'`** · 0.054 · 🛡. `sync` has `--test`; mutators don't. `sync '*'` mass-sends with no confirmation (the no-`--test` path has zero gating).
- **R-009 · AGENT section in `--help` + inject CommandSpec notes/examples into each subcommand's `-h`** · 0.0525 · 🧭 📖 *(peer-flagged)*. The good `notes`/`example` content lives only in the top-level epilog; `caption search -h` is bare argparse. The data already exists on `CommandSpec`.
- **R-011 · Move the `--output-file` "Saved …" line to stderr** · 0.027 · 🪧. Bundle with R-005 (same channel-hygiene commit); with `--output-file` this line is currently the *only* thing on stdout.

---

## What's already good (keep it)

- **stdout = data, stderr = diagnostics.** Errors go to stderr via `main.py`; data via `emit_output`. No ANSI color anywhere → pipelines and `NO_COLOR` are non-issues.
- **`--output json` exists for every read verb** (the parseability *floor* is high) — caveat (R-005): it is condensed/truncated for several verbs, so "json available" ≠ "full fidelity."
- **`sync --test`** is a textbook safe-alternative dry-run; **`dl_transcript`** strips timestamps by default for token efficiency — both are agent-aware design.
- **Errors name the flag/env var** for the common cases (`--limit must be >= 1`, `--index cannot be empty`, `Use either --description or --clear-description, not both`, `Missing Caption API URL. Set CAPTION_API_URL`); invalid *subcommands*/*values* list the valid set.
- **A real 118-test suite** pins help substrings, error messages, output-format defaults, and JSON request bodies — `regression_resistance` is genuinely above baseline (no unrecognized-arg test, though, so R-001 lands cleanly).

## Suggested apply order for a future `full` pass

Per the peer (silent-fail first; build the contract home early):
**R-004 (doctor) → R-003 (capabilities, houses the exit dict) → R-002 (exit codes) → R-001 (flag typo) → R-005 (+R-011) → R-012 → R-009 → R-007 → R-006 → R-010 → R-008.**
Each lands one commit + one `audit/regression_tests/R-NNN__*.test.sh`; keep `uv run pytest` green. Every targeted behavior is offline-testable (this audit verified them all offline with `--env-file /dev/null` + unset creds).

---

## Triangulation (peer-claude)

An independent fresh-context Claude reviewer read the source + ran the binary offline. It **confirmed findings 1–4 cleanly** and materially **improved** the audit:

- **Corrected a false positive.** My draft implied `--output json` recovers full fidelity everywhere. The peer showed the lossiness is in the **command layer** (`_project_view`/`_folder_view`/`_condense_list`/`_truncate_create_md_output`), so JSON stays condensed for `list_projects/list_folders/list_md/list_matters` and `create_md` truncates to 100 chars with no escape. → I lowered `output_parseability` on those 5 verbs and broadened **R-005** from "stderr hint only" to "add `--full` + fix create_md's JSON truncation."
- **Surfaced a missed HIGH issue.** The `list_projects/list_folders` single-page-with-`totalPages:1` defect (it advertises pagination it doesn't do). I had parked this as "out of scope (correctness)"; the peer correctly reframed the *misleading metadata* as an agent-trust failure. → promoted to **R-012**.
- **Deepened the auth finding.** Not just two error phrasings — the main-API verbs have *no* `--clerk-api-key` flag at all (env-only) while history verbs accept both. → broadened **R-010** (intent_inference +150).
- **Flagged a self-doc gap I'd under-weighted.** `CommandSpec.notes`/`example` appear only in top-level help; per-subcommand `-h` is bare. → broadened **R-009** to inject them per subparser.
- **Disputed my prioritization.** Argued R-004 (silent-fail) should *lead* the apply order over R-001 (loud typo). → I raised R-004's blast_radius (silent-fail class) to 0.297 and set the apply order to lead with R-004, while keeping R-001 numerically #1 (it's far more frequent). Both are P0.
- **De-risked R-001.** Confirmed no existing test pins unrecognized-argument behavior, and noted the subcommand-scoping half is harder than framed (argparse bubbles unrecognized optionals to the top parser). → split R-001 into a cheap part (a) and a harder part (b).

Net: the audit is accurate and well-prioritized after these changes; the single most important correction was promoting `doctor`'s silent exit-0 to the front of the apply order and adding the pagination-honesty item.
