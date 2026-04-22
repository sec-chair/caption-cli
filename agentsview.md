# Agentsview Implementation Plan For `caption-cli`

## Summary
- Do not build a separate package. Implement this inside the existing `caption_cli` package and keep the existing `caption` entrypoint.
- Do not add dependencies to `pyproject.toml`. The repo already has `httpx`; use stdlib for SQLite/TOML/temp files and reuse the existing HTTP client instead of adding `requests`, SQLAlchemy, pydantic, or a second CLI stack.
- Keep v1 as two flat commands that match the current CLI style:
  - `caption agentsview_build`
  - `caption agentsview_send`
- Reuse the repo’s existing patterns:
  - `argparse` command registration in `caption_cli/cli.py`
  - command handlers in `caption_cli/commands.py`
  - shared errors via `caption_cli.core.CliError`
  - JSON output via `caption_cli.core.emit_output`

## Why The Original Draft Was Wrong For This Repo
- A standalone `src/...` package is unnecessary duplication. This repo already ships a CLI package and a console script.
- Forcing stdlib-only HTTP makes no sense here. `httpx` is already installed and already handled in `caption_cli.main`.
- NDJSON as the primary stdout format does not fit the current output model. The existing CLI already emits JSON well; special-casing NDJSON is extra surface area for little gain.
- Tests should not depend on a copied real `sessions.db` fixture unless there is no alternative. Generate a temporary SQLite DB in tests instead. That keeps the repo smaller and avoids leaking production-shaped data into fixtures.

## Required Repo Changes
- Extend `CommandSpec` so commands can opt out of Caption API env validation.
  - Current bug: `caption_cli.cli.run()` always calls `_require_api_url(config)`.
  - That would make `agentsview_*` unusable unless `CAPTION_API_URL` is set, even though these commands do not need it.
- Keep `needs_meili` for existing search behavior.
- Add a new flag on `CommandSpec`, for example `needs_api: bool = True`.
  - Existing commands keep the default.
  - `agentsview_build` and `agentsview_send` set `needs_api=False` and `needs_meili=False`.

## Files To Change
- Update [caption_cli/cli.py](/Users/alin/code/caption/caption-cli/caption_cli/cli.py)
  - register `agentsview_build` and `agentsview_send`
  - add shared argument wiring for selectors and share config overrides
  - stop requiring Caption API env vars for commands that do not need them
- Update [caption_cli/commands.py](/Users/alin/code/caption/caption-cli/caption_cli/commands.py)
  - add thin handlers that call into the agentsview module
- Add `caption_cli/agentsview.py`
  - SQLite snapshotting
  - config loading
  - selectors / query builder
  - payload shaping
  - HTTP send
- Add [tests/test_agentsview.py](/Users/alin/code/caption/caption-cli/tests/test_agentsview.py)
  - parser coverage
  - SQLite payload-shaping tests
  - HTTP request tests

## Command Surface
- `caption agentsview_build [selectors...] [--out-dir DIR]`
- `caption agentsview_send [selectors...] [auth options...]`

Shared selectors:
- `--db-path PATH`
- `--session-id SESSION_ID` repeatable
- `--project PROJECT`
- `--agent AGENT`
- `--started-after ISO8601`
- `--started-before ISO8601`
- `--limit N`

Shared auth overrides:
- `--clerk-api-key TOKEN`
- `--org-id ORG_ID`

Build-only options:
- `--out-dir DIR`

Output rules:
- `agentsview_build` defaults to JSON output.
  - If `--out-dir` is omitted, print a JSON array of payloads.
  - If `--out-dir` is provided, write one file per share and return a JSON summary.
- `agentsview_send` returns a JSON summary such as sent count, share IDs, and any failures.
- Do not add a new global output format just for NDJSON in v1. If someone actually needs NDJSON later, add it after there is a real consumer.

## Config Loading
- Do not read share settings from `config.toml`.
- Hard-code the send target URL to `https://history.caption.fyi`.
- Resolve auth as:
  - explicit CLI flag
  - environment variable loaded from `.env` or the shell
  - otherwise fail with `CliError`
- Environment variable names:
  - `CLERK_API_KEY`
  - `ORGANIZATION_ID`
- `clerk_api_key` is not a special share token. It is the normal authenticated API credential used on `/api/*`.

## Auth Contract
- `PUT /api/v1/shares/{shareId}` is a normal authenticated `/api/*` route.
- For API-key auth, send:
  - `Authorization: Bearer <clerk_api_key>`
  - `X-Agentsview-Org: <org_id>`
