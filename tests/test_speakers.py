from __future__ import annotations

import json

import pytest

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


def test_assign_speakers_command_is_available() -> None:
    args = cli.parse_args(
        [
            "assign_speakers",
            "--transcript-id",
            "t1",
            "--channel",
            "microphone",
            "--index",
            "1",
            "--name",
            "Alice",
            "--clerk-api-key",
            "k",
        ]
    )
    assert args.command == "assign_speakers"
    assert args.transcript_id == "t1"
    assert args.project_id is None
    assert args.channel == "microphone"
    assert args.index == 1
    assert args.name == "Alice"
    assert args.clerk_api_key == "k"


def test_list_speakers_command_is_available() -> None:
    args = cli.parse_args(["list_speakers", "t1", "--clerk-api-key", "k"])
    assert args.command == "list_speakers"
    assert args.transcript_id == "t1"
    assert args.clerk_api_key == "k"
    assert args.output == "table"


def test_rename_speaker_command_is_available() -> None:
    args = cli.parse_args(["rename_speaker", "p1", "s1", "--name", "Bob", "--clerk-api-key", "k"])
    assert args.command == "rename_speaker"
    assert args.project_id == "p1"
    assert args.speaker_id == "s1"
    assert args.name == "Bob"
    assert args.clerk_api_key == "k"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("0", 0),
        ("1", 1),
        ("2", 2),
        ("microphone", 0),
        ("Loopback", 1),
        ("EXTERNAL", 2),
        (" microphone ", 0),
    ],
)
def test_parse_channel_accepts_numbers_and_names(value: str, expected: int) -> None:
    assert commands._parse_channel(value) == expected


@pytest.mark.parametrize("value", ["3", "-1", "mic", ""])
def test_parse_channel_rejects_unknown_values(value: str) -> None:
    with pytest.raises(core.CliError, match="--channel must be one of"):
        commands._parse_channel(value)


def test_assign_speakers_requires_exactly_one_target(config: core.RuntimeConfig) -> None:
    for transcript_id, project_id in ((None, None), ("t1", "p1")):
        with pytest.raises(core.CliError, match="exactly one of --transcript-id or --project-id"):
            commands.command_assign_speakers(
                config,
                transcript_id=transcript_id,
                project_id=project_id,
                channel="0",
                index=None,
                speaker_id=None,
                name="Alice",
                dry_run=True,
            )


def test_assign_speakers_requires_exactly_one_speaker_selector(config: core.RuntimeConfig) -> None:
    for speaker_id, name in ((None, None), ("s1", "Alice")):
        with pytest.raises(core.CliError, match="exactly one of --speaker-id or --name"):
            commands.command_assign_speakers(
                config,
                transcript_id="t1",
                project_id=None,
                channel="0",
                index=None,
                speaker_id=speaker_id,
                name=name,
                dry_run=True,
            )


def test_assign_speakers_rejects_negative_index_and_empty_name(config: core.RuntimeConfig) -> None:
    with pytest.raises(core.CliError, match="--index must be >= 0"):
        commands.command_assign_speakers(
            config,
            transcript_id="t1",
            project_id=None,
            channel="0",
            index=-1,
            speaker_id=None,
            name="Alice",
            dry_run=True,
        )
    with pytest.raises(core.CliError, match="--name cannot be empty"):
        commands.command_assign_speakers(
            config,
            transcript_id="t1",
            project_id=None,
            channel="0",
            index=None,
            speaker_id=None,
            name="   ",
            dry_run=True,
        )


def test_assign_speakers_dry_run_previews_transcript_request(config: core.RuntimeConfig) -> None:
    result = commands.command_assign_speakers(
        config,
        transcript_id="t1",
        project_id=None,
        channel="microphone",
        index=1,
        speaker_id=None,
        name="Alice",
        dry_run=True,
    )
    assert result == {
        "dry_run": True,
        "method": "POST",
        "path": "/transcripts/t1/assign-speakers",
        "body": {"channel": 0, "index": 1, "speakerName": "Alice"},
    }


