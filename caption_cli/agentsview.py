from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

import httpx

from caption_cli.core import CliError

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

TOOL_CALL_SQL = """
SELECT
  id, message_id, session_id, tool_name, category,
  tool_use_id, input_json, skill_name,
  result_content_length, result_content, subagent_session_id
FROM tool_calls
WHERE message_id IN ({placeholders})
ORDER BY id
"""

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


@dataclass(frozen=True, slots=True)
class ShareSettings:
    url: str | None
    clerk_api_key: str | None
    org_id: str | None
    publisher: str | None


def default_data_dir() -> Path:
    override = os.getenv("AGENT_VIEWER_DATA_DIR")
    if override and override.strip():
        return Path(override.strip()).expanduser()
    return Path.home() / ".agentsview"


def default_db_path() -> Path:
    return default_data_dir() / "sessions.db"


def default_config_path() -> Path:
    return default_data_dir() / "config.toml"


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


def _load_share_section(config_path: Path) -> Mapping[str, Any]:
    if not config_path.exists():
        return {}

    try:
        with config_path.open("rb") as fh:
            payload = tomllib.load(fh)
    except OSError as exc:
        raise CliError(f"Failed reading config file {config_path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"Failed parsing config file {config_path}: {exc}") from exc

    share_section = payload.get("share")
    if share_section is None:
        return {}
    if not isinstance(share_section, dict):
        raise CliError(f"{config_path} [share] must be a TOML table")
    return share_section


def load_share_settings(
    config_path: Path,
    *,
    share_url: str | None,
    clerk_api_key: str | None,
    org_id: str | None,
    publisher: str | None,
) -> ShareSettings:
    share_section = _load_share_section(config_path)

    config_url = share_section.get("url")
    config_clerk_api_key = share_section.get("clerk_api_key")
    if not isinstance(config_clerk_api_key, str) or not config_clerk_api_key.strip():
        fallback_token = share_section.get("token")
        if isinstance(fallback_token, str) and fallback_token.strip():
            config_clerk_api_key = fallback_token
    config_org_id = share_section.get("org")
    if not isinstance(config_org_id, str) or not config_org_id.strip():
        fallback_org_id = share_section.get("org_id")
        if isinstance(fallback_org_id, str) and fallback_org_id.strip():
            config_org_id = fallback_org_id
    config_publisher = share_section.get("publisher")

    resolved_url = _clean_optional(share_url, "--share-url")
    if resolved_url is None and isinstance(config_url, str) and config_url.strip():
        resolved_url = config_url.strip()
    if resolved_url is not None:
        resolved_url = resolved_url.rstrip("/")

    resolved_clerk_api_key = _clean_optional(clerk_api_key, "--clerk-api-key")
    if resolved_clerk_api_key is None and isinstance(config_clerk_api_key, str) and config_clerk_api_key.strip():
        resolved_clerk_api_key = config_clerk_api_key.strip()

    resolved_org_id = _clean_optional(org_id, "--org-id")
    if resolved_org_id is None and isinstance(config_org_id, str) and config_org_id.strip():
        resolved_org_id = config_org_id.strip()

    resolved_publisher = _clean_optional(publisher, "--publisher")
    if resolved_publisher is None and isinstance(config_publisher, str) and config_publisher.strip():
        resolved_publisher = config_publisher.strip()

    return ShareSettings(
        url=resolved_url,
        clerk_api_key=resolved_clerk_api_key,
        org_id=resolved_org_id,
        publisher=resolved_publisher,
    )


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


def select_sessions(
    conn: sqlite3.Connection,
    *,
    session_ids: list[str],
    project: str | None,
    agent: str | None,
    started_after: str | None,
    started_before: str | None,
    limit: int | None,
) -> list[sqlite3.Row]:
    params: list[Any] = []
    query = SESSION_SQL

    if session_ids:
        query += f" AND id IN ({_placeholders(session_ids)})"
        params.extend(session_ids)
    if project is not None:
        query += " AND project = ?"
        params.append(project)
    if agent is not None:
        query += " AND agent = ?"
        params.append(agent)
    if started_after is not None:
        query += " AND started_at > ?"
        params.append(started_after)
    if started_before is not None:
        query += " AND started_at < ?"
        params.append(started_before)

    query += " ORDER BY started_at DESC, id"
    if limit is not None:
        query += " LIMIT ?"
        params.append(limit)

    try:
        return list(conn.execute(query, params).fetchall())
    except sqlite3.Error as exc:
        raise CliError(f"Failed selecting sessions: {exc}") from exc


def load_messages(conn: sqlite3.Connection, session_id: str) -> list[sqlite3.Row]:
    try:
        return list(conn.execute(MESSAGE_SQL, (session_id,)).fetchall())
    except sqlite3.Error as exc:
        raise CliError(f"Failed loading messages for session {session_id}: {exc}") from exc


def load_tool_calls(conn: sqlite3.Connection, message_ids: list[int]) -> dict[int, list[sqlite3.Row]]:
    if not message_ids:
        return {}

    query = TOOL_CALL_SQL.format(placeholders=_placeholders(message_ids))
    try:
        rows = conn.execute(query, message_ids).fetchall()
    except sqlite3.Error as exc:
        raise CliError(f"Failed loading tool calls: {exc}") from exc

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
    try:
        rows = conn.execute(query, params).fetchall()
    except sqlite3.Error as exc:
        raise CliError(f"Failed loading tool result events for session {session_id}: {exc}") from exc

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
    if row["tool_use_id"]:
        out["tool_use_id"] = row["tool_use_id"]
    if row["agent_id"]:
        out["agent_id"] = row["agent_id"]
    if row["subagent_session_id"]:
        out["subagent_session_id"] = row["subagent_session_id"]
    if row["timestamp"]:
        out["timestamp"] = row["timestamp"]
    return out


def encode_tool_call(row: sqlite3.Row, result_events: list[dict[str, object]]) -> dict[str, object]:
    out: dict[str, object] = {
        "tool_name": row["tool_name"] or "",
        "category": row["category"] or "",
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


def build_payload_for_session(
    conn: sqlite3.Connection,
    session_row: sqlite3.Row,
    publisher: str,
) -> dict[str, object]:
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

    share_id = f"{publisher}:{session_row['id']}"
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


def build_payloads(
    db_path: Path,
    *,
    publisher: str,
    session_ids: list[str],
    project: str | None,
    agent: str | None,
    started_after: str | None,
    started_before: str | None,
    limit: int | None,
) -> list[dict[str, object]]:
    conn = snapshot_db(db_path)
    try:
        session_rows = select_sessions(
            conn,
            session_ids=session_ids,
            project=project,
            agent=agent,
            started_after=started_after,
            started_before=started_before,
            limit=limit,
        )
        return [build_payload_for_session(conn, session_row, publisher) for session_row in session_rows]
    finally:
        conn.close()


def write_payloads(payloads: list[dict[str, object]], out_dir: Path) -> list[Path]:
    resolved_out_dir = out_dir.expanduser()
    try:
        resolved_out_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CliError(f"Failed creating output directory {resolved_out_dir}: {exc}") from exc

    written_paths: list[Path] = []
    for payload in payloads:
        share_id = payload["share_id"]
        if not isinstance(share_id, str) or not share_id:
            raise CliError("Payload missing share_id")
        path = resolved_out_dir / f"{share_id}.json"
        try:
            path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError as exc:
            raise CliError(f"Failed writing payload file {path}: {exc}") from exc
        written_paths.append(path)
    return written_paths


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

    url = f"{base_url.rstrip('/')}/api/v1/shares/{share_id}"
    headers = {
        "Authorization": f"Bearer {clerk_api_key}",
        "X-Agentsview-Org": org_id,
        "Content-Type": "application/json",
        "User-Agent": "agentsview",
    }
    with httpx.Client(timeout=30.0, transport=transport) as client:
        response = client.put(url, headers=headers, json=payload)

    if response.status_code == 204:
        return
    if response.status_code >= 400:
        detail = response.text.strip() or response.reason_phrase
        raise CliError(f"Share server error for {share_id} ({response.status_code}): {detail}")
    raise CliError(f"Unexpected share server response for {share_id} ({response.status_code})")


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
        sent.append({"share_id": share_id, "url": f"{base_url.rstrip('/')}/api/v1/shares/{share_id}"})

    return {
        "sent_count": len(sent),
        "failed_count": len(failures),
        "sent": sent,
        "failures": failures,
    }


def _clean_session_ids(values: list[str] | None) -> list[str]:
    if not values:
        return []
    out: list[str] = []
    for value in values:
        cleaned = _clean_optional(value, "--session-id")
        if cleaned is None:
            continue
        out.append(cleaned)
    return out


def _clean_optional_arg(value: str | None, label: str) -> str | None:
    return _clean_optional(value, label)


def _build_payloads_from_args(args: argparse.Namespace) -> tuple[list[dict[str, object]], ShareSettings]:
    share_settings = load_share_settings(
        Path(args.config_path).expanduser(),
        share_url=args.share_url,
        clerk_api_key=args.clerk_api_key,
        org_id=args.org_id,
        publisher=args.publisher,
    )
    publisher = _require_value(share_settings.publisher, "share publisher (--publisher or [share].publisher)")
    payloads = build_payloads(
        Path(args.db_path).expanduser(),
        publisher=publisher,
        session_ids=_clean_session_ids(args.session_id),
        project=_clean_optional_arg(args.project, "--project"),
        agent=_clean_optional_arg(args.agent, "--agent"),
        started_after=_clean_optional_arg(args.started_after, "--started-after"),
        started_before=_clean_optional_arg(args.started_before, "--started-before"),
        limit=args.limit,
    )
    return payloads, share_settings


def command_agentsview_build(_: Any, args: argparse.Namespace) -> object:
    payloads, _ = _build_payloads_from_args(args)
    if args.out_dir is None:
        return payloads

    written_paths = write_payloads(payloads, Path(args.out_dir))
    return {
        "count": len(payloads),
        "share_ids": [payload["share_id"] for payload in payloads],
        "files": [str(path) for path in written_paths],
    }


def command_agentsview_send(_: Any, args: argparse.Namespace) -> dict[str, object]:
    payloads, share_settings = _build_payloads_from_args(args)
    base_url = _require_value(share_settings.url, "share URL (--share-url or [share].url)")
    clerk_api_key = _require_value(
        share_settings.clerk_api_key,
        "Clerk API key (--clerk-api-key or [share].clerk_api_key)",
    )
    org_id = _require_value(share_settings.org_id, "org id (--org-id or [share].org)")
    return send_payloads(
        payloads,
        base_url=base_url,
        clerk_api_key=clerk_api_key,
        org_id=org_id,
    )