- If auth is missing or invalid, expect `401 Unauthorized` as plain text before the handler runs.
- If auth succeeds but there is no active org, expect `403 {"error":"no active organization — pick one to continue"}`.
- If the API-key user is not a member of `X-Agentsview-Org`, expect plain-text `403 Forbidden`.
- `Content-Type: application/json` is still worth sending, but the handler does not enforce it.
- `User-Agent: agentsview` is optional and only useful for observability.

## Database Access
- Use stdlib `sqlite3`.
- Open the source DB read-only:

```python
sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
```

- Immediately copy into a temp snapshot with `Connection.backup()` and query the snapshot.
- Use `sqlite3.Row` row factory.
- Do not hard-code a requirement that `sessions.db-wal` must exist.
  - That assumption is sloppy. WAL sidecars only matter when the DB is actually using WAL and the sidecar exists.
  - The real rule is simpler: open the real DB read-only through SQLite, back it up immediately, and do not support users hand-copying only the main DB file out of band.

## Data Hydration Rules
- Reconstruct sessions from the same logical ordering the Go sender uses:
  - load sessions from `sessions`
  - load messages ordered by `ordinal ASC`
  - load `tool_calls` ordered by `tool_calls.id`
  - load `tool_result_events` ordered by `tool_call_message_ordinal, call_index, event_index`
- attach each event to `message.tool_calls[call_index]`
- Do not attach tool result events by `tool_use_id`. The draft was right about that part: positional `call_index` is the rule that matters here.

## Query Shape
- Keep the SQL explicit. This is not an ORM problem.

```python
SESSION_SQL = """
SELECT
  id, project, machine, agent,
  first_message, display_name, started_at, ended_at,
  message_count, user_message_count,
  parent_session_id, relationship_type,
  total_output_tokens, peak_context_tokens
FROM sessions
WHERE deleted_at IS NULL
"""
```

```python
MESSAGE_SQL = """
SELECT
  id, session_id, ordinal, role, content, thinking_text,
  timestamp, has_thinking, has_tool_use, content_length,
  is_system, model, token_usage, context_tokens, output_tokens,
  has_context_tokens, has_output_tokens,
  claude_message_id, claude_request_id,
  source_type, source_subtype, source_uuid,
  source_parent_uuid, is_sidechain, is_compact_boundary
FROM messages
WHERE session_id = ?
ORDER BY ordinal ASC
"""
```

```python
TOOL_CALL_SQL = """
SELECT
  id, message_id, session_id, tool_name, category,
  tool_use_id, input_json, skill_name,
  result_content_length, result_content, subagent_session_id
FROM tool_calls
WHERE message_id IN ({placeholders})
ORDER BY id
"""
```

```python
TOOL_EVENT_SQL = """
SELECT
  tool_call_message_ordinal, call_index,
  tool_use_id, agent_id, subagent_session_id,
  source, status, content, content_length,
  timestamp, event_index
FROM tool_result_events
WHERE session_id = ? AND tool_call_message_ordinal IN ({placeholders})
ORDER BY tool_call_message_ordinal, call_index, event_index
"""
```

Selector application:
- build `SESSION_SQL` dynamically with additional `AND ...` predicates for `session_id`, `project`, `agent`, `started_after`, `started_before`
- append `ORDER BY started_at DESC, id`
- append `LIMIT ?` when requested
- use parameter binding everywhere

## Payload Rules
- Match the actual request contract, not the stale docs:
  - URL: `PUT {share.url}/api/v1/shares/{share_id}`
  - `share_id` in the body is optional, but if present it must exactly equal the path value
  - body keys are:
    - `share_id` optional
    - `session` required
    - `messages` required if you want to preserve transcript data

- Request semantics that matter:
  - treat `share_id` as globally unique across the deployment, not just within one org
  - build it as the raw local session ID
  - `session.project` is effectively required even though the server currently fails with `500 {"error":"internal error"}` instead of a clean `400`
  - `messages` is a full replacement set; omitting it or sending `[]` deletes previously stored messages for that share
  - `session.id` can still carry the original local session ID for debugging, but the server ignores it for persistence
  - the stored session ID is always the URL `share_id`
  - local file metadata is not part of the share contract and should not be sent

- `session` contains only:
  - `id`, `project`, `agent`, `first_message`, `display_name`, `started_at`, `ended_at`, `message_count`, `user_message_count`, `parent_session_id`, `relationship_type`, `total_output_tokens`, `peak_context_tokens`
- These session fields must serialize as `null` when absent:
    - `first_message`
    - `display_name`
    - `started_at`
    - `ended_at`
    - `parent_session_id`
