from __future__ import annotations

import pytest

import caption_cli.core as core


def test_emit_output_search_table_for_transcript_captions_uses_condensed_columns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "hits": [
            {
                "id": "caption-hit-id",
                "projectId": "project-uuid-1",
                "updatedAt": "2026-02-09T18:41:33.097Z",
                "format": 1.1,
                "scope": {"workspaceId": "w-uuid", "folderIds": [], "projectId": "legacy-scope-project"},
                "sessionId": "session-uuid",
                "speaker": {"id": "speaker-uuid-1", "name": "0:0"},
                "content": "patent work before and a lot of the money",
                "createdAt": 1766079084978,
            }
        ],
        "estimatedTotalHits": 1,
    }

    core.emit_output(payload, "table", command_name="search", search_index="transcript_captions_v1")
    out = capsys.readouterr().out

    assert "hits: 1 | unique: 1" in out
    assert "| # | projectId (uuid) | speaker.name | updatedAt (YYYYMMDD) | content |" in out
    assert "project-uuid-1" in out
    assert "legacy-scope-project" not in out
    assert "20260209" in out
    assert "speaker.id" not in out
    assert "sessionId" not in out
    assert "createdAt" not in out


def test_emit_output_search_table_for_transcript_sessions_uses_project_id(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "hits": [
            {
                "id": "session-hit-id",
                "projectId": "project-uuid-2",
                "updatedAt": "2026-02-10T18:41:33.097Z",
                "scope": {"workspaceId": "w-uuid", "folderIds": [], "projectId": "legacy-scope-project"},
                "speakers": ["Microphone", "Loopback"],
                "content": "patent application",
            }
        ],
        "estimatedTotalHits": 1,
    }

    core.emit_output(payload, "table", command_name="search", search_index="transcript_sessions_v1")
    out = capsys.readouterr().out

    assert "| # | projectId (uuid) | updatedAt (YYYYMMDD) | speakers | content |" in out
    assert "project-uuid-2" in out
    assert "legacy-scope-project" not in out
    assert "20260210" in out
    assert "Microphone, Loopback" in out


def test_emit_output_search_table_for_projects_uses_condensed_columns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "hits": [
            {
                "id": "project-uuid-1",
                "updatedAt": "2026-02-09T18:41:33.097Z",
                "format": 1,
                "scope": {"workspaceId": "workspace-uuid", "folderIds": []},
                "name": "Transcript 2026-02-09",
                "description": None,
            }
        ],
        "estimatedTotalHits": 1,
    }

    core.emit_output(payload, "table", command_name="search", search_index="projects_v1")
    out = capsys.readouterr().out

    assert "hits: 1 | unique: 1" in out
    assert "| # | id (project uuid) | updatedAt (YYYYMMDD) | name | description |" in out
    assert "project-uuid-1" in out
    assert "20260209" in out
    assert "scope" not in out
    assert "format" not in out


def test_emit_output_table_renders_transcript_id_for_empty_list_speakers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    core.emit_output(
        {"transcriptId": "t1", "items": [], "count": 0},
        "table",
        command_name="list_speakers",
    )

    assert capsys.readouterr().out == "transcriptId: t1\ncount: 0\n"
