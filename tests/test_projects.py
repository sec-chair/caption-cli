from __future__ import annotations

import json
from pathlib import Path

import pytest
from caption_helpers import install_emit_output_capture, set_runtime_env

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


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


def test_list_projects_command_is_available() -> None:
    args = cli.parse_args(["list_projects"])
    assert args.command == "list_projects"


def test_list_folders_command_is_available() -> None:
    args = cli.parse_args(["list_folders"])
    assert args.command == "list_folders"


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
