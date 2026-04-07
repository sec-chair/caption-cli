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

### Environment

These variables are used by the main Caption commands:

- `CAPTION_API_URL`: required for Caption API operations
- `CLERK_API_KEY`: required for authenticated Caption API operations
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

#### Hosted Markdown documents

These commands use `https://history.caption.fyi`, like `sync`, and do not require `CAPTION_API_URL` or `CAPTION_MEILI_URL`.

- `create_md <markdown_file>`
- `list_md`
- `get_md <id>`
- `edit_md <id> <markdown_file>`

Examples:

```bash
uv run caption create_md README.md --project-name "caption-cli endpoint probe" --title "CLI README"
uv run caption list_md --limit 50 --sort recent
uv run caption get_md markdown-document-uuid
uv run caption edit_md markdown-document-uuid README.md --project-id project-uuid --title "Updated"
```

Flags:

- `create_md`: `--project-id`, `--project-name`, `--title`, `--clerk-api-key`, `--org-id`
- `list_md`: `--project`, `--exclude-project`, `--tag`, `--created-by`, `--sort`, `--cursor`, `--limit`, `--clerk-api-key`, `--org-id`
- `get_md`: `--clerk-api-key`, `--org-id`
- `edit_md`: `--project-id`, `--title`, `--clerk-api-key`, `--org-id`

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
uv run caption sync --session-id '*' --org-id org_123
```

Flags:

- `--db-path`
- `--session-id`
- `--test`
- `--clerk-api-key`
- `--org-id`

Behavior:

- `--session-id` is required
- matching is case-insensitive substring match against `sessions.id`
- `--session-id '*'` selects all non-deleted sessions
- `--test` prints the built JSON payloads and does not require send auth
- without `--test`, the command sends payloads to `https://history.caption.fyi`

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


<!-- endpoint probe retry 2 update -->

