# Pass 1 → Pass 2 Uplift Diff

Generated: 2026-07-02T21:40:34Z

## Per-surface uplift

| surface_id | prior weighted | new weighted | Δ | improved dims | regressed dims |
|------------|----------------|--------------|---|---------------|-----------------|
| env__AGENT_VIEWER_DATA_DIR | 713 | 786 | +73 | agent_ease_of_use (+550); intent_inference (+200); self_documentation (+550); composability (+50); regression_resistance (+200) | agent_intuitiveness (-350); agent_ergonomics (-100); error_pedagogy (-100); determinism_and_reproducibility (-200) |
| env__CAPTION_API_URL | 790 | 864 | +74 | agent_ease_of_use (+250); error_pedagogy (+150); intent_inference (+200); self_documentation (+250); composability (+200); regression_resistance (+150) | agent_intuitiveness (-100); agent_ergonomics (-100); determinism_and_reproducibility (-200) |
| env__CAPTION_MEILI_URL | 781 | 832 | +51 | agent_ease_of_use (+300); error_pedagogy (+100); intent_inference (+200); self_documentation (+300); composability (+200) | agent_intuitiveness (-100); agent_ergonomics (-100); determinism_and_reproducibility (-200); regression_resistance (-150) |
| env__CLERK_API_KEY | 772 | 850 | +78 | agent_ease_of_use (+250); error_pedagogy (+200); intent_inference (+200); safety_with_recovery (+200); self_documentation (+250); composability (+150); regression_resistance (+200) | agent_intuitiveness (-300); agent_ergonomics (-100); determinism_and_reproducibility (-200) |
| env__ORGANIZATION_ID | 790 | 782 | -8 | agent_ease_of_use (+250); error_pedagogy (+200); intent_inference (+200); self_documentation (+250) | agent_intuitiveness (-400); agent_ergonomics (-100); determinism_and_reproducibility (-200); composability (-100); regression_resistance (-200) |
| error__doctor_silent | 813 | 909 | +96 | error_pedagogy (+700); composability (+600); regression_resistance (+350) | output_parseability (-100); intent_inference (-300); self_documentation (-200) |
| error__invalid_subcommand | 822 | 814 | -8 | error_pedagogy (+150); composability (+300); regression_resistance (+150) | output_parseability (-400); self_documentation (-300) |
| error__unknown_flag | 768 | 900 | +132 | error_pedagogy (+700); intent_inference (+700); composability (+400); regression_resistance (+300) | output_parseability (-400); self_documentation (-250) |
| exit__0 | 818 | 914 | +96 | output_parseability (+400); self_documentation (+550); composability (+200); regression_resistance (+300) | agent_ergonomics (-150); agent_ease_of_use (-150); error_pedagogy (-100) |
| exit__1 | 700 | 886 | +186 | output_parseability (+650); error_pedagogy (+450); self_documentation (+700); composability (+500); regression_resistance (+100) | agent_ergonomics (-200); agent_ease_of_use (-150) |
| exit__2 | 727 | 909 | +182 | output_parseability (+550); error_pedagogy (+350); self_documentation (+650); composability (+450); regression_resistance (+300) | agent_ergonomics (-150); agent_ease_of_use (-150) |
| flag__global__cache-path | 650 | 691 | +41 | agent_intuitiveness (+150); agent_ergonomics (+50); agent_ease_of_use (+300); error_pedagogy (+100); intent_inference (+350); self_documentation (+300) | output_parseability (-300); composability (-200); regression_resistance (-300) |
| flag__global__env-file | 686 | 700 | +14 | agent_intuitiveness (+150); agent_ergonomics (+50); agent_ease_of_use (+150); intent_inference (+200); self_documentation (+150) | output_parseability (-300); regression_resistance (-250) |
| flag__global__output | 654 | 786 | +132 | agent_intuitiveness (+50); agent_ergonomics (+100); agent_ease_of_use (+250); output_parseability (+250); error_pedagogy (+50); intent_inference (+300); determinism_and_reproducibility (+100); self_documentation (+250); composability (+150) | regression_resistance (-50) |
| flag__global__output-file | 604 | 686 | +82 | agent_intuitiveness (+150); agent_ease_of_use (+150); output_parseability (+200); intent_inference (+350); determinism_and_reproducibility (+50); self_documentation (+200); composability (+250) | error_pedagogy (-150); regression_resistance (-300) |
| verb__create_folder | 568 | 777 | +209 | agent_intuitiveness (+250); agent_ease_of_use (+250); output_parseability (+100); error_pedagogy (+250); intent_inference (+450); safety_with_recovery (+250); determinism_and_reproducibility (+50); self_documentation (+300); composability (+150); regression_resistance (+250) | (none) |
| verb__create_md | 572 | 786 | +214 | agent_intuitiveness (+250); agent_ease_of_use (+250); output_parseability (+250); error_pedagogy (+200); intent_inference (+450); safety_with_recovery (+250); determinism_and_reproducibility (+50); self_documentation (+250); composability (+150); regression_resistance (+250) | (none) |
| verb__create_project | 568 | 782 | +214 | agent_intuitiveness (+250); agent_ease_of_use (+250); output_parseability (+100); error_pedagogy (+250); intent_inference (+450); safety_with_recovery (+250); determinism_and_reproducibility (+50); self_documentation (+300); composability (+150); regression_resistance (+300) | (none) |
| verb__dl_transcript | 618 | 786 | +168 | agent_intuitiveness (+200); agent_ease_of_use (+200); output_parseability (+100); error_pedagogy (+300); intent_inference (+450); determinism_and_reproducibility (+100); self_documentation (+250); composability (+150); regression_resistance (+250) | agent_ergonomics (-150) |
| verb__doctor | 536 | 845 | +309 | agent_intuitiveness (+200); agent_ergonomics (+200); agent_ease_of_use (+300); output_parseability (+600); error_pedagogy (+500); intent_inference (+450); determinism_and_reproducibility (+50); self_documentation (+350); composability (+400); regression_resistance (+350) | (none) |
| verb__edit_folder | 581 | 791 | +210 | agent_intuitiveness (+250); agent_ease_of_use (+300); output_parseability (+100); error_pedagogy (+200); intent_inference (+450); safety_with_recovery (+250); determinism_and_reproducibility (+50); self_documentation (+300); composability (+150); regression_resistance (+250) | (none) |
| verb__edit_project | 581 | 786 | +205 | agent_intuitiveness (+250); agent_ease_of_use (+300); output_parseability (+100); error_pedagogy (+200); intent_inference (+450); safety_with_recovery (+250); determinism_and_reproducibility (+50); self_documentation (+300); composability (+150); regression_resistance (+200) | (none) |
| verb__get_md | 627 | 786 | +159 | agent_intuitiveness (+200); agent_ease_of_use (+200); output_parseability (+100); error_pedagogy (+200); intent_inference (+450); safety_with_recovery (+100); determinism_and_reproducibility (+50); self_documentation (+250); composability (+150); regression_resistance (+150) | agent_ergonomics (-100) |
| verb__list_folders | 586 | 791 | +205 | agent_intuitiveness (+200); agent_ease_of_use (+250); output_parseability (+300); error_pedagogy (+300); intent_inference (+450); determinism_and_reproducibility (+150); self_documentation (+300); composability (+150); regression_resistance (+250) | agent_ergonomics (-100) |
| verb__list_matters | 613 | 800 | +187 | agent_intuitiveness (+200); agent_ease_of_use (+250); output_parseability (+250); error_pedagogy (+200); intent_inference (+450); determinism_and_reproducibility (+100); self_documentation (+250); composability (+150); regression_resistance (+250) | agent_ergonomics (-50) |
| verb__list_md | 636 | 814 | +178 | agent_intuitiveness (+200); agent_ease_of_use (+200); output_parseability (+250); error_pedagogy (+200); intent_inference (+500); determinism_and_reproducibility (+100); self_documentation (+200); composability (+100); regression_resistance (+300) | agent_ergonomics (-100) |
| verb__list_projects | 586 | 795 | +209 | agent_intuitiveness (+200); agent_ease_of_use (+250); output_parseability (+300); error_pedagogy (+300); intent_inference (+450); determinism_and_reproducibility (+150); self_documentation (+300); composability (+150); regression_resistance (+300) | agent_ergonomics (-100) |
| verb__search | 622 | 809 | +187 | agent_intuitiveness (+200); agent_ease_of_use (+200); output_parseability (+250); error_pedagogy (+300); intent_inference (+550); determinism_and_reproducibility (+50); self_documentation (+200); composability (+150); regression_resistance (+250) | agent_ergonomics (-100) |
| verb__sync | 600 | 800 | +200 | agent_intuitiveness (+250); agent_ease_of_use (+250); output_parseability (+100); error_pedagogy (+250); intent_inference (+450); safety_with_recovery (+150); determinism_and_reproducibility (+100); self_documentation (+250); composability (+100); regression_resistance (+300) | (none) |
| verb__token | 613 | 782 | +169 | agent_intuitiveness (+200); agent_ease_of_use (+200); output_parseability (+100); error_pedagogy (+200); intent_inference (+450); safety_with_recovery (+200); determinism_and_reproducibility (+50); self_documentation (+250); composability (+100); regression_resistance (+250) | agent_ergonomics (-150) |

