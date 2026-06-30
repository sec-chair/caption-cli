# Agent Ergonomics Scorecard

Generated: 2026-06-30T17:26:03Z
Source: `agent_ergonomics_audit/audit/agent_surfaces.jsonl` (pass 1)


## How to read this scorecard

- **Pass 1, mode `audit-only`** (no code changed). 30 surfaces scored across the 11 dimensions (0–1000) per `references/rubric/SCORING-RUBRIC.md` v1.0.0. Single-scorer pass (`score_confidence.spread_max: 0`); a `peer-claude` triangulation review is folded into `playbook.md` (and **changed several scores** — see below).
- **Evidence-backed:** every dimension scored > 700 cites a `file:line` or runtime transcript (validated by `tools/validate_scorecard.sh` — passing).
- **n/a convention:** for env-var / exit-code / error-message surfaces, dimensions that don't apply to that surface class (per `SURFACE-CLASSES.md`) are scored **1000 = "no burden on this axis."** That is why those rows show high `weighted` values despite real problems — **read their per-dimension columns, not the weighted average.** (E.g. `error__doctor_silent` weighted=813 but error_pedagogy=200, composability=300; `error__unknown_flag` weighted=768 but error_pedagogy=250, intent=200.) Verb and flag rows have all dimensions in play and are directly comparable.

## Cross-cutting weakest dimensions (the real story)

Median across the 15 verbs:

| dimension | verb median | read |
|-----------|-------------|------|
| intent_inference | **300** | no flag typo-correction; abbreviations off; unknown flags dead-end (→ R-001) |
| regression_resistance | 550 | good error/help pinning, but no robot/capabilities contract tests |
| self_documentation | 600 | rich `--help`, but no `capabilities --json` / `robot-docs`, and per-subcommand `-h` is bare (→ R-003, R-007, R-009) |
| agent_intuitiveness | 600 | discoverable help; lossy output + bare-invocation error drag it (→ R-005, R-006) |
| agent_ergonomics | 600 | 1–2 round-trips; no mega-command |
| error_pedagogy | 600 | names flags/env well; unknown-flag + doctor-silent are the holes (→ R-001, R-004) |
| agent_ease_of_use | 650 | examples + env block in top-level help |
| output_parseability | 650 | `--output json` exists everywhere — **but it is NOT full-fidelity**: `list_projects/list_folders/list_md/list_matters` stay condensed and `create_md` truncates content to 100 chars *even in JSON* (peer-corrected); `doctor` ignores `--output` entirely (→ R-004, R-005) |
| determinism_and_reproducibility | 700 | stable bytes; but `list_projects/folders` report `totalPages:1` for data they didn't fully fetch (→ R-012) |
| safety_with_recovery | 900 | mostly read verbs; `sync --test` is a real dry-run; mutators lack `--dry-run` (→ R-008) |

**Two highest-leverage fixes (peer-aligned):** `error__unknown_flag` (the loud typo cliff — error_pedagogy 250 / intent 200, **R-001**) and `error__doctor_silent` (the *silent* exit-0-on-broken-backend — error_pedagogy 200 / composability 300, **R-004**). The peer reviewer argues R-004 should be fixed first because a misleading "healthy" is more dangerous than a visible error. See `playbook.md`.

## Per-surface scores