def test_assign_speakers_dry_run_previews_project_fanout(
    config: core.RuntimeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    result = commands.command_assign_speakers(
        config,
        transcript_id=None,
        project_id="p1",
        channel="1",
        index=2,
        speaker_id="s1",
        name=None,
        dry_run=True,
    )
    assert result == {
        "dry_run": True,
        "method": "POST",
        "path": "/transcripts/{transcriptId from /projects/p1/transcripts}/assign-speakers",
        "body": {"channel": 1, "index": 2, "speakerId": "s1"},
    }
    assert "diarization indexes are not stable across transcripts" in capsys.readouterr().err


def test_command_assign_speakers_posts_to_transcript_endpoint(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    request_calls: list[tuple[str, str, object, object]] = []

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
    ) -> dict[str, object]:
        request_calls.append((method, path, json_body, expected_statuses))
        return {"speakerId": "speaker-uuid", "updatedCaptionCount": 7}

    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    result = commands.command_assign_speakers(
        config,
        transcript_id="t1",
        project_id=None,
        channel="loopback",
        index=None,
        speaker_id=None,
        name="Alice",
        dry_run=False,
    )

    assert request_calls == [
        ("POST", "/transcripts/t1/assign-speakers", {"channel": 1, "speakerName": "Alice"}, {200, 201})
    ]
    assert result == {"speakerId": "speaker-uuid", "updatedCaptionCount": 7}


def test_command_assign_speakers_project_mode_paginates_and_aggregates(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    get_calls: list[tuple[str, object]] = []
    post_calls: list[tuple[str, str, object, object]] = []
    client_ids: set[int] = set()
    transcript_pages = {
        0: {"items": [{"id": f"t{i}"} for i in range(100)]},
        100: {"items": [{"id": "t100"}]},
    }

    def fake_authorized_get_json(
        api_url: str,
        api_token: str,
        path: str,
        params=None,
        client=None,
        visa_token=None,
    ) -> dict[str, object]:
        assert path == "/projects/p1/transcripts"
        assert params["limit"] == 100
        assert client is not None
        client_ids.add(id(client))
        get_calls.append((path, params))
        return transcript_pages[params["offset"]]

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
        client=None,
    ) -> dict[str, object]:
        assert client is not None
        client_ids.add(id(client))
        post_calls.append((method, path, json_body, expected_statuses))
        return {"speakerId": "speaker-uuid", "updatedCaptionCount": 2}

    monkeypatch.setattr(commands, "_authorized_get_json", fake_authorized_get_json)
    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    result = commands.command_assign_speakers(
        config,
        transcript_id=None,
        project_id="p1",
        channel="0",
        index=None,
        speaker_id=None,
        name="Alice",
        dry_run=False,
    )

    assert len(get_calls) == 2
    assert len(post_calls) == 101
    assert post_calls[0][1] == "/transcripts/t0/assign-speakers"
    assert post_calls[-1][1] == "/transcripts/t100/assign-speakers"
    assert len(client_ids) == 1
    assert result["speakerId"] == "speaker-uuid"
    assert result["transcriptCount"] == 101
    assert result["successCount"] == 101
    assert result["failureCount"] == 0
    assert result["totalUpdatedCaptionCount"] == 202
    assert result["failures"] == []
    assert result["results"][0] == {"transcriptId": "t0", "updatedCaptionCount": 2}


def test_command_assign_speakers_project_mode_reports_partial_failures(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    post_paths: list[str] = []

    def fake_authorized_get_json(
        api_url: str,
        api_token: str,
        path: str,
        params=None,
        client=None,
        visa_token=None,
    ) -> dict[str, object]:
        assert path == "/projects/p1/transcripts"
        return {"items": [{"id": "t1"}, {"id": "t2"}, {"id": "t3"}]}

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
        client=None,
    ) -> dict[str, object]:
        post_paths.append(path)
        if path == "/transcripts/t2/assign-speakers":
            raise core.CliError(
                "Failed POST /transcripts/t2/assign-speakers (500): boom",
                exit_code=core.EXIT_UPSTREAM,
            )
        return {"speakerId": "speaker-uuid", "updatedCaptionCount": 3}

    monkeypatch.setattr(commands, "_authorized_get_json", fake_authorized_get_json)
    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    with pytest.raises(core.CliError) as excinfo:
        commands.command_assign_speakers(
            config,
            transcript_id=None,
            project_id="p1",
            channel="0",
            index=None,
            speaker_id=None,
            name="Alice",
            dry_run=False,
        )

    assert post_paths == [
        "/transcripts/t1/assign-speakers",
        "/transcripts/t2/assign-speakers",
        "/transcripts/t3/assign-speakers",
    ]
    assert excinfo.value.exit_code == core.EXIT_UPSTREAM
    prefix = "assign_speakers project fan-out failed: "
    assert excinfo.value.message.startswith(prefix)
    report = json.loads(excinfo.value.message.removeprefix(prefix))
    assert report["transcriptCount"] == 3
    assert report["successCount"] == 2
    assert report["failureCount"] == 1
    assert report["totalUpdatedCaptionCount"] == 6
    assert report["results"] == [
        {"transcriptId": "t1", "updatedCaptionCount": 3},
        {"transcriptId": "t3", "updatedCaptionCount": 3},
    ]
    assert report["failures"] == [
        {
            "transcriptId": "t2",
            "error": "Failed POST /transcripts/t2/assign-speakers (500): boom",
            "exitCode": core.EXIT_UPSTREAM,
        }
    ]


def test_command_list_speakers_groups_captions_by_channel_index_and_speaker(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    captions = [
        {"channel": 1, "index": 0, "speaker": None, "content": "hello from loopback"},
        {"channel": 0, "index": 1, "speaker": "s-alice", "content": "first alice caption"},
        {"channel": 0, "index": 1, "speaker": "s-alice", "content": "second alice caption"},
        {"channel": 0, "index": 0, "speaker": None, "content": "unassigned mic caption"},
    ]

    def fake_fetch_list(
        api_url: str,
        api_token: str,
        path: str,
        *,
        client=None,
        page_limit: int = commands.PROJECT_TRANSCRIPTS_PAGE_LIMIT,
    ) -> list[dict[str, object]]:
        assert path == "/transcripts/t1/captions"
        return captions

    monkeypatch.setattr(commands, "_fetch_paginated_object_list", fake_fetch_list)

    result = commands.command_list_speakers(config, transcript_id="t1")

    assert result["transcriptId"] == "t1"
    assert result["count"] == 3
    assert result["items"] == [
        {
            "channel": 0,
            "index": 0,
            "speakerId": None,
            "captionCount": 1,
            "sample": "unassigned mic caption",
        },
        {
            "channel": 0,
            "index": 1,
            "speakerId": "s-alice",
            "captionCount": 2,
            "sample": "first alice caption",
        },
        {
            "channel": 1,
            "index": 0,
            "speakerId": None,
            "captionCount": 1,
            "sample": "hello from loopback",
        },
    ]


def test_command_list_speakers_paginates_caption_pages_and_ignores_null_sample(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    first_page = [
        {"channel": 0, "index": 0, "speaker": "s1", "content": None},
        *[
            {"channel": 0, "index": 0, "speaker": "s1", "content": f"caption {i}"}
            for i in range(99)
        ],
    ]
    second_page = [
        {"channel": 1, "index": 0, "speaker": None, "content": "loopback caption"},
    ]
    pages = {0: {"items": first_page}, 100: {"items": second_page}}
    get_offsets: list[int] = []

    def fake_authorized_get_json(
        api_url: str,
        api_token: str,
        path: str,
        params=None,
        client=None,
        visa_token=None,
    ) -> dict[str, object]:
        assert path == "/transcripts/t1/captions"
        assert params["limit"] == 100
        get_offsets.append(params["offset"])
        return pages[params["offset"]]

    monkeypatch.setattr(commands, "_authorized_get_json", fake_authorized_get_json)

    result = commands.command_list_speakers(config, transcript_id="t1")

    assert get_offsets == [0, 100]
    assert result["items"] == [
        {
            "channel": 0,
            "index": 0,
            "speakerId": "s1",
            "captionCount": 100,
            "sample": "",
        },
        {
            "channel": 1,
            "index": 0,
            "speakerId": None,
            "captionCount": 1,
            "sample": "loopback caption",
        },
    ]


def test_rename_speaker_dry_run_previews_patch(config: core.RuntimeConfig) -> None:
    result = commands.command_rename_speaker(
        config,
        project_id="p1",
        speaker_id="s1",
        name="Bob",
        dry_run=True,
    )
    assert result == {
        "dry_run": True,
        "method": "PATCH",
        "path": "/projects/p1/speakers/s1",
        "body": {"name": "Bob"},
    }


def test_rename_speaker_rejects_empty_name(config: core.RuntimeConfig) -> None:
    with pytest.raises(core.CliError, match="--name cannot be empty"):
        commands.command_rename_speaker(config, project_id="p1", speaker_id="s1", name=" ", dry_run=True)


def test_command_rename_speaker_patches_project_speaker(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    request_calls: list[tuple[str, str, object, object]] = []

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
    ) -> dict[str, object]:
        request_calls.append((method, path, json_body, expected_statuses))
        return {"id": "s1", "project": "p1", "kind": "custom", "name": "Bob"}

    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    result = commands.command_rename_speaker(
        config,
        project_id="p1",
        speaker_id="s1",
        name=" Bob ",
        dry_run=False,
    )

    assert request_calls == [("PATCH", "/projects/p1/speakers/s1", {"name": "Bob"}, {200})]
    assert result == {"id": "s1", "project": "p1", "kind": "custom", "name": "Bob"}


def test_run_assign_speakers_dry_run_is_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for env_var in ("CAPTION_API_URL", "CLERK_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "assign_speakers",
            "--transcript-id",
            "t1",
            "--channel",
            "external",
            "--name",
            "Alice",
            "--dry-run",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "dry_run": True,
        "method": "POST",
        "path": "/transcripts/t1/assign-speakers",
        "body": {"channel": 2, "speakerName": "Alice"},
    }