- `messages[*].token_usage` is stored as text in SQLite but must serialize as parsed JSON
- Unknown JSON fields are ignored by the server, but the client should not rely on that sloppiness
- Session counters are trusted input; the server does not recompute them from messages
- Message `id` is accepted in JSON but ignored on insert
- `tool_calls[].call_index` is not part of the JSON contract; ordering comes from array order
- `result_events[].event_index` is likewise ignored on ingest; ordering comes from the array
- Invalid timestamps are silently stored as `NULL`, so the client should validate timestamps before sending if that distinction matters

## Timestamp Contract
- Accepted timestamp formats are:
  - RFC3339Nano
  - `2006-01-02T15:04:05.000Z`
  - `2006-01-02T15:04:05Z`
  - `2006-01-02 15:04:05`
- This applies to:
  - `session.started_at`
  - `session.ended_at`
  - `messages[*].timestamp`
  - `messages[*].tool_calls[*].result_events[*].timestamp`
- Invalid timestamp strings are not rejected. They are stored as `NULL`.

## Serialization Strategy
- Do not use a generic “drop falsy keys” helper. That would be wrong for `null` session fields and wrong for boolean flags that must remain `false`.
- Build JSON dicts explicitly.

```python
def encode_message(row: sqlite3.Row, tool_calls: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {
        "id": row["id"],
        "session_id": row["session_id"],
        "ordinal": row["ordinal"],
        "role": row["role"] or "",
        "content": row["content"] or "",
        "thinking_text": row["thinking_text"] or "",
        "timestamp": row["timestamp"] or "",
        "has_thinking": bool(row["has_thinking"]),
        "has_tool_use": bool(row["has_tool_use"]),
        "content_length": int(row["content_length"] or 0),
        "model": row["model"] or "",
        "context_tokens": int(row["context_tokens"] or 0),
        "output_tokens": int(row["output_tokens"] or 0),
        "has_context_tokens": bool(row["has_context_tokens"]),
        "has_output_tokens": bool(row["has_output_tokens"]),
        "is_system": bool(row["is_system"]),
    }
    if row["token_usage"]:
        out["token_usage"] = json.loads(row["token_usage"])
    if row["claude_message_id"]:
        out["claude_message_id"] = row["claude_message_id"]
    if row["claude_request_id"]:
        out["claude_request_id"] = row["claude_request_id"]
    if row["source_type"]:
        out["source_type"] = row["source_type"]
    if row["source_subtype"]:
        out["source_subtype"] = row["source_subtype"]
    if row["source_uuid"]:
        out["source_uuid"] = row["source_uuid"]
    if row["source_parent_uuid"]:
        out["source_parent_uuid"] = row["source_parent_uuid"]
    if row["is_sidechain"]:
        out["is_sidechain"] = True
    if row["is_compact_boundary"]:
        out["is_compact_boundary"] = True
    if tool_calls:
        out["tool_calls"] = tool_calls
    return out
```

```python
def encode_tool_call(row: sqlite3.Row, result_events: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {
        "tool_name": row["tool_name"],
        "category": row["category"],
    }
    if row["tool_use_id"]:
        out["tool_use_id"] = row["tool_use_id"]
    if row["input_json"]:
        out["input_json"] = row["input_json"]
    if row["skill_name"]:
        out["skill_name"] = row["skill_name"]
    if row["result_content_length"]:
        out["result_content_length"] = int(row["result_content_length"])
    if row["result_content"]:
        out["result_content"] = row["result_content"]
    if row["subagent_session_id"]:
        out["subagent_session_id"] = row["subagent_session_id"]
    if result_events:
        out["result_events"] = result_events
    return out
```

```python
def build_share_payload(session_row: sqlite3.Row, messages: list[dict[str, object]]) -> dict[str, object]:
    share_id = str(session_row["id"])
    return {
        "share_id": share_id,
        "session": {
            "id": session_row["id"],
            "project": session_row["project"],
            "agent": session_row["agent"],
            "first_message": session_row["first_message"],
            "display_name": session_row["display_name"],
            "started_at": session_row["started_at"],
            "ended_at": session_row["ended_at"],
            "message_count": int(session_row["message_count"] or 0),
            "user_message_count": int(session_row["user_message_count"] or 0),
            "parent_session_id": session_row["parent_session_id"],
            "relationship_type": session_row["relationship_type"] or "",
            "total_output_tokens": int(session_row["total_output_tokens"] or 0),
            "peak_context_tokens": int(session_row["peak_context_tokens"] or 0),
        },
        "messages": messages,
    }
```

## HTTP Send
- Use existing `httpx`, not `urllib.request`.
- Reason: no new dependency, consistent timeout/error handling, and `caption_cli.main` already normalizes `httpx.HTTPError`.

