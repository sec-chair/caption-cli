from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import httpx
import pytest

import caption_cli.agentsview as agentsview
import caption_cli.cli as cli
import caption_cli.core as core


def make_agentsview_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.executescript(
            """
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                machine TEXT NOT NULL DEFAULT 'local',
                agent TEXT NOT NULL DEFAULT 'claude',
                first_message TEXT,
                display_name TEXT,
                started_at TEXT,
                ended_at TEXT,
                message_count INTEGER NOT NULL DEFAULT 0,
                user_message_count INTEGER NOT NULL DEFAULT 0,
                parent_session_id TEXT,
                relationship_type TEXT NOT NULL DEFAULT '',
                total_output_tokens INTEGER NOT NULL DEFAULT 0,
                peak_context_tokens INTEGER NOT NULL DEFAULT 0,
                deleted_at TEXT
            );

            CREATE TABLE messages (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                ordinal INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                thinking_text TEXT NOT NULL DEFAULT '',
                timestamp TEXT,
                has_thinking INTEGER NOT NULL DEFAULT 0,
                has_tool_use INTEGER NOT NULL DEFAULT 0,
                content_length INTEGER NOT NULL DEFAULT 0,
                is_system INTEGER NOT NULL DEFAULT 0,
                model TEXT NOT NULL DEFAULT '',
                token_usage TEXT NOT NULL DEFAULT '',
                context_tokens INTEGER NOT NULL DEFAULT 0,
                output_tokens INTEGER NOT NULL DEFAULT 0,
                has_context_tokens INTEGER NOT NULL DEFAULT 0,
                has_output_tokens INTEGER NOT NULL DEFAULT 0,
                claude_message_id TEXT NOT NULL DEFAULT '',
                claude_request_id TEXT NOT NULL DEFAULT '',
                source_type TEXT NOT NULL DEFAULT '',
                source_subtype TEXT NOT NULL DEFAULT '',
                source_uuid TEXT NOT NULL DEFAULT '',
                source_parent_uuid TEXT NOT NULL DEFAULT '',
                is_sidechain INTEGER NOT NULL DEFAULT 0,
                is_compact_boundary INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE tool_calls (
                id INTEGER PRIMARY KEY,
                message_id INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                category TEXT NOT NULL,
                tool_use_id TEXT,
                input_json TEXT,
                skill_name TEXT,
                result_content_length INTEGER,
                result_content TEXT,
                subagent_session_id TEXT
            );

            CREATE TABLE tool_result_events (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_call_message_ordinal INTEGER NOT NULL,
                call_index INTEGER NOT NULL DEFAULT 0,
                tool_use_id TEXT,
                agent_id TEXT,
                subagent_session_id TEXT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                content TEXT NOT NULL,
                content_length INTEGER NOT NULL DEFAULT 0,
                timestamp TEXT,
                event_index INTEGER NOT NULL DEFAULT 0
            );
            """
        )

        conn.execute(
            """
            INSERT INTO sessions (
                id, project, machine, agent, first_message, display_name,
                started_at, ended_at, message_count, user_message_count,
                parent_session_id, relationship_type, total_output_tokens, peak_context_tokens, deleted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "s1",
                "proj",
                "local",
                "codex",
                None,
                None,
                "2026-04-21T05:00:00Z",
                None,
                2,
                1,
                None,
                "",
                17,
                99,
                None,
            ),
        )
        conn.executemany(
            """
            INSERT INTO messages (
                id, session_id, ordinal, role, content, thinking_text, timestamp,
                has_thinking, has_tool_use, content_length, is_system, model,
                token_usage, context_tokens, output_tokens, has_context_tokens, has_output_tokens,
                claude_message_id, claude_request_id, source_type, source_subtype,
                source_uuid, source_parent_uuid, is_sidechain, is_compact_boundary
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    11,
                    "s1",
                    0,
                    "user",
                    "hello",
                    "",
                    "2026-04-21T05:00:00Z",
                    0,
                    0,
                    5,
                    0,
                    "",
                    '{"input_tokens": 3}',
                    0,
                    0,
                    0,
                    0,
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                    0,
                    0,
                ),
                (
                    12,
                    "s1",
                    1,
                    "assistant",
                    "world",
                    "thinking",
                    "2026-04-21T05:00:01Z",
                    1,
                    1,
                    5,
                    0,
                    "gpt-test",
                    "",
                    12,
                    7,
                    1,
                    1,
                    "cm_1",
                    "cr_1",
                    "chat",
                    "reply",
                    "uuid-1",
                    "uuid-parent",
                    1,
                    1,
                ),
            ],
        )
        conn.executemany(
            """
            INSERT INTO tool_calls (
                id, message_id, session_id, tool_name, category, tool_use_id,
                input_json, skill_name, result_content_length, result_content, subagent_session_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (101, 12, "s1", "shell", "exec", "tool-a", '{"cmd":"echo a"}', "skill-a", 0, "", ""),
                (102, 12, "s1", "fetch", "net", "tool-b", '{"url":"https://example.com"}', "", 4, "done", "sub-1"),
            ],
        )
        conn.execute(
            """
            INSERT INTO tool_result_events (
                id, session_id, tool_call_message_ordinal, call_index, tool_use_id,
                agent_id, subagent_session_id, source, status, content, content_length, timestamp, event_index
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                1001,
                "s1",
                1,
                1,
                "tool-b",
                "agent-child",
                "sub-1",
                "tool",
                "completed",
                "done",
                0,
                "2026-04-21T05:00:02Z",
                0,
            ),
        )
        conn.commit()
    finally:
        conn.close()

