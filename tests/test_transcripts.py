from __future__ import annotations

import json
from pathlib import Path

import pytest
from caption_helpers import set_runtime_env

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


def test_dl_transcript_command_is_available() -> None:
    args = cli.parse_args(["dl_transcript", "transcript-1"])
    assert args.command == "dl_transcript"
    assert args.transcript_id == "transcript-1"
    assert args.timestamp is False
    assert args.output == "md"


def test_explicit_output_overrides_dl_transcript_default() -> None:
    args = cli.parse_args(["--output", "json", "dl_transcript", "transcript-1"])
    assert args.output == "json"


def test_dl_transcript_accepts_timestamp_flag() -> None:
    args = cli.parse_args(["dl_transcript", "transcript-1", "--timestamp"])
    assert args.timestamp is True


def test_dl_transcript_fetches_captions_for_transcript(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    calls: list[tuple[str, str, str, dict[str, object] | None]] = []

    def fake_authorized_get_text(
        api_url: str,
        api_token: str,
        path: str,
        params: dict[str, object] | None = None,
    ) -> str:
        calls.append((api_url, api_token, path, params))
        return "[15:01.23] me: First line"

    monkeypatch.setattr(commands, "_authorized_get_text", fake_authorized_get_text)

    result = commands.dl_transcript(config, transcript_id="transcript-uuid")

    assert calls == [
        (
            "http://localhost:8000",
            "api-token",
            "/transcripts/transcript-uuid/export/txt",
            {"includeHeader": "false"},
        ),
    ]
    assert result == "me: First line"


def test_dl_transcript_preserves_timestamps_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    def fake_authorized_get_text(
        api_url: str,
        api_token: str,
        path: str,
        params: dict[str, object] | None = None,
    ) -> str:
        assert api_url == "http://localhost:8000"
        assert api_token == "api-token"
        assert path == "/transcripts/transcript-uuid/export/txt"
        assert params == {"includeHeader": "false"}
        return "[15:01.23] me: First line"

    monkeypatch.setattr(commands, "_authorized_get_text", fake_authorized_get_text)

    result = commands.dl_transcript(config, transcript_id="transcript-uuid", timestamp=True)

    assert result == "[15:01.23] me: First line"


def test_strip_transcript_timestamps_handles_iso_export_lines() -> None:
    transcript_text = (
        "# From Friday, April 10, 2026 at 9:21 AM\n\n"
        "[2026-04-10T14:23:23.875Z] Microphone:0\n"
        "  so when i start talking\n"
        "[2026-04-10T14:23:36.524Z] Microphone:1\n"
        "  because of the fact\n"
    )

    assert commands._strip_transcript_timestamps(transcript_text) == (
        "# From Friday, April 10, 2026 at 9:21 AM\n\n"
        "Microphone:0\n"
        "  so when i start talking\n"
        "Microphone:1\n"
        "  because of the fact\n"
    )


def test_run_dl_transcript_does_not_require_meili_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    set_runtime_env(monkeypatch, meili_url=None)

    def fake_dl_transcript(config: core.RuntimeConfig, *, transcript_id: str, timestamp: bool = False) -> str:
        assert transcript_id == "transcript-uuid"
        assert timestamp is False
        return "me: hello there\nmeeting-0: hi"

    monkeypatch.setattr(cli, "dl_transcript", fake_dl_transcript)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "dl_transcript",
            "transcript-uuid",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == "me: hello there\nmeeting-0: hi\n"


def test_run_dl_transcript_writes_default_md_output_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    output_file = tmp_path / "transcripts" / "transcript.md"
    transcript_text = "me: hello there\nmeeting-0: hi"

    def fake_dl_transcript(config: core.RuntimeConfig, *, transcript_id: str, timestamp: bool = False) -> str:
        assert transcript_id == "transcript-uuid"
        assert timestamp is False
        return transcript_text

    monkeypatch.setattr(cli, "dl_transcript", fake_dl_transcript)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "--output-file",
            str(output_file),
            "dl_transcript",
            "transcript-uuid",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Saved dl_transcript output to {output_file}\n"
    assert output_file.read_text(encoding="utf-8") == f"{transcript_text}\n"


def test_run_dl_transcript_with_timestamp_flag_preserves_timestamps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    set_runtime_env(monkeypatch, meili_url=None)

    def fake_dl_transcript(config: core.RuntimeConfig, *, transcript_id: str, timestamp: bool = False) -> str:
        assert transcript_id == "transcript-uuid"
        assert timestamp is True
        return "[15:01.23] me: hello there\n[15:01.24] meeting-0: hi"

    monkeypatch.setattr(cli, "dl_transcript", fake_dl_transcript)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "dl_transcript",
            "transcript-uuid",
            "--timestamp",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == "[15:01.23] me: hello there\n[15:01.24] meeting-0: hi\n"


def test_run_dl_transcript_with_json_output_emits_raw_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    set_runtime_env(monkeypatch, meili_url=None)

    payload = "me: hello"

    def fake_dl_transcript(config: core.RuntimeConfig, *, transcript_id: str, timestamp: bool = False) -> str:
        assert transcript_id == "transcript-uuid"
        assert timestamp is False
        return payload

    monkeypatch.setattr(cli, "dl_transcript", fake_dl_transcript)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "--output",
            "json",
            "dl_transcript",
            "transcript-uuid",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out) == "me: hello"


def test_run_dl_transcript_with_json_output_writes_json_rendered_output_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    output_file = tmp_path / "transcripts" / "transcript.json"
    payload = "me: hello"

    def fake_dl_transcript(config: core.RuntimeConfig, *, transcript_id: str, timestamp: bool = False) -> str:
        assert transcript_id == "transcript-uuid"
        assert timestamp is False
        return payload

    monkeypatch.setattr(cli, "dl_transcript", fake_dl_transcript)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "--output",
            "json",
            "--output-file",
            str(output_file),
            "dl_transcript",
            "transcript-uuid",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Saved dl_transcript output to {output_file}\n"
    assert output_file.read_text(encoding="utf-8") == f"{json.dumps(payload, indent=2)}\n"


def test_run_with_output_file_does_not_print_success_or_write_on_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    output_file = tmp_path / "nested" / "transcript.md"

    def fake_dl_transcript(config: core.RuntimeConfig, *, transcript_id: str, timestamp: bool = False) -> str:
        raise core.CliError("download failed")

    monkeypatch.setattr(cli, "dl_transcript", fake_dl_transcript)

    with pytest.raises(core.CliError, match="download failed"):
        cli.run(
            [
                "--env-file",
                "",
                "--cache-path",
                str(tmp_path / "search-token.json"),
                "--output-file",
                str(output_file),
                "dl_transcript",
                "transcript-uuid",
            ]
        )

    assert capsys.readouterr().out == ""
    assert not output_file.exists()
