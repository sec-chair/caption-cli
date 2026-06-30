# Pass 1 Scope Decision

**Mode.** `audit-only` — score every surface, produce ranked recommendations + playbook + scorecard + heatmap. **No code changes** to the target.
**Target.** `/Users/alin/code/caption/caption-cli`
**Workspace.** `/Users/alin/code/caption/caption-cli/agent_ergonomics_audit/` — in-tree; never a sibling.
**Target branch.** `main` (this skill never creates a new branch and never switches off the current one).
**Triangulation appetite.** `peer-claude` (one independent Claude reviewer on Phase 4 recommendation synthesis).
**CASS appetite.** `skip` (user opted out of prior-session mining).
**Date.** 2026-06-30

## Must-not-touch

- Nothing off-limits was specified by the user. Since this is `audit-only`, **no target source is modified regardless** — all findings are recommendations only.

## Deprecation policies

- N/A for an audit-only pass (no changes applied). Recommendations note backward-compat strategy (add, don't remove) for the implementer of a future `full` pass.

## Out-of-scope feature work

- Feature requests are not in scope for an ergonomics audit. One correctness observation surfaced during source review (workspace listing claims pagination in help/notes but `_command_list_workspace_items` fetches a single page and always reports `totalPages: 1`); recorded as a note in the scorecard, **not** an ergonomics recommendation.

## Environment notes

- Toolchain present: `uv`, Python 3.13, `.venv`. No install needed.
- `flock` + `timeout` absent (macOS default). Only matters for concurrent appliers / the timeout-wrapped inventory walker — neither used in a single-threaded audit-only pass. Inventory + intent-corpus were driven directly.
- Helper skills absent: `/agent-mail`, `/br` (Beads), `/cass`, `/ubs`. Inline fallbacks used; deferred work tracked in `HANDOFF.md` rather than beads.
- All runtime probes were run with an **empty `--env-file` and unset `CAPTION_*`/`CLERK_*`/`ORGANIZATION_ID`** so nothing touched the network or loaded the repo's real `.env`. This keeps the audit offline, deterministic, and side-effect-free.