**Median uplift across 30 scored surfaces:** 168 pts
**Mean uplift across 30 scored surfaces:** 141 pts

## Added surfaces (present in pass 2 only)

| surface_id | weighted_score |
|------------|----------------|
| exit__3 | 914 |
| exit__4 | 836 |
| exit__5 | 841 |
| verb__bare_invocation | 832 |
| verb__capabilities | 864 |
| verb__robot-docs | 818 |

## Regressions (per-dim drop > 25 pts)

| surface_id | dim | prior | new | Δ |
|------------|-----|-------|-----|---|
| env__AGENT_VIEWER_DATA_DIR | agent_intuitiveness | 1000 | 650 | -350 |
| env__AGENT_VIEWER_DATA_DIR | agent_ergonomics | 1000 | 900 | -100 |
| env__AGENT_VIEWER_DATA_DIR | error_pedagogy | 600 | 500 | -100 |
| env__AGENT_VIEWER_DATA_DIR | determinism_and_reproducibility | 1000 | 800 | -200 |
| env__CAPTION_API_URL | agent_intuitiveness | 1000 | 900 | -100 |
| env__CAPTION_API_URL | agent_ergonomics | 1000 | 900 | -100 |
| env__CAPTION_API_URL | determinism_and_reproducibility | 1000 | 800 | -200 |
| env__CAPTION_MEILI_URL | agent_intuitiveness | 1000 | 900 | -100 |
| env__CAPTION_MEILI_URL | agent_ergonomics | 1000 | 900 | -100 |
| env__CAPTION_MEILI_URL | determinism_and_reproducibility | 1000 | 800 | -200 |
| env__CAPTION_MEILI_URL | regression_resistance | 550 | 400 | -150 |
| env__CLERK_API_KEY | agent_intuitiveness | 1000 | 700 | -300 |
| env__CLERK_API_KEY | agent_ergonomics | 1000 | 900 | -100 |
| env__CLERK_API_KEY | determinism_and_reproducibility | 1000 | 800 | -200 |
| env__ORGANIZATION_ID | agent_intuitiveness | 1000 | 600 | -400 |
| env__ORGANIZATION_ID | agent_ergonomics | 1000 | 900 | -100 |
| env__ORGANIZATION_ID | determinism_and_reproducibility | 1000 | 800 | -200 |
| env__ORGANIZATION_ID | composability | 700 | 600 | -100 |
| env__ORGANIZATION_ID | regression_resistance | 550 | 350 | -200 |
| error__doctor_silent | output_parseability | 1000 | 900 | -100 |
| error__doctor_silent | intent_inference | 1000 | 700 | -300 |
| error__doctor_silent | self_documentation | 1000 | 800 | -200 |
| error__invalid_subcommand | output_parseability | 1000 | 600 | -400 |
| error__invalid_subcommand | self_documentation | 1000 | 700 | -300 |
| error__unknown_flag | output_parseability | 1000 | 600 | -400 |
| error__unknown_flag | self_documentation | 1000 | 750 | -250 |
| exit__0 | agent_ergonomics | 1000 | 850 | -150 |
| exit__0 | agent_ease_of_use | 1000 | 850 | -150 |
| exit__0 | error_pedagogy | 1000 | 900 | -100 |
| exit__1 | agent_ergonomics | 1000 | 800 | -200 |
| exit__1 | agent_ease_of_use | 1000 | 850 | -150 |
| exit__2 | agent_ergonomics | 1000 | 850 | -150 |
| exit__2 | agent_ease_of_use | 1000 | 850 | -150 |
| flag__global__cache-path | output_parseability | 1000 | 700 | -300 |
| flag__global__cache-path | composability | 700 | 500 | -200 |
| flag__global__cache-path | regression_resistance | 550 | 250 | -300 |
| flag__global__env-file | output_parseability | 1000 | 700 | -300 |
| flag__global__env-file | regression_resistance | 550 | 300 | -250 |
| flag__global__output | regression_resistance | 550 | 500 | -50 |
| flag__global__output-file | error_pedagogy | 550 | 400 | -150 |
| flag__global__output-file | regression_resistance | 550 | 250 | -300 |
| verb__dl_transcript | agent_ergonomics | 650 | 500 | -150 |
| verb__get_md | agent_ergonomics | 650 | 550 | -100 |
| verb__list_folders | agent_ergonomics | 650 | 550 | -100 |
| verb__list_matters | agent_ergonomics | 600 | 550 | -50 |
| verb__list_md | agent_ergonomics | 650 | 550 | -100 |
| verb__list_projects | agent_ergonomics | 650 | 550 | -100 |
| verb__search | agent_ergonomics | 600 | 500 | -100 |
| verb__token | agent_ergonomics | 650 | 500 | -150 |
