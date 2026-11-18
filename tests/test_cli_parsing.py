from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

import caption_cli.cli as cli
import caption_cli.core as core


def test_run_guide_json_emits_machine_readable_contract_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for env_var in ("CAPTION_API_URL", "CLERK_API_KEY", "CAPTION_MEILI_URL"):
        monkeypatch.delenv(env_var, raising=False)

    exit_code = cli.run(["--env-file", "", "--output", "json", "guide"])

    captured = capsys.readouterr()
    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["tool"] == "caption"
    assert payload["contract_version"]
    command_names = [command["name"] for command in payload["commands"]]
    assert "guide" in command_names
    assert "doctor" in command_names
    assert "search" in command_names
    assert payload["exit_codes"]["0"]
    assert payload["exit_codes"]["2"]
    assert "CAPTION_API_URL" in payload["env_vars"]
    search_command = next(command for command in payload["commands"] if command["name"] == "search")
    assert search_command["usage"].startswith("caption search")
    assert search_command["default_output"] == "table"


def test_guide_defaults_to_md_output() -> None:
    assert cli.parse_args(["guide"]).output == "md"


def test_top_level_help_documents_exit_codes(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["-h"])

    output = capsys.readouterr().out
    assert "Exit codes" in output
    assert "configuration error" in output
    assert "upstream failure" in output


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


def test_command_default_outputs_are_applied() -> None:
    assert cli.parse_args(["doctor"]).output == "plain"
    assert cli.parse_args(["search", "term"]).output == "table"
    assert cli.parse_args(["list_projects"]).output == "table"
    assert cli.parse_args(["list_folders"]).output == "table"
    assert cli.parse_args(["list_speakers", "t1"]).output == "table"
    assert (
        cli.parse_args(
            ["assign_speakers", "--transcript-id", "t1", "--channel", "0", "--name", "Alice"]
        ).output
        == "json"
    )
    assert cli.parse_args(["rename_speaker", "p1", "s1", "--name", "Bob"]).output == "json"
    assert cli.parse_args(["create_project", "My Project"]).output == "json"


def test_parse_args_accepts_output_file(tmp_path: Path) -> None:
    output_file = tmp_path / "out.txt"

    args = cli.parse_args(["--output-file", str(output_file), "list_projects"])

    assert args.output_file == output_file


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


def test_run_guide_prints_agent_handbook_offline(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    for env_var in ("CAPTION_API_URL", "CLERK_API_KEY", "CAPTION_MEILI_URL"):
        monkeypatch.delenv(env_var, raising=False)

    exit_code = cli.run(["--env-file", "", "guide"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "# caption — agent guide" in output
    assert "## Global options" in output
    assert "## Exit codes" in output
    assert "## Environment" in output
    assert "### search" in output
    assert "- requires: Caption API (CAPTION_API_URL), Meilisearch (CAPTION_MEILI_URL)" in output
    assert "caption --output json guide" in output


def test_removed_doc_commands_error_as_usage() -> None:
    for legacy in (["capabilities"], ["robot-docs", "guide"]):
        with pytest.raises(SystemExit) as excinfo:
            cli.parse_args(legacy)
        assert excinfo.value.code == core.EXIT_USAGE


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
    assert "caption guide" in output
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


def test_guide_contract_includes_speaker_commands() -> None:
    command_names = {command["name"] for command in cli.build_capabilities()["commands"]}
    assert {"assign_speakers", "list_speakers", "rename_speaker"} <= command_names


def test_bound_command_params_have_matching_flags() -> None:
    # _bind passes args by name and skips unmatched ones; a required parameter
    # without a same-named flag would only fail at call time.
    _, specs, subparsers = cli.build_parser(cli.default_env_file())

    for name, spec in specs.items():
        if spec.handler.__closure__ is None:
            continue

        command = next(
            cell.cell_contents for cell in spec.handler.__closure__ if callable(cell.cell_contents)
        )
        dests = {action.dest for action in subparsers[name]._actions}
        params = list(inspect.signature(command).parameters.values())[1:]
        unmatched = [
            param.name
            for param in params
            if param.default is inspect.Parameter.empty and param.name not in dests
        ]

        assert unmatched == [], f"{name}: no flag for required parameter(s) {unmatched}"
