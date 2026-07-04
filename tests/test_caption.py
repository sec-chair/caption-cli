from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


class FakeAuthError(Exception):
    def __init__(self) -> None:
        self.status_code = 401
        self.code = "invalid_api_key"
        self.message = "invalid_api_key"
        super().__init__(self.message)


@pytest.fixture
def config(tmp_path: Path) -> core.RuntimeConfig:
    return core.RuntimeConfig(
        api_url="http://localhost:8000",
        api_token="api-token",
        meili_url="https://configured.meili",
        cache_path=tmp_path / "search-token.json",
        output="json",
    )


def write_cache(path: Path, token: str = "cached-token", url: str = "https://cached.meili") -> None:
    path.write_text(json.dumps({"token": token, "url": url}), encoding="utf-8")


def set_runtime_env(monkeypatch: pytest.MonkeyPatch, *, meili_url: str | None = "https://configured.meili") -> None:
    monkeypatch.setenv("CAPTION_API_URL", "http://localhost:8000")
    monkeypatch.setenv("CLERK_API_KEY", "api-token")
    if meili_url is None:
        monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    else:
        monkeypatch.setenv("CAPTION_MEILI_URL", meili_url)


def install_emit_output_capture(monkeypatch: pytest.MonkeyPatch) -> dict[str, object]:
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
    return emitted


def test_token_command_fetches_and_caches_credentials(monkeypatch: pytest.MonkeyPatch, config: core.RuntimeConfig) -> None:
    expected = core.SearchToken(
        token="meili-token",
        url="https://meili.railway.app",
        expires_at="2099-01-01T00:00:00Z",
    )

    monkeypatch.setattr(commands, "fetch_search_token", lambda api_url, api_token: expected)

    result = commands.command_token(config)
    assert result["token"] == "[REDACTED]"
    assert result["url"] == "https://configured.meili"

    cached = json.loads(config.cache_path.read_text(encoding="utf-8"))
    assert cached == {
        "token": "meili-token",
        "url": "https://meili.railway.app",
        "expiresAt": "2099-01-01T00:00:00Z",
    }


def test_token_command_show_token_returns_raw_value(monkeypatch: pytest.MonkeyPatch, config: core.RuntimeConfig) -> None:
    expected = core.SearchToken(
        token="meili-token",
        url="https://meili.railway.app",
        expires_at="2099-01-01T00:00:00Z",
    )

    monkeypatch.setattr(commands, "fetch_search_token", lambda api_url, api_token: expected)

    result = commands.command_token(config, show_token=True)
    assert result["token"] == "meili-token"


def test_doctor_command_reports_both_features(monkeypatch: pytest.MonkeyPatch, config: core.RuntimeConfig) -> None:
    workspace_id = "019ddf62-9a21-7b01-bf9a-26c60a819d90"

    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        assert api_url == "http://localhost:8000"
        assert api_token == "api-token"
        return workspace_id

    def fake_agentsview_json(*args: object, **kwargs: object) -> dict[str, object]:
        assert args == ("GET", "/api/v1/md")
        assert kwargs["params"] == {"limit": 1}
        assert kwargs["expected_statuses"] == {200}
        return {"documents": []}

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)
    monkeypatch.setattr(commands.agentsview, "_agentsview_json", fake_agentsview_json)
    args = cli.parse_args(["--env-file", "", "doctor", "--clerk-api-key", "history-token", "--org-id", "org_123"])

    result = commands.command_doctor(config, args)
    assert result["features"] == ["core", "agentsview"]
    assert result["organization"] == "org_123"
    assert result["probes"] == [
        {"name": "core", "available": True, "reason": None},
        {"name": "agentsview", "available": True, "reason": None},
    ]