def test_agentsview_commands_parse() -> None:
    args = cli.parse_args(["agentsview_build", "--project", "library", "--limit", "2", "--out-dir", "/tmp/out"])
    assert args.command == "agentsview_build"
    assert args.project == "library"
    assert args.limit == 2
    assert args.out_dir == "/tmp/out"

    send_args = cli.parse_args(["agentsview_send", "--session-id", "s1", "--org-id", "org_123"])
    assert send_args.command == "agentsview_send"
    assert send_args.session_id == ["s1"]
    assert send_args.org_id == "org_123"
    assert send_args.output == "json"


def test_agentsview_removed_flags_are_rejected() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["agentsview_build", "--config-path", "/tmp/config.toml"])
    with pytest.raises(SystemExit):
        cli.parse_args(["agentsview_send", "--share-url", "https://example.com"])
    with pytest.raises(SystemExit):
        cli.parse_args(["agentsview_send", "--publisher", "local"])


def test_agentsview_run_does_not_require_caption_api_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    db_path.touch()

    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    monkeypatch.delenv("CLERK_API_KEY", raising=False)

    emitted: dict[str, object] = {}

    def fake_emit_output(
        value: object,
        output_format: str,
        *,
        command_name: str | None = None,
        search_index: str | None = None,
    ) -> None:
        emitted["value"] = value
        emitted["format"] = output_format
        emitted["command_name"] = command_name
        emitted["search_index"] = search_index

    monkeypatch.setattr(cli, "emit_output", fake_emit_output)
    monkeypatch.setattr(cli, "command_agentsview_build", lambda config, args: {"ok": True, "db_path": args.db_path})

    exit_code = cli.run(["agentsview_build", "--db-path", str(db_path)])

    assert exit_code == 0
    assert emitted["value"] == {"ok": True, "db_path": str(db_path)}
    assert emitted["command_name"] == "agentsview_build"


def test_build_payloads_shapes_messages_and_tool_events(tmp_path: Path) -> None:
    db_path = tmp_path / "sessions.db"
    make_agentsview_db(db_path)

    payloads = agentsview.build_payloads(
        db_path,
        session_ids=[],
        project="proj",
        agent="codex",
        started_after=None,
        started_before=None,
        limit=10,
    )

    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["share_id"] == "s1"
    assert payload["session"]["first_message"] is None
    assert payload["session"]["display_name"] is None
    assert payload["session"]["parent_session_id"] is None

    messages = payload["messages"]
    assert [message["ordinal"] for message in messages] == [0, 1]
    assert messages[0]["token_usage"] == {"input_tokens": 3}

    assistant_message = messages[1]
    assert assistant_message["thinking_text"] == "thinking"
    assert assistant_message["claude_message_id"] == "cm_1"
    assert assistant_message["source_type"] == "chat"
    assert assistant_message["is_sidechain"] is True
    assert assistant_message["is_compact_boundary"] is True

    tool_calls = assistant_message["tool_calls"]
    assert [tool_call["tool_name"] for tool_call in tool_calls] == ["shell", "fetch"]
    assert "result_content_length" not in tool_calls[0]
    assert "result_events" not in tool_calls[0]
    assert tool_calls[1]["result_content_length"] == 4
    assert tool_calls[1]["result_events"][0]["agent_id"] == "agent-child"
    assert tool_calls[1]["result_events"][0]["content_length"] == 0