| surface_id | weighted | intu | ergo | ease | parse | error | intent | safe | det | self | comp | regr |
|------------|----------|------|------|------|-------|-------|--------|------|-----|------|------|------|
| verb__doctor | 536 | 650 | 600 | 600 | 300 | 350 | 300 | 1000 | 700 | 550 | 400 | 450 |
| verb__token | 613 | 600 | 650 | 650 | 700 | 600 | 300 | 800 | 650 | 600 | 700 | 500 |
| verb__search | 622 | 600 | 600 | 700 | 600 | 550 | 250 | 1000 | 700 | 650 | 650 | 550 |
| verb__list_projects | 586 | 600 | 650 | 600 | 500 | 500 | 300 | 1000 | 600 | 550 | 650 | 500 |
| verb__list_folders | 586 | 600 | 650 | 600 | 500 | 500 | 300 | 1000 | 600 | 550 | 650 | 500 |
| verb__create_project | 568 | 550 | 600 | 600 | 700 | 550 | 300 | 550 | 700 | 550 | 650 | 500 |
| verb__create_folder | 568 | 550 | 600 | 600 | 700 | 550 | 300 | 550 | 700 | 550 | 650 | 500 |
| verb__edit_project | 581 | 550 | 600 | 600 | 700 | 650 | 300 | 550 | 700 | 550 | 650 | 550 |
| verb__edit_folder | 581 | 550 | 600 | 600 | 700 | 650 | 300 | 550 | 700 | 550 | 650 | 550 |
| verb__dl_transcript | 618 | 600 | 650 | 650 | 650 | 500 | 300 | 1000 | 700 | 600 | 650 | 500 |
| verb__list_matters | 613 | 600 | 600 | 650 | 550 | 600 | 300 | 1000 | 650 | 600 | 650 | 550 |
| verb__sync | 600 | 550 | 600 | 650 | 700 | 600 | 300 | 700 | 650 | 600 | 700 | 550 |
| verb__create_md | 572 | 550 | 600 | 650 | 550 | 600 | 300 | 550 | 700 | 600 | 650 | 550 |
| verb__list_md | 636 | 600 | 650 | 700 | 600 | 600 | 300 | 1000 | 650 | 650 | 700 | 550 |
| verb__get_md | 627 | 600 | 650 | 650 | 650 | 600 | 300 | 900 | 700 | 600 | 650 | 600 |
| flag__global__output | 654 | 700 | 600 | 650 | 650 | 650 | 400 | 1000 | 700 | 600 | 700 | 550 |
| flag__global__output-file | 604 | 650 | 700 | 650 | 600 | 550 | 400 | 700 | 700 | 600 | 550 | 550 |
| flag__global__cache-path | 650 | 600 | 650 | 500 | 1000 | 550 | 400 | 1000 | 700 | 500 | 700 | 550 |
| flag__global__env-file | 686 | 650 | 650 | 650 | 1000 | 550 | 400 | 1000 | 700 | 650 | 750 | 550 |
| env__CAPTION_API_URL | 790 | 1000 | 1000 | 700 | 1000 | 650 | 400 | 1000 | 1000 | 700 | 700 | 550 |
| env__CLERK_API_KEY | 772 | 1000 | 1000 | 700 | 1000 | 650 | 400 | 800 | 1000 | 700 | 700 | 550 |
| env__CAPTION_MEILI_URL | 781 | 1000 | 1000 | 650 | 1000 | 650 | 400 | 1000 | 1000 | 650 | 700 | 550 |
| env__ORGANIZATION_ID | 790 | 1000 | 1000 | 700 | 1000 | 650 | 400 | 1000 | 1000 | 700 | 700 | 550 |
| env__AGENT_VIEWER_DATA_DIR | 713 | 1000 | 1000 | 350 | 1000 | 600 | 400 | 1000 | 1000 | 350 | 650 | 500 |
| exit__0 | 818 | 1000 | 1000 | 1000 | 500 | 1000 | 1000 | 1000 | 900 | 400 | 700 | 500 |
| exit__1 | 700 | 1000 | 1000 | 1000 | 250 | 400 | 1000 | 1000 | 900 | 250 | 400 | 500 |
| exit__2 | 727 | 1000 | 1000 | 1000 | 350 | 500 | 1000 | 1000 | 900 | 300 | 450 | 500 |
| error__unknown_flag | 768 | 1000 | 1000 | 1000 | 1000 | 250 | 200 | 1000 | 1000 | 1000 | 500 | 500 |
| error__invalid_subcommand | 822 | 1000 | 1000 | 1000 | 1000 | 550 | 400 | 1000 | 1000 | 1000 | 600 | 500 |
| error__doctor_silent | 813 | 1000 | 1000 | 1000 | 1000 | 200 | 1000 | 1000 | 1000 | 1000 | 300 | 450 |

## Distribution histogram

### Weighted score distribution (per surface)

```
   0- 99 │  (0)
 100-199 │  (0)
 200-299 │  (0)
 300-399 │  (0)
 400-499 │  (0)
 500-599 │ ████████ (8)
 600-699 │ ███████████ (11)
 700-799 │ ████████ (8)
 800-899 │ ███ (3)
 900-999 │  (0)
1000     │  (0)
```

## Below-Polish-Bar surfaces (weighted < 750)

- verb__doctor (weighted: 536)
- verb__token (weighted: 613)
- verb__search (weighted: 622)
- verb__list_projects (weighted: 586)
- verb__list_folders (weighted: 586)
- verb__create_project (weighted: 568)
- verb__create_folder (weighted: 568)
- verb__edit_project (weighted: 581)
- verb__edit_folder (weighted: 581)
- verb__dl_transcript (weighted: 618)
- verb__list_matters (weighted: 613)
- verb__sync (weighted: 600)
- verb__create_md (weighted: 572)
- verb__list_md (weighted: 636)
- verb__get_md (weighted: 627)
- flag__global__output (weighted: 654)
- flag__global__output-file (weighted: 604)
- flag__global__cache-path (weighted: 650)
- flag__global__env-file (weighted: 686)
- env__AGENT_VIEWER_DATA_DIR (weighted: 713)
- exit__1 (weighted: 700)
- exit__2 (weighted: 727)
