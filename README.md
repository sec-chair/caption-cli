# caption-cli

## Setup

Use `uv`. Anything else is the wrong tool for this repo.

```bash
uv sync
uv run caption --help
```

By default the CLI loads environment variables from `$PWD/.env`. Override that with `--env-file` if needed.

## Usage

The `caption` console script calls [`caption_cli.main:main`](caption_cli/main.py). Command registration lives in [`caption_cli/cli.py`](caption_cli/cli.py); API/Meilisearch behavior lives in [`caption_cli/commands.py`](caption_cli/commands.py) and [`caption_cli/core.py`](caption_cli/core.py).

### Discovery (start here if you are an agent)

- `guide`: detailed agent handbook — global options, exit codes, env vars, per-command usage (Markdown, offline)
- `--output json guide`: the same contract machine-readable (JSON, offline)
- `doctor [--strict]`: probe which Caption features are reachable; failed probes print reasons to stderr, `--strict` exits non-zero

```bash
uv run caption guide
uv run caption --output json guide
uv run caption --output json doctor --strict
```

### Environment

These variables are used by the main Caption commands:

- `CAPTION_API_URL`: required for Caption API operations, including `tail --link`
- `CLERK_API_KEY`: required for authenticated Caption API operations; not required or sent when `tail --link` uses a share link
- `CAPTION_MEILI_URL`: required for `token` and `search`

### Global flags

- `--env-file`: dotenv file to load before resolving env-based defaults
- `--cache-path`: location of the cached Meilisearch token JSON file
- `--output {json,table,md}`: output formatter
- `--output-file PATH`: write rendered command output to a file and print a saved-location message

### Commands

#### Search and auth

- `token`: fetch `/search/token` and cache it locally
- `search <query>`: search one Meilisearch index

Examples:

```bash
uv run caption token
uv run caption search "roadmap" --index transcript_sessions_v2 --limit 10
```

Supported search examples from help:

- `transcript_sessions_v2`
- `transcript_blocks_v2`

#### Workspace objects

- `list_projects`
- `list_folders`
- `create_project <name>`
- `create_folder <name>`
- `edit_project <project_id>`
- `edit_folder <folder_id>`

Examples:

```bash
uv run caption list_projects
uv run caption --output-file outputs/projects.tsv list_projects
uv run caption --output-file outputs/folders.tsv list_folders
uv run caption create_project "My Project" --description "First draft"
uv run caption edit_folder folder-uuid --name "Renamed" --clear-parent
```

#### Transcript export

- `dl_transcript <transcript_id>`

By default timestamps are stripped. Pass `--timestamp` to keep them.

```bash
uv run caption dl_transcript transcript-uuid
uv run caption dl_transcript transcript-uuid --timestamp
uv run caption --output-file transcripts/transcript-uuid.md dl_transcript transcript-uuid
uv run caption --output json --output-file transcripts/transcript-uuid.json dl_transcript transcript-uuid
```

#### Live caption tail

- `tail [transcript_id]`: stream finalized caption rows from the events gateway
- `tail --link URL_OR_TOKEN`: stream a shared project as a guest

Examples:

```bash
uv run caption tail transcript-uuid --max-events 5
uv run caption tail --idle-timeout 300
uv run caption tail --link https://app.caption.fyi/shared/SHARE_TOKEN --max-events 10
uv run caption tail transcript-uuid --link SHARE_TOKEN --duration 60
```

Output is fixed line text:

```text
microphone-1: We should ship on Friday.
```

Behavior:

- without `transcript_id`, authenticated mode tails the transcript attached to the most recently updated project
- with `--link` and no `transcript_id`, the CLI resolves the project share link and tails the most recently updated transcript in that shared project
- `--link` accepts either `https://app.caption.fyi/shared/<token>` or the bare 16-character token
- link mode requires `CAPTION_API_URL`, but it does not require or send `CLERK_API_KEY`
- folder share links are not supported yet
- stdout is reserved for caption rows; reconnect and resolution notes go to stderr

#### Speakers

- `assign_speakers`: assign a speaker to transcript captions by channel and optional diarization index
- `list_speakers <transcript_id>`: summarize `(channel, index, speakerId)` caption groups for a transcript
- `rename_speaker <project_id> <speaker_id>`: rename a custom speaker across a project

A typical flow: inspect a transcript with `list_speakers` to see which `(channel, index)` groups exist, then label each group with `assign_speakers`, and fix mistakes later with `rename_speaker`.

```bash
uv run caption list_speakers transcript-uuid
uv run caption assign_speakers --transcript-id transcript-uuid --channel microphone --index 1 --name "Alice"
uv run caption assign_speakers --project-id project-uuid --channel loopback --name "Opposing Counsel"
uv run caption rename_speaker project-uuid speaker-uuid --name "Alice Smith"
```

`assign_speakers` targets exactly one of `--transcript-id` or `--project-id`, and identifies the speaker with exactly one of `--name` or `--speaker-id`:

- `--channel` accepts `0|microphone`, `1|loopback`, or `2|external`
- `--index` filters to one diarization index; omit it to update every index in the channel
- `--name` reuses or creates a custom speaker scoped to the transcript's project (preferred)
- `--speaker-id` assigns an existing speaker UUID; the API does not verify it belongs to the transcript's project, so only pass IDs obtained from the same project
- `--project-id` fans out over every transcript in the project and aggregates per-transcript results; diarization indexes are not stable across transcripts, so project-wide assignment usually makes sense without `--index`
- `--dry-run` prints the request that would be sent without sending it (also supported by `rename_speaker`)

`list_speakers` shows speaker IDs only — caption payloads do not include speaker names. `rename_speaker` only works on custom speakers; user-backed speakers are rejected by the API.

## Development

Run tests with:

```bash
uv run pytest
```