def test_snapshot_db_reads_committed_rows_in_wal_mode(tmp_path: Path) -> None:
    db_path = tmp_path / "wal.db"
    writer = sqlite3.connect(db_path)
    try:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE sessions (id TEXT PRIMARY KEY, deleted_at TEXT)")
        writer.execute("INSERT INTO sessions (id, deleted_at) VALUES ('s1', NULL)")
        writer.commit()
    finally:
        writer.close()

    snapshot = agentsview.snapshot_db(db_path)
    try:
        count = snapshot.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
    finally:
        snapshot.close()

    assert count == 1


def test_send_payload_uses_expected_request_contract() -> None:
    payload = {
        "share_id": "s1",
        "session": {"id": "s1", "project": "proj", "agent": "codex", "message_count": 1, "user_message_count": 1},
        "messages": [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PUT"
        assert str(request.url) == "https://history.caption.fyi/api/v1/shares/s1"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert request.headers["X-Agentsview-Org"] == "org_123"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["User-Agent"] == "agentsview"
        assert json.loads(request.content) == payload
        return httpx.Response(status_code=204)

    transport = httpx.MockTransport(handler)
    agentsview.send_payload(
        agentsview.AGENTSVIEW_BASE_URL,
        "test-token",
        "org_123",
        "s1",
        payload,
        transport=transport,
    )


@pytest.mark.parametrize(
    ("status_code", "body", "match"),
    [
        (401, "Unauthorized", "401"),
        (403, "Forbidden", "Forbidden"),
        (403, '{"error":"no active organization — pick one to continue"}', "no active organization"),
        (500, '{"error":"internal error"}', "internal error"),
    ],
)
def test_send_payload_surfaces_server_errors(status_code: int, body: str, match: str) -> None:
    payload = {
        "share_id": "s1",
        "session": {"id": "s1", "project": "proj", "agent": "codex", "message_count": 1, "user_message_count": 1},
        "messages": [],
    }

    transport = httpx.MockTransport(lambda request: httpx.Response(status_code=status_code, text=body))
    with pytest.raises(core.CliError, match=match):
        agentsview.send_payload(
            agentsview.AGENTSVIEW_BASE_URL,
            "test-token",
            "org_123",
            "s1",
            payload,
            transport=transport,
        )


def test_send_payload_rejects_blank_project() -> None:
    payload = {
        "share_id": "s1",
        "session": {"id": "s1", "project": "   ", "agent": "codex", "message_count": 1, "user_message_count": 1},
        "messages": [],
    }

    with pytest.raises(core.CliError, match="blank session.project"):
        agentsview.send_payload(
            agentsview.AGENTSVIEW_BASE_URL,
            "test-token",
            "org_123",
            "s1",
            payload,
            transport=httpx.MockTransport(lambda request: httpx.Response(status_code=204)),
        )


def test_command_agentsview_send_uses_env_auth_when_flags_are_omitted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    make_agentsview_db(db_path)
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")
    captured: dict[str, object] = {}

    def fake_send_payloads(
        payloads: list[dict[str, object]],
        *,
        base_url: str,
        clerk_api_key: str,
        org_id: str,
        transport: httpx.BaseTransport | None = None,
    ) -> dict[str, object]:
        captured["payloads"] = payloads
        captured["base_url"] = base_url
        captured["clerk_api_key"] = clerk_api_key
        captured["org_id"] = org_id
        captured["transport"] = transport
        return {"sent_count": len(payloads), "failed_count": 0, "sent": [], "failures": []}

    monkeypatch.setattr(agentsview, "send_payloads", fake_send_payloads)

    args = cli.parse_args(["agentsview_send", "--db-path", str(db_path), "--session-id", "s1"])
    result = agentsview.command_agentsview_send(None, args)

    assert result["sent_count"] == 1
    assert captured["base_url"] == agentsview.AGENTSVIEW_BASE_URL
    assert captured["clerk_api_key"] == "env-token"
    assert captured["org_id"] == "env-org"
    payloads = captured["payloads"]
    assert isinstance(payloads, list)
    assert len(payloads) == 1
    payload = payloads[0]
    assert payload["share_id"] == "s1"
    assert payload["session"]["id"] == "s1"
    assert payload["session"]["project"] == "proj"
    assert len(payload["messages"]) == 2


def test_command_agentsview_send_flags_override_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    make_agentsview_db(db_path)
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")
    captured: dict[str, str] = {}

    def fake_send_payloads(
        payloads: list[dict[str, object]],
        *,
        base_url: str,
        clerk_api_key: str,
        org_id: str,
        transport: httpx.BaseTransport | None = None,
    ) -> dict[str, object]:
        captured["clerk_api_key"] = clerk_api_key
        captured["org_id"] = org_id
        return {"sent_count": len(payloads), "failed_count": 0, "sent": [], "failures": []}

    monkeypatch.setattr(agentsview, "send_payloads", fake_send_payloads)

    args = cli.parse_args(
        [
            "agentsview_send",
            "--db-path",
            str(db_path),
            "--session-id",
            "s1",
            "--clerk-api-key",
            "flag-token",
            "--org-id",
            "flag-org",
        ]
    )
    agentsview.command_agentsview_send(None, args)

    assert captured == {"clerk_api_key": "flag-token", "org_id": "flag-org"}


def test_command_agentsview_send_requires_clerk_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    make_agentsview_db(db_path)
    monkeypatch.delenv("CLERK_API_KEY", raising=False)
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    args = cli.parse_args(["--env-file", "", "agentsview_send", "--db-path", str(db_path), "--session-id", "s1"])
    with pytest.raises(core.CliError, match=r"Missing Clerk API key \(--clerk-api-key or CLERK_API_KEY\)"):
        agentsview.command_agentsview_send(None, args)


def test_command_agentsview_send_requires_organization_id(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    make_agentsview_db(db_path)
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.delenv("ORGANIZATION_ID", raising=False)

    args = cli.parse_args(["--env-file", "", "agentsview_send", "--db-path", str(db_path), "--session-id", "s1"])
    with pytest.raises(core.CliError, match=r"Missing org id \(--org-id or ORGANIZATION_ID\)"):
        agentsview.command_agentsview_send(None, args)


def test_agentsview_send_uses_env_file_for_auth(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "sessions.db"
    make_agentsview_db(db_path)
    env_file = tmp_path / ".env"
    env_file.write_text("CLERK_API_KEY=file-token\nORGANIZATION_ID=file-org\n", encoding="utf-8")
    monkeypatch.delenv("CLERK_API_KEY", raising=False)
    monkeypatch.delenv("ORGANIZATION_ID", raising=False)
    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    emitted: dict[str, object] = {}
    captured: dict[str, str] = {}

    def fake_emit_output(
        value: object,
        output_format: str,
        *,
        command_name: str | None = None,
        search_index: str | None = None,
    ) -> None:
        emitted["value"] = value
        emitted["format"] = output_format
        emitted["command_name"] = command_name

    def fake_send_payloads(
        payloads: list[dict[str, object]],
        *,
        base_url: str,
        clerk_api_key: str,
        org_id: str,
        transport: httpx.BaseTransport | None = None,
    ) -> dict[str, object]:
        captured["base_url"] = base_url
        captured["clerk_api_key"] = clerk_api_key
        captured["org_id"] = org_id
        return {"sent_count": len(payloads), "failed_count": 0, "sent": [], "failures": []}

    monkeypatch.setattr(cli, "emit_output", fake_emit_output)
    monkeypatch.setattr(agentsview, "send_payloads", fake_send_payloads)

    exit_code = cli.run(
        [
            "--env-file",
            str(env_file),
            "agentsview_send",
            "--db-path",
            str(db_path),
            "--session-id",
            "s1",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "base_url": agentsview.AGENTSVIEW_BASE_URL,
        "clerk_api_key": "file-token",
        "org_id": "file-org",
    }
    assert emitted["format"] == "json"
    assert emitted["command_name"] == "agentsview_send"
