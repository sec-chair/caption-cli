# caption-cli

This repo has one CLI entrypoint and one agentsview support module. Treating them as separate tools matters:

- [`caption.py`](/Users/alin/code/caption/caption-cli/caption.py) is the executable entrypoint.
- [`caption_cli/agentsview.py`](/Users/alin/code/caption/caption-cli/caption_cli/agentsview.py) is not a standalone script. It powers the `sync` subcommand exposed through `caption.py`.

## Setup

Use `uv`. Anything else is the wrong tool for this repo.

```bash
uv sync
```

By default the CLI loads environment variables from `$PWD/.env`. Override that with `--env-file` if needed.

## `caption.py`

Run either form:

```bash
uv run caption --help
uv run caption.py --help
```

`caption.py` is a thin wrapper that calls [`caption_cli.main:main`](/Users/alin/code/caption/caption-cli/caption_cli/main.py). The actual command registration lives in [`caption_cli/cli.py`](/Users/alin/code/caption/caption-cli/caption_cli/cli.py), and the API/Meilisearch behavior lives in [`caption_cli/commands.py`](/Users/alin/code/caption/caption-cli/caption_cli/commands.py) and [`caption_cli/core.py`](/Users/alin/code/caption/caption-cli/caption_cli/core.py).

### Discovery (start here if you are an agent)

- `capabilities`: machine-readable CLI contract — commands, exit codes, env vars (JSON, offline)
- `robot-docs guide`: paste-ready agent handbook (Markdown, offline)
- `doctor [--strict]`: probe which Caption features are reachable; failed probes print reasons to stderr, `--strict` exits non-zero

```bash
uv run caption capabilities
uv run caption robot-docs guide
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

#### Hosted Markdown documents

These commands use `https://history.caption.fyi`, like `sync`, and do not require `CAPTION_API_URL` or `CAPTION_MEILI_URL`.

- `list_matters`
- `create_md <markdown_file>`
- `list_md`
- `get_md <id>`

Examples:

```bash
uv run caption list_matters --include-one-shot
uv run caption create_md README.md --project-name "caption-cli endpoint probe" --title "CLI README"
uv run caption list_md --limit 50 --sort recent
uv run caption get_md markdown-document-uuid
uv run caption --output-file docs/markdown-document-uuid.md get_md markdown-document-uuid
```

Flags:

- `list_matters`: `--include-one-shot`, `--clerk-api-key`, `--org-id`
- `create_md`: `--project-id`, `--project-name`, `--title`, `--clerk-api-key`, `--org-id`; `--title` defaults to the filename, and output truncates `raw_markdown` and `plain_text` to 100 characters
- `list_md`: `--project`, `--exclude-project`, `--tag`, `--created-by`, `--sort`, `--cursor`, `--limit`, `--clerk-api-key`, `--org-id`
- `get_md`: `--cache-dir`, `--clerk-api-key`, `--org-id`; saves `raw_markdown` to `caption_cache/md/<title>.md` by default instead of printing the full API response

## `caption_cli/agentsview.py`

This module handles exporting and publishing agentsview session data from a local SQLite database. You do not run this file directly. You use it through:

- `uv run caption sync ...`

### What it does

- resolves the default data directory from `AGENT_VIEWER_DATA_DIR` or `~/.agentsview`
- reads the local `sessions.db`
- snapshots the SQLite database into memory before querying it
- selects sessions by case-insensitive partial match on the raw session ID
- reconstructs messages, tool calls, and tool result events
- builds share payloads
- either prints the payload JSON or sends payloads to a share server

### Defaults

- default DB path: `~/.agentsview/sessions.db`

If `AGENT_VIEWER_DATA_DIR` is set, the default DB path moves under that directory.

### `sync`

Build share payloads from the local SQLite database and either print them or send them.

```bash
uv run caption sync --session-id s1 --test
uv run caption sync --session-id s1 --org-id org_123
uv run caption sync --session-id s1 --project-name "Matter Override" --org-id org_123
uv run caption sync --session-id '*' --org-id org_123
```

Flags:

- `--db-path`
- `--session-id`
- `--project-name`
- `--test`
- `--clerk-api-key`
- `--org-id`

Behavior:

- `--session-id` is required
- matching is case-insensitive substring match against `sessions.id`
- `--session-id '*'` selects all non-deleted sessions
- `--project-name` overrides the built payload's `session.project` for every matched session
- `--test` prints the built JSON payloads and does not require send auth
- without `--test`, the command sends payloads to `https://history.caption.fyi` over a single reused HTTP connection
- if any session fails to send, the command exits `4` (upstream failure) and the error message embeds the full sent/failures report

This command does not require `CAPTION_API_URL` or `CAPTION_MEILI_URL`.

Auth resolution:

1. CLI flag
2. environment variable from `.env` or the shell
3. failure with `CliError` if a required send setting is still missing

Relevant auth variables:

```dotenv
CLERK_API_KEY=token
ORGANIZATION_ID=org_123
```

`sync` always sends to `https://history.caption.fyi` unless `--test` is used.

### Share payload shape

Each built payload includes:

- `share_id`
- `session`
- `messages`

`share_id` is built as:

```text
{session_id}
```

### Development

Run tests with:

```bash
uv run pytest
```
