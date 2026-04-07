from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from caption_cli.core import CliError

AGENTSVIEW_BASE_URL = "https://history.caption.fyi"
AGENTSVIEW_USER_AGENT = "caption-cli"
LIST_MD_OUTPUT_FIELDS = ("id", "project", "title", "plain_text_preview", "tags")
LIST_MATTERS_OUTPUT_FIELDS = ("id", "name", "full_name")
CREATE_MD_OUTPUT_TRUNCATE_FIELDS = ("raw_markdown", "plain_text")
CREATE_MD_OUTPUT_TRUNCATE_LENGTH = 100

SESSION_SQL = """
SELECT id, project, machine, agent, first_message, display_name, started_at, ended_at,
  message_count, user_message_count, parent_session_id, relationship_type,
  total_output_tokens, peak_context_tokens
FROM sessions
WHERE deleted_at IS NULL
"""

MESSAGE_SQL = """
SELECT id, session_id, ordinal, role, content, thinking_text, timestamp, has_thinking,
  has_tool_use, content_length, is_system, model, token_usage, context_tokens, output_tokens,
  has_context_tokens, has_output_tokens, claude_message_id, claude_request_id,
  source_type, source_subtype, source_uuid, source_parent_uuid, is_sidechain, is_compact_boundary
FROM messages
WHERE session_id = ?
ORDER BY ordinal ASC
"""

TOOL_CALL_SQL = """
SELECT id, message_id, session_id, tool_name, category, tool_use_id, input_json,
  skill_name, result_content_length, result_content, subagent_session_id
FROM tool_calls
WHERE message_id IN ({placeholders})
ORDER BY id
"""

TOOL_EVENT_SQL = """
SELECT tool_call_message_ordinal, call_index, tool_use_id, agent_id, subagent_session_id,
  source, status, content, content_length, timestamp, event_index
FROM tool_result_events
WHERE session_id = ? AND tool_call_message_ordinal IN ({placeholders})
ORDER BY tool_call_message_ordinal, call_index, event_index
"""


def default_data_dir() -> Path:
    override = os.getenv("AGENT_VIEWER_DATA_DIR")
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return Path.home() / ".agentsview"


def default_db_path() -> Path:
    return default_data_dir() / "sessions.db"


