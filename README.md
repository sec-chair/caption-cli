# caption-cli

This repo has one CLI entrypoint and one agentsview support module. Treating them as separate tools matters:

- [`caption.py`](/Users/alin/code/caption/caption-cli/caption.py) is the executable entrypoint.
- [`caption_cli/agentsview.py`](/Users/alin/code/caption/caption-cli/caption_cli/agentsview.py) is not a standalone script. It powers the `agentsview_build` and `agentsview_send` subcommands exposed through `caption.py`.

## Setup

Use `uv`. Anything else is the wrong tool for this repo.

```bash
uv sync
```

By default the CLI loads environment variables from `<repo-root>/.env`. Override that with `--env-file` if needed.

## `caption.py`

Run either form:

```bash
uv run caption --help
uv run caption.py --help
```

`caption.py` is a thin wrapper that calls [`caption_cli.main:main`](/Users/alin/code/caption/caption-cli/caption_cli/main.py). The actual command registration lives in [`caption_cli/cli.py`](/Users/alin/code/caption/caption-cli/caption_cli/cli.py), and the API/Meilisearch behavior lives in [`caption_cli/commands.py`](/Users/alin/code/caption/caption-cli/caption_cli/commands.py) and [`caption_cli/core.py`](/Users/alin/code/caption/caption-cli/caption_cli/core.py).

### Environment

These variables are used by the main Caption commands:

- `CAPTION_API_URL`: required for Caption API operations
- `CLERK_API_KEY`: required for authenticated Caption API operations
- `CAPTION_MEILI_URL`: required for `token` and `search`

### Global flags

- `--env-file`: dotenv file to load before resolving env-based defaults
- `--cache-path`: location of the cached Meilisearch token JSON file
- `--output {json,table,md}`: output formatter

### Commands

#### Search and auth

- `token`: fetch `/search/token` and cache it locally
- `search <query>`: search one Meilisearch index

Examples:

```bash
uv run caption token
uv run caption search "roadmap" --index projects_v1 --limit 10
```

Supported search examples from help:

- `transcript_captions_v1`
- `workspace_folders_v1`
- `projects_v1`
- `transcript_sessions_v1`

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
uv run caption create_project "My Project" --description "First draft"
uv run caption edit_folder folder-uuid --name "Renamed" --clear-parent
```

#### Transcript export

- `dl_transcript <transcript_id>`

By default timestamps are stripped. Pass `--timestamp` to keep them.

```bash
uv run caption dl_transcript transcript-uuid
uv run caption dl_transcript transcript-uuid --timestamp
```

## `caption_cli/agentsview.py`

This module handles exporting and publishing agentsview session data from a local SQLite database. You do not run this file directly. You use it through:

- `uv run caption agentsview_build ...`
- `uv run caption agentsview_send ...`

### What it does

- resolves the default data directory from `AGENT_VIEWER_DATA_DIR` or `~/.agentsview`
- reads the local `sessions.db`
- snapshots the SQLite database into memory before querying it
- selects sessions with optional filters
- reconstructs messages, tool calls, and tool result events
- builds share payloads
- optionally writes payload JSON files
- optionally sends payloads to a share server

### Defaults

- default DB path: `~/.agentsview/sessions.db`
- default config path: `~/.agentsview/config.toml`

If `AGENT_VIEWER_DATA_DIR` is set, both defaults move under that directory.

### Shared flags

Both agentsview commands support:

- `--db-path`
- `--config-path`
- `--session-id` (repeatable)
- `--project`
- `--agent`
- `--started-after`
- `--started-before`
- `--limit`
- `--share-url`
- `--clerk-api-key`
- `--org-id`
- `--publisher`

### `agentsview_build`

Build share payloads from the local SQLite database.

```bash
uv run caption agentsview_build --project library --limit 2
uv run caption agentsview_build --project library --limit 2 --out-dir ./shares
```

Behavior:

- without `--out-dir`, prints a JSON array of payloads
- with `--out-dir`, writes one JSON file per share ID and returns a JSON summary

### `agentsview_send`

Build payloads and `PUT` them to the share server.

```bash
uv run caption agentsview_send --session-id s1 --share-url https://library.caption.fyi --org-id org_123 --publisher local
```

This command does not require `CAPTION_API_URL` or `CAPTION_MEILI_URL`.

### Config file

`agentsview_send` and `agentsview_build` can read share settings from TOML:

```toml
[share]
url = "https://library.caption.fyi"
clerk_api_key = "token"
org = "org_123"
publisher = "local"
```

Resolution order is:

1. CLI flag
2. `[share]` value from `--config-path`
3. failure with `CliError` if a required send setting is still missing

The code also accepts fallback keys:

- `token` as a fallback for `clerk_api_key`
- `org_id` as a fallback for `org`

### Share payload shape

Each built payload includes:

- `share_id`
- `session`
- `messages`

`share_id` is built as:

```text
{publisher}:{session_id}
```

That is deliberate. Without the publisher prefix, collisions are predictable.

### Development

Run tests with:

```bash
uv run pytest
```