def test_doctor_command_omits_core_when_caption_returns_non_uuid(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    monkeypatch.setattr(commands, "fetch_current_workspace_id", lambda api_url, api_token: "not-a-uuid")
    monkeypatch.setattr(commands.agentsview, "_agentsview_json", lambda *args, **kwargs: {"documents": []})
    args = cli.parse_args(["--env-file", "", "doctor", "--clerk-api-key", "history-token", "--org-id", "org_123"])

    result = commands.command_doctor(config, args)
    assert result["features"] == ["agentsview"]
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
    monkeypatch.setattr(commands.agentsview, "_agentsview_json", lambda *args, **kwargs: {"documents": []})
    args = cli.parse_args(["--env-file", "", "doctor", "--clerk-api-key", "history-token", "--org-id", "org_123"])

    result = commands.command_doctor(config, args)
    assert result["features"] == ["agentsview"]
    core_probe = result["probes"][0]
    assert core_probe["available"] is False
    assert "caption failed" in core_probe["reason"]


def test_doctor_command_omits_agentsview_without_documents(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    monkeypatch.setattr(
        commands,
        "fetch_current_workspace_id",
        lambda api_url, api_token: "019ddf62-9a21-7b01-bf9a-26c60a819d90",
    )
    monkeypatch.setattr(commands.agentsview, "_agentsview_json", lambda *args, **kwargs: {"items": []})
    args = cli.parse_args(["--env-file", "", "doctor", "--clerk-api-key", "history-token", "--org-id", "org_123"])

    result = commands.command_doctor(config, args)
    assert result["features"] == ["core"]
    agentsview_probe = result["probes"][1]
    assert agentsview_probe["available"] is False
    assert "documents" in agentsview_probe["reason"]


@pytest.mark.parametrize(
    "exc",
    [
        core.CliError("agentsview failed"),
        httpx.ConnectError("agentsview failed"),
    ],
)
def test_doctor_command_omits_agentsview_when_probe_raises(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
    exc: Exception,
) -> None:
    monkeypatch.setattr(
        commands,
        "fetch_current_workspace_id",
        lambda api_url, api_token: "019ddf62-9a21-7b01-bf9a-26c60a819d90",
    )

    def fake_agentsview_json(*args: object, **kwargs: object) -> dict[str, object]:
        raise exc

    monkeypatch.setattr(commands.agentsview, "_agentsview_json", fake_agentsview_json)
    args = cli.parse_args(["--env-file", "", "doctor", "--clerk-api-key", "history-token", "--org-id", "org_123"])

    result = commands.command_doctor(config, args)
    assert result["features"] == ["core"]
    agentsview_probe = result["probes"][1]
    assert agentsview_probe["available"] is False
    assert "agentsview failed" in agentsview_probe["reason"]


def _install_fake_doctor(monkeypatch: pytest.MonkeyPatch, *, core_ok: bool, agentsview_ok: bool) -> None:
    def fake_command_doctor(config: core.RuntimeConfig, args: object) -> dict[str, object]:
        probes = [
            {"name": "core", "available": core_ok, "reason": None if core_ok else "Missing Caption API URL. Set CAPTION_API_URL"},
            {"name": "agentsview", "available": agentsview_ok, "reason": None if agentsview_ok else "history server unreachable: boom"},
        ]
        return {
            "organization": "org_123",
            "features": [probe["name"] for probe in probes if probe["available"]],
            "probes": probes,
        }

    monkeypatch.setattr(cli, "command_doctor", fake_command_doctor)


def test_run_doctor_failed_probe_reports_reason_on_stderr_but_exits_zero(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_doctor(monkeypatch, core_ok=False, agentsview_ok=True)

    exit_code = cli.run(["--env-file", "", "doctor"])

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "doctor: probe 'core' failed: Missing Caption API URL" in captured.err
    assert "ORGANIZATION: org_123" in captured.out
    assert "agentsview" in captured.out


def test_run_doctor_strict_exits_nonzero_when_probe_fails(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_doctor(monkeypatch, core_ok=False, agentsview_ok=False)

    exit_code = cli.run(["--env-file", "", "doctor", "--strict"])

    captured = capsys.readouterr()
    assert exit_code != 0
    assert "doctor: probe 'core' failed" in captured.err
    assert "doctor: probe 'agentsview' failed" in captured.err


def test_run_doctor_json_output_is_structured_and_parseable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _install_fake_doctor(monkeypatch, core_ok=True, agentsview_ok=True)

    exit_code = cli.run(["--env-file", "", "--output", "json", "doctor"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["organization"] == "org_123"
    assert payload["features"] == ["core", "agentsview"]
    assert payload["probes"][0] == {"name": "core", "available": True, "reason": None}
    assert captured.err == ""


def test_run_capabilities_emits_machine_readable_contract_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for env_var in ("CAPTION_API_URL", "CLERK_API_KEY", "CAPTION_MEILI_URL", "ORGANIZATION_ID"):
        monkeypatch.delenv(env_var, raising=False)

    exit_code = cli.run(["--env-file", "", "capabilities"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["tool"] == "caption"
    assert payload["contract_version"]
    command_names = [command["name"] for command in payload["commands"]]
    assert "capabilities" in command_names
    assert "doctor" in command_names
    assert "search" in command_names
    assert payload["exit_codes"]["0"]
    assert payload["exit_codes"]["2"]
    assert "CAPTION_API_URL" in payload["env_vars"]
    assert "AGENT_VIEWER_DATA_DIR" in payload["env_vars"]
    search_command = next(command for command in payload["commands"] if command["name"] == "search")
    assert search_command["usage"].startswith("caption search")
    assert search_command["default_output"] == "table"


def test_capabilities_defaults_to_json_output() -> None:
    assert cli.parse_args(["capabilities"]).output == "json"


def test_list_projects_full_returns_raw_payload_without_note(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
    capsys: pytest.CaptureFixture[str],
) -> None:
    raw_item = {
        "id": "p1",
        "name": "Alpha",
        "transcript": None,
        "createdAt": "2024-01-01",
        "updatedAt": "2024-01-02",
        "folder": None,
        "description": None,
        "extraServerField": "kept-only-in-full",
    }
    monkeypatch.setattr(commands, "fetch_current_workspace_id", lambda api_url, api_token: "w-uuid")
    monkeypatch.setattr(commands, "fetch_workspace_items", lambda *args, **kwargs: [dict(raw_item)])

    condensed = commands.command_list_projects(config)
    condensed_err = capsys.readouterr().err
    assert "extraServerField" not in condensed["items"][0]
    assert "condensed view" in condensed_err
    assert "--full" in condensed_err

    full = commands.command_list_projects(config, full=True)
    full_err = capsys.readouterr().err
    assert full["items"][0]["extraServerField"] == "kept-only-in-full"
    assert full_err == ""


def test_exit_code_dictionary_missing_config_maps_to_exit_config() -> None:
    empty_config = core.RuntimeConfig(
        api_url=None, api_token=None, meili_url=None, cache_path=Path("unused"), output="json"
    )
    with pytest.raises(core.CliError) as excinfo:
        core._require_api_url(empty_config)
    assert excinfo.value.exit_code == core.EXIT_CONFIG

    with pytest.raises(core.CliError) as excinfo:
        core._require_api_token(empty_config)
    assert excinfo.value.exit_code == core.EXIT_CONFIG

    with pytest.raises(core.CliError) as excinfo:
        core._require_meili_url(empty_config)
    assert excinfo.value.exit_code == core.EXIT_CONFIG


def test_exit_code_dictionary_maps_remote_statuses() -> None:
    assert core._exit_code_for_status(404) == core.EXIT_NOT_FOUND
    assert core._exit_code_for_status(500) == core.EXIT_UPSTREAM
    assert core._exit_code_for_status(401) == core.EXIT_UPSTREAM

    not_found_transport = httpx.MockTransport(lambda request: httpx.Response(404, text="nope"))
    with pytest.raises(core.CliError) as excinfo:
        commands.agentsview._agentsview_request(
            "GET",
            "/api/v1/md/missing-doc",
            auth=("key", "org"),
            expected_statuses={200},
            transport=not_found_transport,
        )
    assert excinfo.value.exit_code == core.EXIT_NOT_FOUND

    server_error_transport = httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(core.CliError) as excinfo:
        commands.agentsview._agentsview_request(
            "GET",
            "/api/v1/md",
            auth=("key", "org"),
            expected_statuses={200},
            transport=server_error_transport,
        )
    assert excinfo.value.exit_code == core.EXIT_UPSTREAM


def test_top_level_help_documents_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["-h"])

    output = capsys.readouterr().out
    assert "Exit codes" in output
    assert "configuration error" in output
    assert "upstream failure" in output


def test_extract_object_list_accepts_current_items_response() -> None:
    payload = {"items": [{"id": "f1"}, {"id": "f2"}]}

    assert core._extract_object_list(payload, "/folders/workspace/folders") == [
        {"id": "f1"},
        {"id": "f2"},
    ]


def test_extract_object_list_keeps_legacy_top_level_array_response() -> None:
    payload = [{"id": "f1"}]

    assert core._extract_object_list(payload, "/folders/workspace/folders") == [{"id": "f1"}]


def test_extract_object_list_rejects_object_without_items_array() -> None:
    with pytest.raises(core.CliError, match="missing array 'items'"):
        core._extract_object_list({"count": 0}, "/folders/workspace/folders")


def test_extract_object_list_rejects_non_object_items() -> None:
    with pytest.raises(core.CliError, match="'items' array containing non-object items"):
        core._extract_object_list({"items": ["not-object"]}, "/folders/workspace/folders")


def test_parse_args_defaults_env_file_to_current_working_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    loaded: list[tuple[Path, bool]] = []
    expected_env_file = tmp_path / ".env"

    def fake_load_dotenv(*, dotenv_path: Path, override: bool) -> None:
        loaded.append((dotenv_path, override))

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "load_dotenv", fake_load_dotenv)

    args = cli.parse_args(["list_projects"])

    assert args.env_file == str(expected_env_file)
    assert loaded == [(expected_env_file, True)]


def test_parse_args_respects_env_file_override(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    loaded: list[tuple[Path, bool]] = []
    custom_env = tmp_path / "custom.env"

    def fake_load_dotenv(*, dotenv_path: Path, override: bool) -> None:
        loaded.append((dotenv_path, override))

    monkeypatch.setattr(cli, "load_dotenv", fake_load_dotenv)

    args = cli.parse_args(["--env-file", str(custom_env), "list_projects"])

    assert args.env_file == str(custom_env)
    assert loaded == [(custom_env, True)]


def test_parse_args_ignores_caption_meili_cache_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CAPTION_MEILI_CACHE", "/tmp/ignored-search-token.json")

    args = cli.parse_args(["list_projects"])

    assert args.cache_path == core.DEFAULT_CACHE_PATH


def test_search_command_defaults_to_captions_index_and_limit() -> None:
    args = cli.parse_args(["search", "term"])

    assert args.command == "search"
    assert args.query == "term"
    assert args.index == core.DEFAULT_SEARCH_INDEX
    assert args.limit == core.DEFAULT_LIMIT
    assert args.show_dupes is False
    assert args.output == "table"


def test_search_command_accepts_positional_query_and_index_uid() -> None:
    args = cli.parse_args(
        ["search", "term", "--index", "projects_v1", "--limit", "7", "--show-dupes"]
    )

    assert args.command == "search"
    assert args.query == "term"
    assert args.index == "projects_v1"
    assert args.limit == 7
    assert args.show_dupes is True


def test_search_help_lists_supported_indices(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["search", "--help"])

    captured = capsys.readouterr()
    assert core.DEFAULT_SEARCH_INDEX in captured.out
    assert "transcript_blocks_v2" in captured.out
    assert "transcript_captions_v1" not in captured.out
    assert "workspace_folders_v1" not in captured.out
    assert "projects_v1" not in captured.out
    assert "transcript_sessions_v1" not in captured.out


def test_search_command_rejects_limit_lt_1() -> None:
    with pytest.raises(core.CliError, match="--limit must be >= 1"):
        cli.parse_args(["search", "term", "--limit", "0"])


def test_list_projects_command_is_available() -> None:
    args = cli.parse_args(["list_projects"])
    assert args.command == "list_projects"


def test_list_folders_command_is_available() -> None:
    args = cli.parse_args(["list_folders"])
    assert args.command == "list_folders"


def test_list_matters_command_is_available() -> None:
    args = cli.parse_args(["list_matters"])
    assert args.command == "list_matters"
    assert args.include_one_shot is False


def test_create_project_command_is_available() -> None:
    args = cli.parse_args(["create_project", "My Project", "--description", "Desc", "--workspace-id", "w1"])
    assert args.command == "create_project"
    assert args.name == "My Project"
    assert args.description == "Desc"
    assert args.workspace_id == "w1"


def test_create_folder_command_is_available() -> None:
    args = cli.parse_args(["create_folder", "My Folder", "--description", "Desc", "--parent", "f1", "--workspace-id", "w1"])
    assert args.command == "create_folder"
    assert args.name == "My Folder"
    assert args.description == "Desc"
    assert args.parent == "f1"
    assert args.workspace_id == "w1"


def test_edit_project_command_is_available() -> None:
    args = cli.parse_args(["edit_project", "project-1", "--name", "Renamed", "--clear-folder"])
    assert args.command == "edit_project"
    assert args.project_id == "project-1"
    assert args.name == "Renamed"
    assert args.clear_folder is True


def test_edit_folder_command_is_available() -> None:
    args = cli.parse_args(["edit_folder", "folder-1", "--name", "Renamed", "--clear-parent"])
    assert args.command == "edit_folder"
    assert args.folder_id == "folder-1"
    assert args.name == "Renamed"
    assert args.clear_parent is True


def test_dl_transcript_command_is_available() -> None:
    args = cli.parse_args(["dl_transcript", "transcript-1"])
    assert args.command == "dl_transcript"
    assert args.transcript_id == "transcript-1"
    assert args.timestamp is False
    assert args.output == "md"


def test_command_default_outputs_are_applied() -> None:
    assert cli.parse_args(["doctor"]).output == "plain"
    assert cli.parse_args(["search", "term"]).output == "table"
    assert cli.parse_args(["list_projects"]).output == "table"
    assert cli.parse_args(["list_folders"]).output == "table"
    assert cli.parse_args(["list_matters"]).output == "table"
    assert cli.parse_args(["list_speakers", "t1"]).output == "table"
    assert (
        cli.parse_args(
            ["assign_speakers", "--transcript-id", "t1", "--channel", "0", "--name", "Alice"]
        ).output
        == "json"
    )
    assert cli.parse_args(["rename_speaker", "p1", "s1", "--name", "Bob"]).output == "json"
    assert cli.parse_args(["list_md"]).output == "json"
    assert cli.parse_args(["get_md", "doc-id"]).output == "md"
    assert cli.parse_args(["create_project", "My Project"]).output == "json"


def test_explicit_output_overrides_dl_transcript_default() -> None:
    args = cli.parse_args(["--output", "json", "dl_transcript", "transcript-1"])
    assert args.output == "json"


def test_parse_args_accepts_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "out.txt"

    args = cli.parse_args(["--output-file", str(output_file), "list_projects"])

    assert args.output_file == output_file


def test_doctor_command_is_available() -> None:
    args = cli.parse_args(["doctor"])
    assert args.command == "doctor"
    assert args.output == "plain"
    assert args.clerk_api_key is None
    assert args.org_id is None


def test_dl_transcript_accepts_timestamp_flag() -> None:
    args = cli.parse_args(["dl_transcript", "transcript-1", "--timestamp"])
    assert args.timestamp is True


def test_unknown_flag_typo_suggests_correction_and_subcommand_usage(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.parse_args(["search", "term", "--liimt", "5"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "did you mean --limit?" in captured.err
    assert "usage: caption search" in captured.err
    assert "for 'caption search'" in captured.err


def test_unknown_flag_underscore_spelling_suggests_dashed_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.parse_args(["token", "--show_token"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "did you mean --show-token?" in captured.err
    assert "usage: caption token" in captured.err


def test_unknown_flag_abbreviation_suggests_full_flag(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.parse_args(["search", "term", "--lim", "5"])

    assert excinfo.value.code == 2
    assert "did you mean --limit?" in capsys.readouterr().err


def test_global_flag_after_subcommand_teaches_placement(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.parse_args(["search", "term", "--output", "json"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "global flag and must come before the subcommand" in captured.err
    assert "did you mean --output?" not in captured.err


def test_unknown_flag_without_close_match_lists_valid_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.parse_args(["search", "term", "--jsno"])

    captured = capsys.readouterr()
    assert excinfo.value.code == 2
    assert "Valid flags:" in captured.err
    assert "--output" in captured.err
    assert "--limit" in captured.err


def test_removed_global_flags_are_rejected() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["--api-url", "http://localhost:8000", "list_projects"])
    with pytest.raises(SystemExit):
        cli.parse_args(["--api-token", "api-token", "list_projects"])
    with pytest.raises(SystemExit):
        cli.parse_args(["--meili-url", "https://configured.meili", "token"])


def test_top_level_help_contains_single_page_cheat_sheet(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["-h"])

    output = capsys.readouterr().out
    assert "Command Cheat Sheet" in output
    assert "CAPTION_API_URL" in output
    assert "CLERK_API_KEY" in output
    assert "CAPTION_MEILI_URL" in output
    assert "--api-url" not in output
    assert "--api-token" not in output
    assert "--meili-url" not in output
    for command_name in (
        "token",
        "search",
        "list_projects",
        "list_folders",
        "list_matters",
        "create_project",
        "create_folder",
        "edit_project",
        "edit_folder",
        "dl_transcript",
        "assign_speakers",
        "list_speakers",
        "rename_speaker",
    ):
        assert command_name in output
    assert "usage: caption search <query> [--index INDEX] [--limit N]" in output
    assert "example: caption --output json dl_transcript <transcript-uuid>" in output


def test_create_project_dry_run_returns_request_preview_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for env_var in ("CAPTION_API_URL", "CLERK_API_KEY"):
        monkeypatch.delenv(env_var, raising=False)

    exit_code = cli.run(["--env-file", "", "create_project", "Demo", "--description", "d", "--dry-run"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True
    assert payload["method"] == "POST"
    assert payload["path"].endswith("/projects")
    assert payload["body"] == {"name": "Demo", "description": "d"}


def test_edit_project_dry_run_previews_patch_body(config: core.RuntimeConfig) -> None:
    result = commands.command_edit_project(
        config,
        project_id="p-uuid",
        name=None,
        description=None,
        clear_description=False,
        folder=None,
        clear_folder=True,
        dry_run=True,
    )
    assert result == {"dry_run": True, "method": "PATCH", "path": "/projects/p-uuid", "body": {"folder": None}}


def test_edit_project_dry_run_still_validates_inputs(config: core.RuntimeConfig) -> None:
    with pytest.raises(core.CliError, match="not both"):
        commands.command_edit_project(
            config,
            project_id="p-uuid",
            name=None,
            description="x",
            clear_description=True,
            folder=None,
            clear_folder=False,
            dry_run=True,
        )


def test_sync_wildcard_without_test_or_yes_is_refused(config: core.RuntimeConfig) -> None:
    args = cli.parse_args(["--env-file", "", "sync", "--session-id", "*"])
    with pytest.raises(core.CliError) as excinfo:
        commands.command_sync(config, args)
    assert "--yes" in excinfo.value.message
    assert "--test" in excinfo.value.message


def test_sync_dry_run_is_an_alias_for_test() -> None:
    args = cli.parse_args(["--env-file", "", "sync", "--session-id", "s1", "--dry-run"])
    assert args.test is True


def test_sync_wildcard_with_test_builds_payloads(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    monkeypatch.setattr(commands.agentsview, "build_payloads", lambda db_path, *, session_id_query: [])
    args = cli.parse_args(["--env-file", "", "sync", "--session-id", "*", "--test"])
    assert commands.command_sync(config, args) == []


def test_sync_wildcard_with_yes_proceeds_to_send(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    monkeypatch.setenv("CLERK_API_KEY", "k")
    monkeypatch.setenv("ORGANIZATION_ID", "o")
    monkeypatch.setattr(commands.agentsview, "build_payloads", lambda db_path, *, session_id_query: [])
    sent: dict[str, object] = {}

    def fake_send_payloads(payloads: list, **kwargs: object) -> dict[str, object]:
        sent["payloads"] = payloads
        return {"sent_count": 0, "failed_count": 0, "sent": [], "failures": []}

    monkeypatch.setattr(commands.agentsview, "send_payloads", fake_send_payloads)
    args = cli.parse_args(["--env-file", "", "sync", "--session-id", "*", "--yes"])
    result = commands.command_sync(config, args)
    assert result["sent_count"] == 0
    assert sent["payloads"] == []


def test_main_api_verbs_accept_clerk_api_key_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("CAPTION_API_URL", "http://localhost:8000")
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    seen: dict[str, object] = {}

    def fake_command_list_projects(config: core.RuntimeConfig, *, full: bool = False) -> dict[str, object]:
        seen["api_token"] = config.api_token
        return {"workspaceId": "w", "items": [], "count": 0}

    monkeypatch.setattr(cli, "command_list_projects", fake_command_list_projects)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "list_projects",
            "--clerk-api-key",
            "flag-token",
        ]
    )

    assert exit_code == 0
    assert seen["api_token"] == "flag-token"


def test_main_api_verbs_all_parse_clerk_api_key() -> None:
    assert cli.parse_args(["token", "--clerk-api-key", "k"]).clerk_api_key == "k"
    assert cli.parse_args(["search", "q", "--clerk-api-key", "k"]).clerk_api_key == "k"
    assert cli.parse_args(["list_folders", "--clerk-api-key", "k"]).clerk_api_key == "k"
    assert cli.parse_args(["create_project", "N", "--clerk-api-key", "k"]).clerk_api_key == "k"
    assert cli.parse_args(["edit_project", "id", "--name", "N", "--clerk-api-key", "k"]).clerk_api_key == "k"
    assert cli.parse_args(["dl_transcript", "t", "--clerk-api-key", "k"]).clerk_api_key == "k"


def test_bare_invocation_prints_cheat_sheet_help_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        cli.parse_args([])

    output = capsys.readouterr().out
    assert excinfo.value.code == 0
    assert "Command Cheat Sheet" in output
    assert "Agent quick start" in output


def test_run_robot_docs_guide_prints_agent_handbook_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for env_var in ("CAPTION_API_URL", "CLERK_API_KEY", "CAPTION_MEILI_URL", "ORGANIZATION_ID"):
        monkeypatch.delenv(env_var, raising=False)

    exit_code = cli.run(["--env-file", "", "robot-docs", "guide"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "# caption — agent guide" in output
    assert "## Exit codes" in output
    assert "## Environment" in output
    assert "### search" in output
    assert "caption capabilities" in output


def test_robot_docs_topic_defaults_to_guide() -> None:
    args = cli.parse_args(["robot-docs"])
    assert args.topic == "guide"
    assert args.output == "md"


def test_subcommand_help_includes_notes_example_and_default_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["search", "-h"])

    output = capsys.readouterr().out
    assert "default output: table" in output
    assert "Uses cached token and refreshes once on Meili auth failures." in output
    assert (
        f'example: caption search "roadmap" --index {core.DEFAULT_SEARCH_INDEX} --limit 10'
        in output
    )


def test_top_level_help_has_agent_quick_start(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["-h"])

    output = capsys.readouterr().out
    assert "Agent quick start" in output
    assert "caption capabilities" in output
    assert "--output json" in output


def test_legacy_subcommands_are_removed() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["search-global", "--query", "term"])

    with pytest.raises(SystemExit):
        cli.parse_args(["search-captions", "--query", "term", "--session-id", "abc"])

    with pytest.raises(SystemExit):
        cli.parse_args(["search-folders", "--query", "eng"])

    with pytest.raises(SystemExit):
        cli.parse_args(["create", "name"])

    with pytest.raises(SystemExit):
        cli.parse_args(["edit", "id"])


def test_command_search_uses_index_search_endpoint_shape(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    write_cache(config.cache_path)
    index_calls: list[str] = []
    search_calls: list[tuple[str, dict[str, int]]] = []

    class FakeIndex:
        def search(self, query, opt_params=None):
            search_calls.append((query, dict(opt_params or {})))
            return {"hits": []}

    class FakeClient:
        def index(self, index_uid):
            index_calls.append(index_uid)
            return FakeIndex()

    monkeypatch.setattr(core, "build_meili_client", lambda url, token: FakeClient())

    result = commands.command_search(config, query="roadmap", index="projects_v1", limit=7)

    assert result == {"hits": []}
    assert index_calls == ["projects_v1"]
    assert search_calls == [("roadmap", {"limit": 7})]


def test_command_search_dedupes_hits_by_project_id(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    write_cache(config.cache_path)

    class FakeIndex:
        def search(self, query, opt_params=None):
            return {
                "hits": [
                    {"id": "caption-1", "projectId": "project-1"},
                    {"id": "caption-2", "projectId": "project-1"},
                    {"id": "session-1", "scope": {"projectId": "project-2"}},
                    {
                        "id": "caption-3",
                        "projectId": "project-2",
                        "scope": {"projectId": "legacy-project"},
                    },
                    {"id": "projectless-1"},
                    {"id": "projectless-2"},
                ],
                "estimatedTotalHits": 6,
            }

    class FakeClient:
        def index(self, index_uid):
            return FakeIndex()

    monkeypatch.setattr(core, "build_meili_client", lambda url, token: FakeClient())

    result = commands.command_search(
        config, query="roadmap", index="transcript_captions_v1", limit=10
    )

    assert [hit["id"] for hit in result["hits"]] == [
        "caption-1",
        "session-1",
        "projectless-1",
        "projectless-2",
    ]
    assert result["estimatedTotalHits"] == 6


def test_command_search_show_dupes_skips_project_id_dedupe(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    write_cache(config.cache_path)

    class FakeIndex:
        def search(self, query, opt_params=None):
            return {
                "hits": [
                    {"id": "caption-1", "projectId": "project-1"},
                    {"id": "caption-2", "projectId": "project-1"},
                ],
                "estimatedTotalHits": 2,
            }

    class FakeClient:
        def index(self, index_uid):
            return FakeIndex()

    monkeypatch.setattr(core, "build_meili_client", lambda url, token: FakeClient())

    result = commands.command_search(
        config,
        query="roadmap",
        index="transcript_captions_v1",
        limit=10,
        show_dupes=True,
    )

    assert [hit["id"] for hit in result["hits"]] == ["caption-1", "caption-2"]


def test_command_search_rejects_empty_index(
    config: core.RuntimeConfig,
) -> None:
    with pytest.raises(core.CliError, match="--index cannot be empty"):
        commands.command_search(config, query="term", index="   ", limit=5)


def test_invalid_meili_token_refreshes_once_and_retries(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    write_cache(config.cache_path, token="stale-token", url="https://old.meili")
    built_clients: list[tuple[str, str]] = []
    fetch_calls: list[tuple[str, str]] = []
    index_calls: list[str] = []

    class FirstIndex:
        def search(self, query, opt_params=None):
            raise FakeAuthError()

    class SecondIndex:
        def search(self, query, opt_params=None):
            return {"hits": [{"id": "ok"}]}

    class FirstClient:
        def index(self, index_uid):
            index_calls.append(index_uid)
            return FirstIndex()

    class SecondClient:
        def index(self, index_uid):
            index_calls.append(index_uid)
            return SecondIndex()

    def fake_build_client(url: str, token: str):
        built_clients.append((url, token))
        if token == "stale-token":
            return FirstClient()
        return SecondClient()

    def fake_fetch_search_token(api_url: str, api_token: str) -> core.SearchToken:
        fetch_calls.append((api_url, api_token))
        return core.SearchToken(token="fresh-token", url="https://new.meili")

    monkeypatch.setattr(core, "build_meili_client", fake_build_client)
    monkeypatch.setattr(core, "fetch_search_token", fake_fetch_search_token)

    result = commands.command_search(config, query="retry", index=core.DEFAULT_SEARCH_INDEX, limit=2)

    assert result == {"hits": [{"id": "ok"}]}
    assert fetch_calls == [("http://localhost:8000", "api-token")]
    assert built_clients == [
        ("https://configured.meili", "stale-token"),
        ("https://configured.meili", "fresh-token"),
    ]
    assert index_calls == [core.DEFAULT_SEARCH_INDEX, core.DEFAULT_SEARCH_INDEX]

    cached = json.loads(config.cache_path.read_text(encoding="utf-8"))
    assert cached == {"token": "fresh-token", "url": "https://new.meili"}


def test_run_search_uses_default_index_when_flag_omitted(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    set_runtime_env(monkeypatch, meili_url=config.meili_url)
    write_cache(config.cache_path)
    index_calls: list[str] = []

    class FakeIndex:
        def search(self, query, opt_params=None):
            return {"hits": [{"query": query, "limit": opt_params["limit"]}]}

    class FakeClient:
        def index(self, index_uid):
            index_calls.append(index_uid)
            return FakeIndex()

    monkeypatch.setattr(core, "build_meili_client", lambda url, token: FakeClient())
    emitted = install_emit_output_capture(monkeypatch)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(config.cache_path),
            "search",
            "term",
        ]
    )

    assert exit_code == 0
    assert index_calls == [core.DEFAULT_SEARCH_INDEX]
    assert emitted["format"] == "table"
    assert emitted["value"] == {"hits": [{"query": "term", "limit": core.DEFAULT_LIMIT}]}
    assert emitted["command_name"] == "search"
    assert emitted["search_index"] == core.DEFAULT_SEARCH_INDEX


def test_run_search_show_dupes_passes_flag_to_command(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    set_runtime_env(monkeypatch, meili_url=config.meili_url)
    captured: dict[str, object] = {}

    def fake_command_search(
        runtime_config: core.RuntimeConfig,
        query: str,
        index: str,
        limit: int,
        *,
        show_dupes: bool,
    ) -> dict[str, object]:
        captured["config"] = runtime_config
        captured["query"] = query
        captured["index"] = index
        captured["limit"] = limit
        captured["show_dupes"] = show_dupes
        return {"hits": []}

    monkeypatch.setattr(cli, "command_search", fake_command_search)
    emitted = install_emit_output_capture(monkeypatch)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(config.cache_path),
            "search",
            "term",
            "--index",
            "projects_v1",
            "--limit",
            "7",
            "--show-dupes",
        ]
    )

    assert exit_code == 0
    assert captured == {
        "config": core.RuntimeConfig(
            api_url="http://localhost:8000",
            api_token="api-token",
            meili_url="https://configured.meili",
            cache_path=config.cache_path,
            output="table",
        ),
        "query": "term",
        "index": "projects_v1",
        "limit": 7,
        "show_dupes": True,
    }
    assert emitted["value"] == {"hits": []}


def test_command_list_projects_fetches_workspace_and_all_projects(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    fetch_calls: list[tuple[str, str]] = []

    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        assert api_url == "http://localhost:8000"
        assert api_token == "api-token"
        return "workspace-uuid"

    def fake_fetch_workspace_items(
        api_url: str,
        api_token: str,
        workspace_id: str,
        endpoint: str,
    ) -> list[dict[str, object]]:
        fetch_calls.append((workspace_id, endpoint))
        assert endpoint == "projects"
        return [
            {
                "id": "p1",
                "createdAt": "2023-12-31T00:00:00Z",
                "updatedAt": "2024-01-01T00:00:00Z",
                "name": "Alpha",
                "description": "First",
                "folder": None,
                "transcript": "t1",
                "workspace": "w1",
                "createdBy": "u1",
            },
            {
                "id": "p2",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-02T00:00:00Z",
                "name": "Beta",
                "description": None,
                "folder": "f1",
                "transcript": "t2",
                "workspace": "w1",
                "updatedBy": "u2",
            },
        ]

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)
    monkeypatch.setattr(commands, "fetch_workspace_items", fake_fetch_workspace_items)

    result = commands.command_list_projects(config)

    assert result["workspaceId"] == "workspace-uuid"
    assert result["count"] == 2
    assert "totalCount" not in result
    assert "totalPages" not in result
    assert [item["id"] for item in result["items"]] == ["p1", "p2"]
    for field in ("id", "createdAt", "updatedAt", "name", "description", "folder", "transcript"):
        assert field in result["items"][0]
    assert "workspace" not in result["items"][0]
    assert result["items"][0]["transcript"] == "t1"
    assert result["items"][1]["transcript"] == "t2"
    assert fetch_calls == [
        ("workspace-uuid", "projects"),
    ]


def test_command_list_folders_fetches_workspace_and_all_folders(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    fetch_calls: list[tuple[str, str]] = []

    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        assert api_url == "http://localhost:8000"
        assert api_token == "api-token"
        return "workspace-uuid"

    def fake_fetch_workspace_items(
        api_url: str,
        api_token: str,
        workspace_id: str,
        endpoint: str,
    ) -> list[dict[str, object]]:
        fetch_calls.append((workspace_id, endpoint))
        assert endpoint == "folders"
        return [
            {
                "id": "f1",
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": "2024-01-02T00:00:00Z",
                "name": "Alpha Folder",
                "description": "Top level",
                "parent": None,
                "workspace": "w1",
                "createdBy": "u1",
            },
            {
                "id": "f2",
                "createdAt": "2024-01-03T00:00:00Z",
                "updatedAt": "2024-01-04T00:00:00Z",
                "name": "Child Folder",
                "description": None,
                "parent": "f1",
                "workspace": "w1",
                "updatedBy": "u2",
            },
        ]

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)
    monkeypatch.setattr(commands, "fetch_workspace_items", fake_fetch_workspace_items)

    result = commands.command_list_folders(config)

    assert result["workspaceId"] == "workspace-uuid"
    assert result["count"] == 2
    assert "totalCount" not in result
    assert "totalPages" not in result
    assert [item["id"] for item in result["items"]] == ["f1", "f2"]
    for field in ("id", "createdAt", "updatedAt", "name", "description", "parent"):
        assert field in result["items"][0]
    assert "workspace" not in result["items"][0]
    assert result["items"][0]["parent"] is None
    assert result["items"][1]["parent"] == "f1"
    assert fetch_calls == [
        ("workspace-uuid", "folders"),
    ]


def test_command_create_project_uses_workspace_lookup_and_returns_filtered_project(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    request_calls: list[tuple[str, str, str, str, object, object]] = []

    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        assert api_url == "http://localhost:8000"
        assert api_token == "api-token"
        return "workspace-uuid"

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
    ) -> dict[str, object]:
        request_calls.append((api_url, api_token, method, path, json_body, expected_statuses))
        return {
            "id": "p1",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-02T00:00:00Z",
            "name": "My Project",
            "description": "Desc",
            "folder": None,
            "transcript": "t1",
            "workspace": "workspace-uuid",
            "createdBy": "u1",
        }

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)
    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    result = commands.command_create_project(config, name="My Project", description="Desc", workspace_id=None)

    assert request_calls == [
        (
            "http://localhost:8000",
            "api-token",
            "POST",
            "/folders/workspace-uuid/projects",
            {"name": "My Project", "description": "Desc"},
            {201},
        )
    ]
    assert result == {
        "id": "p1",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-02T00:00:00Z",
        "name": "My Project",
        "description": "Desc",
        "folder": None,
        "transcript": "t1",
    }


def test_command_create_project_uses_explicit_workspace_id(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    paths: list[str] = []

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
    ) -> dict[str, object]:
        paths.append(path)
        return {
            "id": "p2",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
            "name": "Explicit",
            "description": None,
            "folder": None,
            "transcript": "t2",
        }

    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    commands.command_create_project(config, name="Explicit", description=None, workspace_id="workspace-explicit")
    assert paths == ["/folders/workspace-explicit/projects"]


def test_command_create_folder_uses_folder_endpoint_and_returns_filtered_folder(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    request_calls: list[tuple[str, str, str, str, object, object]] = []

    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        assert api_url == "http://localhost:8000"
        assert api_token == "api-token"
        return "workspace-uuid"

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
    ) -> dict[str, object]:
        request_calls.append((api_url, api_token, method, path, json_body, expected_statuses))
        return {
            "id": "f1",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-02T00:00:00Z",
            "name": "My Folder",
            "description": "Desc",
            "parent": "parent-uuid",
            "workspace": "workspace-uuid",
            "createdBy": "u1",
        }

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)
    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    result = commands.command_create_folder(
        config,
        name="My Folder",
        description="Desc",
        parent="parent-uuid",
        workspace_id=None,
    )

    assert request_calls == [
        (
            "http://localhost:8000",
            "api-token",
            "POST",
            "/folders/workspace-uuid/folders",
            {"name": "My Folder", "description": "Desc", "parent": "parent-uuid"},
            {200, 201},
        )
    ]
    assert result == {
        "id": "f1",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-02T00:00:00Z",
        "name": "My Folder",
        "description": "Desc",
        "parent": "parent-uuid",
    }


def test_command_edit_project_patches_project_and_returns_filtered_fields(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    request_calls: list[tuple[str, str, str, str, object, object]] = []

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
    ) -> dict[str, object]:
        request_calls.append((api_url, api_token, method, path, json_body, expected_statuses))
        return {
            "id": "p1",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-03T00:00:00Z",
            "name": "Renamed",
            "description": None,
            "folder": None,
            "transcript": "t1",
            "workspace": "workspace-uuid",
        }

    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    result = commands.command_edit_project(
        config,
        project_id="project-uuid",
        name="Renamed",
        description=None,
        clear_description=True,
        folder=None,
        clear_folder=True,
    )

    assert request_calls == [
        (
            "http://localhost:8000",
            "api-token",
            "PATCH",
            "/projects/project-uuid",
            {"name": "Renamed", "description": None, "folder": None},
            {200},
        )
    ]
    assert result == {
        "id": "p1",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-03T00:00:00Z",
        "name": "Renamed",
        "description": None,
        "folder": None,
        "transcript": "t1",
    }


def test_command_edit_folder_patches_folder_and_returns_filtered_fields(
    monkeypatch: pytest.MonkeyPatch,
    config: core.RuntimeConfig,
) -> None:
    request_calls: list[tuple[str, str, str, str, object, object]] = []

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        params=None,
        json_body=None,
        expected_statuses=None,
    ) -> dict[str, object]:
        request_calls.append((api_url, api_token, method, path, json_body, expected_statuses))
        return {
            "id": "f1",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-03T00:00:00Z",
            "name": "Renamed Folder",
            "description": None,
            "parent": None,
            "workspace": "workspace-uuid",
        }

    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request)

    result = commands.command_edit_folder(
        config,
        folder_id="folder-uuid",
        name="Renamed Folder",
        description=None,
        clear_description=True,
        parent=None,
        clear_parent=True,
    )

    assert request_calls == [
        (
            "http://localhost:8000",
            "api-token",
            "PATCH",
            "/folders/folder-uuid",
            {"name": "Renamed Folder", "description": None, "parent": None},
            {200},
        )
    ]
    assert result == {
        "id": "f1",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-03T00:00:00Z",
        "name": "Renamed Folder",
        "description": None,
        "parent": None,
    }


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


def test_emit_output_table_renders_hosted_projects_collection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "projects": [
            {
                "id": "matter-id",
                "name": "library",
                "full_name": "/example/path/library",
                "org_id": "org_123",
                "session_count": 10,
            }
        ]
    }

    core.emit_output(payload, "table", command_name="list_matters")
    out = capsys.readouterr().out

    assert out == (
        "count: 1\n"
        "id\tname\tfull_name\n"
        "matter-id\tlibrary\t/example/path/library\n"
    )


def test_emit_output_table_renders_hosted_markdown_documents_collection(
    capsys: pytest.CaptureFixture[str],
) -> None:
    payload = {
        "documents": [
            {
                "id": "doc-id",
                "project": "/example/path/library",
                "title": "Doc Title",
                "plain_text_preview": "Preview text",
                "tags": "one, two",
            }
        ],
        "total": 1,
    }

    core.emit_output(payload, "table", command_name="list_md")
    out = capsys.readouterr().out

    assert out == (
        "count: 1\n"
        "id\tproject\ttitle\tplain_text_preview\ttags\n"
        "doc-id\t/example/path/library\tDoc Title\tPreview text\tone, two\n"
    )


def test_emit_output_table_renders_transcript_id_for_empty_list_speakers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    core.emit_output(
        {"transcriptId": "t1", "items": [], "count": 0},
        "table",
        command_name="list_speakers",
    )

    assert capsys.readouterr().out == "transcriptId: t1\ncount: 0\n"


def test_command_edit_project_requires_update_fields(config: core.RuntimeConfig) -> None:
    with pytest.raises(core.CliError, match="edit_project requires at least one field"):
        commands.command_edit_project(
            config,
            project_id="project-uuid",
            name=None,
            description=None,
            clear_description=False,
            folder=None,
            clear_folder=False,
        )


def test_command_edit_project_rejects_conflicting_nullable_flags(config: core.RuntimeConfig) -> None:
    with pytest.raises(core.CliError, match="Use either --description or --clear-description"):
        commands.command_edit_project(
            config,
            project_id="project-uuid",
            name=None,
            description="new",
            clear_description=True,
            folder=None,
            clear_folder=False,
        )

    with pytest.raises(core.CliError, match="Use either --folder or --clear-folder"):
        commands.command_edit_project(
            config,
            project_id="project-uuid",
            name=None,
            description=None,
            clear_description=False,
            folder="folder-uuid",
            clear_folder=True,
        )


def test_command_edit_folder_rejects_conflicting_nullable_flags(config: core.RuntimeConfig) -> None:
    with pytest.raises(core.CliError, match="Use either --description or --clear-description"):
        commands.command_edit_folder(
            config,
            folder_id="folder-uuid",
            name=None,
            description="new",
            clear_description=True,
            parent=None,
            clear_parent=False,
        )

    with pytest.raises(core.CliError, match="Use either --parent or --clear-parent"):
        commands.command_edit_folder(
            config,
            folder_id="folder-uuid",
            name=None,
            description=None,
            clear_description=False,
            parent="parent-uuid",
            clear_parent=True,
        )


def test_run_list_projects_does_not_require_meili_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    emitted = install_emit_output_capture(monkeypatch)

    def fake_command_list_projects(config: core.RuntimeConfig, *, full: bool = False) -> dict[str, object]:
        return {
            "workspaceId": "workspace-uuid",
            "items": [{"id": "p1", "name": "Alpha", "updatedAt": "2024-01-01T00:00:00Z", "folder": None}],
            "count": 1,
        }

    monkeypatch.setattr(cli, "command_list_projects", fake_command_list_projects)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "list_projects",
        ]
    )

    assert exit_code == 0
    assert emitted["format"] == "table"
    assert emitted["value"] == {
        "workspaceId": "workspace-uuid",
        "items": [{"id": "p1", "name": "Alpha", "updatedAt": "2024-01-01T00:00:00Z", "folder": None}],
        "count": 1,
    }


def test_run_list_projects_writes_rendered_output_file_and_saved_line(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    output_file = tmp_path / "nested" / "projects.tsv"

    def fake_command_list_projects(config: core.RuntimeConfig, *, full: bool = False) -> dict[str, object]:
        return {
            "workspaceId": "workspace-uuid",
            "items": [{"id": "p1", "name": "Alpha", "updatedAt": "2024-01-01T00:00:00Z", "folder": None}],
            "count": 1,
        }

    monkeypatch.setattr(cli, "command_list_projects", fake_command_list_projects)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "--output-file",
            str(output_file),
            "list_projects",
        ]
    )

    assert exit_code == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == f"Saved list_projects output to {output_file}\n"
    assert output_file.read_text(encoding="utf-8") == (
        "workspaceId: workspace-uuid\n"
        "count: 1\n"
        "id\tname\tupdatedAt\tfolder\n"
        "p1\tAlpha\t2024-01-01T00:00:00Z\t\n"
    )


def test_run_list_matters_does_not_require_caption_api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    monkeypatch.setenv("CLERK_API_KEY", "history-token")
    monkeypatch.setenv("ORGANIZATION_ID", "org_123")
    emitted = install_emit_output_capture(monkeypatch)

    def fake_command_list_matters(config: core.RuntimeConfig, args: object) -> dict[str, object]:
        return {
            "projects": [
                {
                    "id": "matter-id",
                    "name": "library",
                    "full_name": "/example/path/library",
                    "org_id": "org_123",
                    "session_count": 10,
                }
            ]
        }

    monkeypatch.setattr(cli, "command_list_matters", fake_command_list_matters)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "list_matters",
        ]
    )

    assert exit_code == 0
    assert emitted["format"] == "table"
    assert emitted["value"] == {
        "projects": [
            {
                "id": "matter-id",
                "name": "library",
                "full_name": "/example/path/library",
                "org_id": "org_123",
                "session_count": 10,
            }
        ]
    }


def test_run_list_folders_does_not_require_meili_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    emitted = install_emit_output_capture(monkeypatch)

    def fake_command_list_folders(config: core.RuntimeConfig, *, full: bool = False) -> dict[str, object]:
        return {
            "workspaceId": "workspace-uuid",
            "items": [{"id": "f1", "name": "Root", "updatedAt": "2024-01-01T00:00:00Z", "parent": None}],
            "count": 1,
        }

    monkeypatch.setattr(cli, "command_list_folders", fake_command_list_folders)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "list_folders",
        ]
    )

    assert exit_code == 0
    assert emitted["format"] == "table"
    assert emitted["value"] == {
        "workspaceId": "workspace-uuid",
        "items": [{"id": "f1", "name": "Root", "updatedAt": "2024-01-01T00:00:00Z", "parent": None}],
        "count": 1,
    }


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


def test_run_create_project_does_not_require_meili_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    emitted = install_emit_output_capture(monkeypatch)

    def fake_command_create_project(
        config: core.RuntimeConfig,
        *,
        name: str,
        description: str | None,
        workspace_id: str | None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        assert name == "My Project"
        assert description == "Desc"
        assert workspace_id is None
        return {
            "id": "p1",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
            "name": "My Project",
            "description": "Desc",
            "folder": None,
            "transcript": "t1",
        }

    monkeypatch.setattr(cli, "command_create_project", fake_command_create_project)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "create_project",
            "My Project",
            "--description",
            "Desc",
        ]
    )

    assert exit_code == 0
    assert emitted["format"] == "json"
    assert emitted["value"] == {
        "id": "p1",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "name": "My Project",
        "description": "Desc",
        "folder": None,
        "transcript": "t1",
    }


def test_run_create_folder_does_not_require_meili_url(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    set_runtime_env(monkeypatch, meili_url=None)
    emitted = install_emit_output_capture(monkeypatch)

    def fake_command_create_folder(
        config: core.RuntimeConfig,
        *,
        name: str,
        description: str | None,
        parent: str | None,
        workspace_id: str | None,
        dry_run: bool = False,
    ) -> dict[str, object]:
        assert name == "My Folder"
        assert description == "Desc"
        assert parent == "parent-uuid"
        assert workspace_id is None
        return {
            "id": "f1",
            "createdAt": "2024-01-01T00:00:00Z",
            "updatedAt": "2024-01-01T00:00:00Z",
            "name": "My Folder",
            "description": "Desc",
            "parent": "parent-uuid",
        }

    monkeypatch.setattr(cli, "command_create_folder", fake_command_create_folder)

    exit_code = cli.run(
        [
            "--env-file",
            "",
            "--cache-path",
            str(tmp_path / "search-token.json"),
            "create_folder",
            "My Folder",
            "--description",
            "Desc",
            "--parent",
            "parent-uuid",
        ]
    )

    assert exit_code == 0
    assert emitted["format"] == "json"
    assert emitted["value"] == {
        "id": "f1",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "name": "My Folder",
        "description": "Desc",
        "parent": "parent-uuid",
    }


def test_run_fails_when_api_url_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.setenv("CLERK_API_KEY", "api-token")
    monkeypatch.setenv("CAPTION_MEILI_URL", "https://configured.meili")

    with pytest.raises(core.CliError, match="Missing Caption API URL"):
        cli.run(["--env-file", "", "token"])


def test_run_fails_when_meili_url_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    monkeypatch.setenv("CAPTION_API_URL", "http://localhost:8000")
    monkeypatch.setenv("CLERK_API_KEY", "api-token")

    with pytest.raises(core.CliError, match="Missing Meilisearch URL"):
        cli.run(["--env-file", "", "token"])


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


def test_fetch_paginated_object_list_rejects_non_advancing_pagination(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    full_page = {"items": [{"channel": 0, "index": 0, "content": f"caption {i}"} for i in range(100)]}
    get_offsets: list[int] = []

    def fake_authorized_get_json(
        api_url: str,
        api_token: str,
        path: str,
        params=None,
        client=None,
    ) -> dict[str, object]:
        get_offsets.append(params["offset"])
        return full_page

    monkeypatch.setattr(commands, "_authorized_get_json", fake_authorized_get_json)

    with pytest.raises(core.CliError) as excinfo:
        commands._fetch_paginated_object_list("https://api", "token", "/transcripts/t1/captions")

    assert get_offsets == [0, 100]
    assert excinfo.value.exit_code == core.EXIT_UPSTREAM
    assert "pagination did not advance at offset 100" in excinfo.value.message


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


def test_capabilities_includes_speaker_commands() -> None:
    command_names = {command["name"] for command in cli.build_capabilities()["commands"]}
    assert {"assign_speakers", "list_speakers", "rename_speaker"} <= command_names