def _clean_optional(value: str | None, label: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        raise CliError(f"{label} cannot be empty")
    return cleaned


def _require_value(value: str | None, label: str) -> str:
    if value is None or not value.strip():
        raise CliError(f"Missing {label}")
    return value.strip()


def _agentsview_auth(args: argparse.Namespace) -> tuple[str, str]:
    return (
        _require_value(
            _clean_optional(args.clerk_api_key, "--clerk-api-key") or os.getenv("CLERK_API_KEY"),
            "Clerk API key (--clerk-api-key or CLERK_API_KEY)",
        ),
        _require_value(
            _clean_optional(args.org_id, "--org-id") or os.getenv("ORGANIZATION_ID"),
            "org id (--org-id or ORGANIZATION_ID)",
        ),
    )


def _agentsview_request(
    method: str,
    path: str,
    *,
    auth: tuple[str, str],
    params: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
    expected_statuses: set[int],
    transport: httpx.BaseTransport | None = None,
    base_url: str = AGENTSVIEW_BASE_URL,
) -> Mapping[str, Any] | None:
    clerk_api_key, org_id = auth
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {clerk_api_key}",
        "X-Agentsview-Org": org_id,
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": AGENTSVIEW_USER_AGENT,
    }
    with httpx.Client(timeout=30.0, transport=transport) as client:
        response = client.request(method, url, headers=headers, params=params, json=json_body)

    if response.status_code not in expected_statuses:
        detail = response.text.strip() or response.reason_phrase
        raise CliError(f"Failed {method.upper()} {path} ({response.status_code}): {detail}")
    if expected_statuses == {204}:
        return None

    content_type = response.headers.get("content-type", "")
    if "json" not in content_type.lower():
        excerpt = response.text.strip().replace("\n", " ")
        if len(excerpt) > 240:
            excerpt = f"{excerpt[:237]}..."
        raise CliError(
            f"{method.upper()} {path} returned non-JSON response "
            f"({response.status_code}, {content_type or 'no content-type'}): {excerpt}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise CliError(f"{method.upper()} {path} returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise CliError(f"{method.upper()} {path} returned non-object JSON")
    return payload


def _agentsview_json(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
    payload = _agentsview_request(*args, **kwargs)
    assert payload is not None
    return payload


def snapshot_db(db_path: Path) -> sqlite3.Connection:
    resolved_db_path = db_path.expanduser()
    if not resolved_db_path.exists():
        raise CliError(f"Database not found: {resolved_db_path}")

    source_uri = f"file:{resolved_db_path}?mode=ro"
    try:
        source = sqlite3.connect(source_uri, uri=True)
    except sqlite3.Error as exc:
        raise CliError(f"Failed opening database {resolved_db_path}: {exc}") from exc

    snapshot = sqlite3.connect(":memory:")
    snapshot.row_factory = sqlite3.Row
    try:
        source.backup(snapshot)
    except sqlite3.Error as exc:
        snapshot.close()
        raise CliError(f"Failed snapshotting database {resolved_db_path}: {exc}") from exc
    finally:
        source.close()

    return snapshot


def _placeholders(values: Iterable[object]) -> str:
    count = sum(1 for _ in values)
    if count == 0:
        raise ValueError("placeholders require at least one value")
    return ",".join("?" for _ in range(count))


def _fetchall(conn: sqlite3.Connection, query: str, params: Iterable[Any], error: str) -> list[sqlite3.Row]:
    try:
        return list(conn.execute(query, tuple(params)).fetchall())
    except sqlite3.Error as exc:
        raise CliError(f"{error}: {exc}") from exc


def _copy_truthy(out: dict[str, object], row: sqlite3.Row, *keys: str) -> None:
    out.update({key: row[key] for key in keys if row[key]})


def _copy_true(out: dict[str, object], row: sqlite3.Row, *keys: str) -> None:
    out.update({key: True for key in keys if row[key]})


def select_sessions(
    conn: sqlite3.Connection,
    *,
    session_id_query: str,
) -> list[sqlite3.Row]:
    params: list[Any] = []
    query = SESSION_SQL

    cleaned_session_id_query = _require_value(
        _clean_optional(session_id_query, "--session-id"),
        "--session-id",
    )
    if cleaned_session_id_query != "*":
        query += " AND id LIKE ? ESCAPE '\\' COLLATE NOCASE"
        params.append(f"%{_escape_like(cleaned_session_id_query)}%")
    query += " ORDER BY started_at DESC, id"

    return _fetchall(conn, query, params, "Failed selecting sessions")


def load_messages(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    return _fetchall(conn, MESSAGE_SQL, (session_id,), f"Failed loading messages for session {session_id}")


def load_tool_calls(conn: sqlite3.Connection, message_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    if not message_ids:
        return {}

    query = TOOL_CALL_SQL.format(placeholders=_placeholders(message_ids))
    rows = _fetchall(conn, query, message_ids, "Failed loading tool calls")

    out: dict[int, list[sqlite3.Row]] = {}
    for row in rows:
        out.setdefault(int(row["message_id"]), []).append(row)
    return out


def load_tool_events(
    conn: sqlite3.Connection,
    session_id: str,
    message_ordinals: list[int],
) -> dict[tuple[int, int], list[sqlite3.Row]]:
    if not message_ordinals:
        return {}

    query = TOOL_EVENT_SQL.format(placeholders=_placeholders(message_ordinals))
    params: list[Any] = [session_id, *message_ordinals]
    rows = _fetchall(conn, query, params, f"Failed loading tool result events for session {session_id}")

    out: dict[tuple[int, int], list[sqlite3.Row]] = {}
    for row in rows:
        key = (int(row["tool_call_message_ordinal"]), int(row["call_index"]))
        out.setdefault(key, []).append(row)
    return out


def encode_result_event(row: sqlite3.Row) -> dict[str, object]:
    out: dict[str, object] = {
        "source": row["source"] or "",
        "status": row["status"] or "",
        "content": row["content"] or "",
        "content_length": int(row["content_length"] or 0),
    }
    _copy_truthy(out, row, "tool_use_id", "agent_id", "subagent_session_id", "timestamp")
    return out


def encode_tool_call(row: sqlite3.Row, result_events: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {
        "tool_name": row["tool_name"] or "",
        "category": row["category"] or "",
    }
    _copy_truthy(out, row, "tool_use_id", "input_json", "skill_name")
    if row["result_content_length"]:
        out["result_content_length"] = int(row["result_content_length"])
    _copy_truthy(out, row, "result_content", "subagent_session_id")
    if result_events:
        out["result_events"] = result_events
    return out


def encode_message(row: sqlite3.Row, tool_calls: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {
        "id": int(row["id"]),
        "session_id": row["session_id"],
        "ordinal": int(row["ordinal"]),
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
        try:
            out["token_usage"] = json.loads(row["token_usage"])
        except json.JSONDecodeError as exc:
            raise CliError(f"Invalid token_usage JSON for message {row['id']}: {exc}") from exc
    _copy_truthy(out, row, "claude_message_id", "claude_request_id", "source_type", "source_subtype", "source_uuid", "source_parent_uuid")
    _copy_true(out, row, "is_sidechain", "is_compact_boundary")
    if tool_calls:
        out["tool_calls"] = tool_calls
    return out


def build_payload_for_session(conn: sqlite3.Connection, session_row: sqlite3.Row) -> dict[str, object]:
    messages = load_messages(conn, str(session_row["id"]))
    message_ids = [int(row["id"]) for row in messages]
    message_ordinals = [int(row["ordinal"]) for row in messages]
    tool_calls_by_message_id = load_tool_calls(conn, message_ids)
    tool_events_by_key = load_tool_events(conn, str(session_row["id"]), message_ordinals)

    encoded_messages: list[dict[str, object]] = []
    for message_row in messages:
        tool_call_rows = tool_calls_by_message_id.get(int(message_row["id"]), [])
        encoded_tool_calls: list[dict[str, object]] = []
        for call_index, tool_call_row in enumerate(tool_call_rows):
            event_rows = tool_events_by_key.get((int(message_row["ordinal"]), call_index), [])
            encoded_events = [encode_result_event(event_row) for event_row in event_rows]
            encoded_tool_calls.append(encode_tool_call(tool_call_row, encoded_events))
        encoded_messages.append(encode_message(message_row, encoded_tool_calls))

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
        "messages": encoded_messages,
    }


def build_payloads(db_path: Path, *, session_id_query: str) -> list[dict[str, object]]:
    conn = snapshot_db(db_path)
    try:
        session_rows = select_sessions(conn, session_id_query=session_id_query)
        return [build_payload_for_session(conn, session_row) for session_row in session_rows]
    finally:
        conn.close()


def _read_markdown_file(markdown_file: str) -> str:
    path = Path(markdown_file).expanduser()
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise CliError(f"Failed reading Markdown file {path}: {exc}") from exc


def _markdown_filename(markdown_file: str) -> str:
    name = Path(markdown_file).expanduser().name
    if not name:
        raise CliError("Markdown file path must include a filename")
    return name


def _condense_md(doc: Mapping[str, Any]) -> dict[str, Any]:
    project = doc.get("project")
    if isinstance(project, Mapping):
        project = next((value for key in ("full_name", "name", "id") if isinstance(value := project.get(key), str) and value.strip()), None)
    tags = doc.get("tags")
    values = {
        "id": doc.get("id"),
        "project": project,
        "title": doc.get("title"),
        "plain_text_preview": doc.get("plain_text_preview"),
        "tags": ", ".join(map(str, tags)) if isinstance(tags, list) else tags,
    }
    return {field: values[field] for field in LIST_MD_OUTPUT_FIELDS}


def _condense_list(payload: Mapping[str, Any], keys: tuple[str, ...], view: Any) -> dict[str, Any]:
    condensed = dict(payload)
    for key in keys:
        items = payload.get(key)
        if isinstance(items, list):
            condensed[key] = [view(item) for item in items if isinstance(item, Mapping)]
    return condensed


def _truncate_create_md_output(payload: Mapping[str, Any]) -> dict[str, Any]:
    truncated = dict(payload)
    for field in CREATE_MD_OUTPUT_TRUNCATE_FIELDS:
        value = truncated.get(field)
        if isinstance(value, str):
            truncated[field] = value[:CREATE_MD_OUTPUT_TRUNCATE_LENGTH]
    return truncated


def _validate_raw_markdown(payload: Mapping[str, Any], doc_id: str) -> None:
    raw_markdown = payload.get("raw_markdown")
    if not isinstance(raw_markdown, str):
        raise CliError(f"/api/v1/md/{doc_id} response missing string 'raw_markdown'")


def command_create_md(_: Any, args: argparse.Namespace, *, transport: httpx.BaseTransport | None = None) -> Mapping[str, Any]:
    body: dict[str, Any] = {"raw_markdown": _read_markdown_file(args.markdown_file)}
    for body_key, attr_name, label in (
        ("project_id", "project_id", "--project-id"),
        ("project_name", "project_name", "--project-name"),
    ):
        value = _clean_optional(getattr(args, attr_name), label)
        if value is not None:
            body[body_key] = value
    body["title"] = _clean_optional(args.title, "--title") or _markdown_filename(args.markdown_file)
    payload = _agentsview_json(
        "POST",
        "/api/v1/projects/md",
        auth=_agentsview_auth(args),
        json_body=body,
        expected_statuses={201},
        transport=transport,
    )
    return _truncate_create_md_output(payload)


def command_list_md(_: Any, args: argparse.Namespace, *, transport: httpx.BaseTransport | None = None) -> Mapping[str, Any]:
    params: dict[str, Any] = {}
    for attr_name, param_name, label in (
        ("project", "project", "--project"),
        ("exclude_project", "exclude_project", "--exclude-project"),
        ("sort", "sort", "--sort"),
        ("cursor", "cursor", "--cursor"),
    ):
        if (value := _clean_optional(getattr(args, attr_name), label)) is not None:
            params[param_name] = value
    for attr_name, param_name, label in (("tag", "tag", "--tag"), ("created_by", "created_by", "--created-by")):
        values = getattr(args, attr_name)
        if values:
            joined = ",".join(
                value
                for value in (_clean_optional(raw, label) for raw in values)
                if value is not None
            )
            if joined:
                params[param_name] = joined
    if args.limit is not None:
        params["limit"] = args.limit
    payload = _agentsview_json(
        "GET",
        "/api/v1/md",
        auth=_agentsview_auth(args),
        params=params or None,
        expected_statuses={200},
        transport=transport,
    )
    return _condense_list(payload, ("documents", "items"), _condense_md)


def command_list_matters(_: Any, args: argparse.Namespace, *, transport: httpx.BaseTransport | None = None) -> Mapping[str, Any]:
    payload = _agentsview_json(
        "GET",
        "/api/v1/projects",
        auth=_agentsview_auth(args),
        params={"include_one_shot": "true"} if args.include_one_shot else None,
        expected_statuses={200},
        transport=transport,
    )
    return _condense_list(
        payload,
        ("projects",),
        lambda item: {field: item.get(field) for field in LIST_MATTERS_OUTPUT_FIELDS},
    )


def command_get_md(_: Any, args: argparse.Namespace, *, transport: httpx.BaseTransport | None = None) -> Mapping[str, Any]:
    doc_id = _require_value(args.id, "id")
    payload = _agentsview_json(
        "GET",
        f"/api/v1/md/{doc_id}",
        auth=_agentsview_auth(args),
        expected_statuses={200},
        transport=transport,
    )
    _validate_raw_markdown(payload, doc_id)
    return payload


def send_payload(
    base_url: str,
    clerk_api_key: str,
    org_id: str,
    share_id: str,
    payload: dict[str, object],
    *,
    transport: httpx.BaseTransport | None = None,
) -> None:
    session_payload = payload.get("session")
    if not isinstance(session_payload, dict):
        raise CliError(f"Payload for {share_id} is missing session")
    project = session_payload.get("project")
    if not isinstance(project, str) or not project.strip():
        raise CliError(f"Payload for {share_id} has blank session.project")
    _agentsview_request(
        "PUT",
        f"/api/v1/shares/{share_id}",
        auth=(clerk_api_key, org_id),
        json_body=payload,
        expected_statuses={204},
        transport=transport,
        base_url=base_url,
    )


def send_payloads(
    payloads: list[dict[str, object]],
    *,
    base_url: str,
    clerk_api_key: str,
    org_id: str,
    transport: httpx.BaseTransport | None = None,
) -> dict[str, object]:
    sent: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []

    for payload in payloads:
        share_id = payload.get("share_id")
        if not isinstance(share_id, str) or not share_id:
            raise CliError("Payload missing share_id")
        try:
            send_payload(base_url, clerk_api_key, org_id, share_id, payload, transport=transport)
        except CliError as exc:
            failures.append({"share_id": share_id, "error": exc.message})
            continue
        sent.append({"share_id": share_id, "url": f"{base_url.rstrip('/')}/sessions/{share_id}"})

    return {"sent_count": len(sent), "failed_count": len(failures), "sent": sent, "failures": failures}


def override_payload_project_name(
    payloads: list[dict[str, object]],
    project_name: str | None,
) -> None:
    if project_name is None:
        return

    cleaned_project_name = project_name.strip()
    if not cleaned_project_name:
        raise CliError("--project-name must not be blank")

    for payload in payloads:
        session_payload = payload.get("session")
        if not isinstance(session_payload, dict):
            share_id = payload.get("share_id")
            raise CliError(f"Payload for {share_id} is missing session")
        session_payload["project"] = cleaned_project_name


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def command_sync(_: Any, args: argparse.Namespace) -> object:
    payloads = build_payloads(Path(args.db_path).expanduser(), session_id_query=args.session_id)
    override_payload_project_name(payloads, args.project_name)
    if args.test:
        return payloads

    clerk_api_key, org_id = _agentsview_auth(args)
    return send_payloads(
        payloads,
        base_url=AGENTSVIEW_BASE_URL,
        clerk_api_key=clerk_api_key,
        org_id=org_id,
    )
