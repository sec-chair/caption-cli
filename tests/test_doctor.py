from __future__ import annotations

import json

import httpx
import pytest

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


def test_doctor_command_reports_core_feature(monkeypatch: pytest.MonkeyPatch, config: core.RuntimeConfig) -> None:
    workspace_id = "019ddf62-9a21-7b01-bf9a-26c60a819d90"

    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        assert api_url == "http://localhost:8000"
        assert api_token == "api-token"
        return workspace_id

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)

    result = commands.command_doctor(config)
    assert list(result) == ["probes"]
    assert result["probes"] == [
        {"name": "core", "available": True, "reason": None},
    ]


def test_doctor_command_omits_core_when_caption_returns_non_uuid(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    monkeypatch.setattr(commands, "fetch_current_workspace_id", lambda api_url, api_token: "not-a-uuid")

    result = commands.command_doctor(config)
    assert list(result) == ["probes"]
    core_probe = result["probes"][0]
    assert core_probe["available"] is False
    assert "non-UUID" in core_probe["reason"]


@pytest.mark.parametrize(
    "exc",
    [
        core.CliError("caption failed"),
        httpx.ConnectError("caption failed"),
    ],
)
def test_doctor_command_omits_core_when_caption_probe_raises(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
    exc: Exception,
) -> None:
    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        raise exc

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)

    result = commands.command_doctor(config)
    assert list(result) == ["probes"]
    core_probe = result["probes"][0]
    assert core_probe["available"] is False
    assert "caption failed" in core_probe["reason"]


def _install_fake_doctor(monkeypatch: pytest.MonkeyPatch, *, core_ok: bool) -> None:
    def fake_command_doctor(config: core.RuntimeConfig) -> dict[str, object]:
        probes = [
            {"name": "core", "available": core_ok, "reason": None if core_ok else "Missing Caption API URL. Set CAPTION_API_URL"},
        ]
        return {"probes": probes}

    monkeypatch.setattr(cli, "command_doctor", fake_command_doctor)


def test_run_doctor_failed_probe_reports_reason_on_stderr_but_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_doctor(monkeypatch, core_ok=False)

    exit_code = cli.run(["--env-file", "", "doctor"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "doctor: probe 'core' failed: Missing Caption API URL" in captured.err
    assert captured.out == "CAPTION FEATURES AVAILABLE:\n"


def test_run_doctor_strict_exits_nonzero_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_doctor(monkeypatch, core_ok=False)

    exit_code = cli.run(["--env-file", "", "doctor", "--strict"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "doctor: probe 'core' failed" in captured.err


def test_run_doctor_plain_lists_available_probes(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_doctor(monkeypatch, core_ok=True)

    exit_code = cli.run(["--env-file", "", "doctor"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out == "CAPTION FEATURES AVAILABLE:\ncore\n"


def test_run_doctor_json_output_is_structured_and_parseable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_doctor(monkeypatch, core_ok=True)

    exit_code = cli.run(["--env-file", "", "--output", "json", "doctor"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert "features" not in payload
    assert payload["probes"][0] == {"name": "core", "available": True, "reason": None}
    assert captured.err == ""


def test_doctor_command_is_available() -> None:
    args = cli.parse_args(["doctor"])
    assert args.command == "doctor"
    assert args.output == "plain"
    assert args.clerk_api_key is None
