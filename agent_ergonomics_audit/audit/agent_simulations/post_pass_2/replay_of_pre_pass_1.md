# Pass 2 — Mechanical Replay of the Pass 1 Baseline Transcripts

The exact argv sequences captured in `pre_pass_1/` were re-run against the post-Pass-2
binary (offline: `--env-file /dev/null`, all `CAPTION_*`/`CLERK_API_KEY`/`ORGANIZATION_ID` unset).

| Task / step | Invocation | Pass 1 outcome | Pass 2 outcome |
|---|---|---|---|
| 01 / 1 | `caption --help` | success | success (help now includes Agent quick start + exit codes) |
| 01 / 2 | `caption search roadmap --liimt 5` | **stuck** — top-level usage, no hint, exit 2 | **useful_hint** — subcommand usage + `did you mean --limit?`, exit 2 |
| 01 / 3 | `caption search roadmap --lim 5` | **stuck** — same dead end | **useful_hint** — `did you mean --limit?` |
| 01 / 4 | `caption search roadmap --limit 5` | error, exit **1** (overloaded) | error, exit **3** (config class; message unchanged) |
| 02 / 1 | `caption doctor` | **silent-degraded** — empty feature list, exit 0, empty stderr | loud — both probe failures + reasons on stderr, exit 0 |
| 02 / 2 | `caption --output json doctor` | `--output json` **ignored** (plain text) | structured JSON `{organization, features, probes[]}` on stdout; reasons on stderr |
| 03 / 1 | `caption sync --session-id nonexistent --test` | success (clean dry-run) | success (unchanged) |

**Reading.** The two Pass 1 "stuck" steps (the typo wall) now emit an exact corrective
hint, and the Pass 1 "confidently silent" doctor is now loud and machine-readable.
The only intentional behavior change in exit codes: missing-config now exits 3 per the
published dictionary (was 1).

Replayed: 2026-07-02 (Pass 2, post-apply HEAD).
