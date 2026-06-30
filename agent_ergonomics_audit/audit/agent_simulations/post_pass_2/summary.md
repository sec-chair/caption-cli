# Fresh-agent simulation — post Pass 2

Operator ran every invocation offline with no credentials:
`env -u CAPTION_API_URL -u CLERK_API_KEY -u ORGANIZATION_ID -u CAPTION_MEILI_URL uv run caption --env-file /dev/null <args>`

## Per-task results

| Task | First-try success | Round-trips to value | Ever stuck? |
|------|-------------------|----------------------|-------------|
| 1 — discover-and-search | partial | 1 to discover; correct search built by step 5 (blocked only by missing creds) | no |
| 2 — probe-capabilities | yes | 1 (`capabilities`); +1 for live availability (`doctor --strict`) | no |
| 3 — dry-run-sync | no (guessed `--dry-run` first) | 2 | no |

## Where the tool helped or hurt

Discovery is effortless: a bare `caption` prints usage plus an "Agent quick start", an env-var list, exit-code dictionary, and a full per-command cheat sheet, so I never had to guess what commands or flags existed. Flag mistakes were handled gracefully — both the typo (`--limt`) and the abbreviation (`--lim`) returned exit 2 with "did you mean --limit?", and the bad `sync --dry-run` guess returned the complete list of valid flags, which named `--test` and got me unstuck in one step. The capabilities/doctor split is a real strength: `capabilities` gives an offline machine-readable contract (exit 0), while `doctor --strict --output json` reports each probe as `available:false` with a reason that names the exact missing env var — and because plain `doctor` still exits 0, I could clearly distinguish "tool healthy" from "feature unavailable." The only friction points were minor and environmental: credential-gated commands (search) can't complete without `CAPTION_API_URL`, though the error says exactly that; and `sync` uses `--test` rather than the `--dry-run` that every other mutating subcommand uses, a naming inconsistency that cost one round-trip but was immediately self-correcting thanks to the flag-listing error. I was never stuck on any task.