```python
def send_payload(base_url: str, clerk_api_key: str, org_id: str, share_id: str, payload: dict[str, object]) -> None:
    url = f"{base_url.rstrip('/')}/api/v1/shares/{share_id}"
    headers = {
        "Authorization": f"Bearer {clerk_api_key}",
        "X-Agentsview-Org": org_id,
        "Content-Type": "application/json",
        "User-Agent": "agentsview",
    }
    with httpx.Client(timeout=30.0) as client:
        response = client.put(url, headers=headers, json=payload)
    if response.status_code == 204:
        return
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise CliError(f"Share server error ({response.status_code}): {detail}")
    raise CliError(f"Unexpected share server response ({response.status_code})")
```

Notes:
- Use `json=payload` unless byte-for-byte parity testing proves the server depends on custom separators. Don’t cargo-cult serialization tweaks without evidence.
- Keep `share_id` in the body equal to the path even though the handler treats it as optional. Optional here is not a reason to create two sources of truth.
- Expect full-upsert behavior: the latest snapshot wins.
- The endpoint is not fully atomic end-to-end. Session metadata upsert happens before message replacement, so a failed message write can still leave updated session metadata behind.

## Response Contract
- Success: `204 No Content`
- Handler validation errors return JSON:
  - `400 {"error":"missing share_id"}`
  - `400 {"error":"invalid JSON body"}`
  - `400 {"error":"share_id in body does not match URL"}`
- Middleware/auth errors happen before the handler:
  - `401 Unauthorized` plain text for missing or invalid auth
  - `403 Forbidden` plain text for org membership failures under API-key auth
  - `403 {"error":"no active organization — pick one to continue"}` when auth succeeds but no org is active
- Storage failures return `500 {"error":"internal error"}`
- Request timeout returns `503 {"error":"request timed out"}`

## Suggested Internal API
- Keep the implementation narrow:
  - `load_share_settings(...) -> ShareSettings`
  - `snapshot_db(...) -> sqlite3.Connection`
  - `select_sessions(...) -> list[sqlite3.Row]`
  - `load_messages(...) -> list[sqlite3.Row]`
  - `load_tool_calls(...) -> dict[int, list[sqlite3.Row]]`
  - `load_tool_events(...) -> dict[tuple[int, int], list[sqlite3.Row]]`
  - `build_payload_for_session(...) -> dict[str, object]`
  - `build_payloads(...) -> list[dict[str, object]]`
  - `write_payloads(...) -> list[Path]`
  - `send_payloads(...) -> list[dict[str, object]]`

Do not split this into four tiny modules on day one. One focused `caption_cli/agentsview.py` module is enough until the code proves otherwise.

## Test Plan
- Parser / command registration:
  - `agentsview_build` and `agentsview_send` parse correctly
  - `agentsview_*` commands do not require `CAPTION_API_URL` or `CAPTION_MEILI_URL`
  - `--limit < 1` fails if that validation is shared with existing commands

- SQLite payload-shaping tests:
  - create a temporary SQLite DB inside the test
  - create only the tables/rows needed for each scenario
  - avoid relying on a checked-in production DB snapshot unless query setup becomes unmanageable

- Payload behavior:
  - session with no tool calls omits `tool_calls`
  - `token_usage` text becomes a JSON object, not a string
  - multiple tool calls keep `tool_calls.id` ordering
  - result events attach by `call_index`
  - empty `result_events` is omitted
  - nullable session fields serialize as `null`
  - `session.id` is preserved in the JSON body but ignored by persistence
  - `session.project` blank or whitespace fails at send time
  - empty or missing `messages` is treated as destructive full replacement
  - zero `result_content_length` remains absent/null, while zero event `content_length` is backfilled by the server

- HTTP tests:
  - verify `PUT`
  - verify path `/api/v1/shares/{session_id}`
  - verify bearer auth header
  - verify `X-Agentsview-Org`
  - verify `Content-Type: application/json` is sent even though the server does not enforce it
  - verify `User-Agent: agentsview` is sent if we decide to keep it
  - verify success expects `204 No Content`
  - verify 4xx/5xx produces `CliError`
  - verify `401` and both flavors of `403` produce useful error text

- Snapshot test:
  - use a temp DB in WAL mode
  - confirm snapshot reads current rows through SQLite backup

## Assumptions
- Python baseline is the repo baseline, `>=3.13`, so `tomllib` is available and no fallback dependency is needed.
- v1 supports batch selection through repeated `--session-id` plus filters.
- `agentsview_build` is the safe default inspection path; `agentsview_send` performs the network mutation.
- No new dependency should be installed for this feature unless a real implementation blocker appears. None is obvious from the current repo.
