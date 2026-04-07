from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

import caption_cli.agentsview as agentsview
import caption_cli.cli as cli
import caption_cli.core as core


def test_md_commands_parse() -> None:
    create_args = cli.parse_args(
        [
            "create_md",
            "README.md",
            "--project-name",
            "Probe",
            "--title",
            "Title",
            "--org-id",
            "org_123",
        ]
    )
    assert create_args.command == "create_md"
    assert create_args.markdown_file == "README.md"
    assert create_args.project_name == "Probe"
    assert create_args.title == "Title"
    assert create_args.output == "json"

    list_args = cli.parse_args(
        [
            "list_md",
            "--project",
            "Alpha",
            "--exclude-project",
            "Archive",
            "--tag",
            "one",
            "--tag",
            "two,three",
            "--created-by",
            "user_1",
            "--sort",
            "recent",
            "--cursor",
            "next",
            "--limit",
            "50",
        ]
    )
    assert list_args.command == "list_md"
    assert list_args.tag == ["one", "two,three"]
    assert list_args.created_by == ["user_1"]
    assert list_args.limit == 50
    assert list_args.output == "json"

    get_args = cli.parse_args(["get_md", "doc-id"])
    assert get_args.command == "get_md"
    assert get_args.id == "doc-id"
    assert get_args.output == "md"
    assert get_args.cache_dir == Path("caption_cache")

    matters_args = cli.parse_args(["list_matters", "--include-one-shot"])
    assert matters_args.command == "list_matters"
    assert matters_args.include_one_shot is True
    assert matters_args.output == "table"


def test_edit_md_command_is_removed() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["edit_md", "doc-id", "README.md", "--project-id", "project-id"])


def test_list_md_rejects_invalid_sort() -> None:
    with pytest.raises(SystemExit):
        cli.parse_args(["list_md", "--sort", "oldest"])


def test_md_run_does_not_require_caption_api_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    markdown_file = tmp_path / "README.md"
    markdown_file.write_text("# Hello\n", encoding="utf-8")
    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    monkeypatch.delenv("CLERK_API_KEY", raising=False)
    monkeypatch.delenv("ORGANIZATION_ID", raising=False)
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
    monkeypatch.setattr(cli, "command_create_md", lambda config, args: {"ok": True, "file": args.markdown_file})

    exit_code = cli.run(["create_md", str(markdown_file), "--org-id", "org_123"])

    assert exit_code == 0
    assert emitted["value"] == {"ok": True, "file": str(markdown_file)}
    assert emitted["format"] == "json"
    assert emitted["command_name"] == "create_md"


def test_create_md_uses_expected_request_contract(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    markdown_file = tmp_path / "README.md"
    markdown_file.write_text("# Hello\n", encoding="utf-8")
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://history.caption.fyi/api/v1/projects/md"
        assert request.headers["Authorization"] == "Bearer env-token"
        assert request.headers["X-Agentsview-Org"] == "env-org"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["User-Agent"] == "caption-cli"
        assert json.loads(request.content) == {
            "raw_markdown": "# Hello\n",
            "project_name": "Probe",
            "title": "README.md",
        }
        return httpx.Response(
            status_code=201,
            headers={"content-type": "application/json"},
            json={
                "id": "doc-id",
                "project_id": "project-id",
                "raw_markdown": "m" * 101,
                "plain_text": "p" * 101,
            },
        )

    args = cli.parse_args(
        [
            "--env-file",
            "",
            "create_md",
            str(markdown_file),
            "--project-name",
            "Probe",
        ]
    )
    result = agentsview.command_create_md(None, args, transport=httpx.MockTransport(handler))

    assert result == {
        "id": "doc-id",
        "project_id": "project-id",
        "raw_markdown": "m" * 100,
        "plain_text": "p" * 100,
    }


def test_create_md_honors_explicit_title(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    markdown_file = tmp_path / "README.md"
    markdown_file.write_text("# Hello\n", encoding="utf-8")
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.content)["title"] == "Title"
        return httpx.Response(status_code=201, headers={"content-type": "application/json"}, json={"id": "doc-id"})

    args = cli.parse_args(["--env-file", "", "create_md", str(markdown_file), "--title", "Title"])
    result = agentsview.command_create_md(None, args, transport=httpx.MockTransport(handler))

    assert result == {"id": "doc-id"}


def test_list_md_uses_expected_query_params(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == (
            "https://history.caption.fyi/api/v1/md?"
            "project=Alpha&exclude_project=Archive&sort=most_starred&cursor=next&tag=one%2Ctwo%2Cthree&"
            "created_by=user_1%2Cuser_2&limit=25"
        )
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={
                "documents": [
                    {
                        "id": "doc-id",
                        "project_id": "project-id",
                        "project": {"id": "project-id", "name": "Alpha", "full_name": "/matters/Alpha"},
                        "created_by": "user_1",
                        "title": "Doc Title",
                        "plain_text_preview": "Preview text",
                        "created_at": "2026-05-01T19:23:42Z",
                        "updated_at": "2026-05-01T19:23:42Z",
                        "star_count": 3,
                        "tags": ["one", "two"],
                    }
                ],
                "total": 1,
            },
        )

    args = cli.parse_args(
        [
            "--env-file",
            "",
            "list_md",
            "--project",
            "Alpha",
            "--exclude-project",
            "Archive",
            "--tag",
            "one",
            "--tag",
            "two,three",
            "--created-by",
            "user_1,user_2",
            "--sort",
            "most_starred",
            "--cursor",
            "next",
            "--limit",
            "25",
        ]
    )
    result = agentsview.command_list_md(None, args, transport=httpx.MockTransport(handler))

    assert result == {
        "documents": [
            {
                "id": "doc-id",
                "project": "/matters/Alpha",
                "title": "Doc Title",
                "plain_text_preview": "Preview text",
                "tags": "one, two",
            }
        ],
        "total": 1,
    }


def test_list_matters_uses_expected_request_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://history.caption.fyi/api/v1/projects?include_one_shot=true"
        assert request.headers["Authorization"] == "Bearer env-token"
        assert request.headers["X-Agentsview-Org"] == "env-org"
        assert request.headers["Accept"] == "application/json"
        assert request.headers["Content-Type"] == "application/json"
        assert request.headers["User-Agent"] == "caption-cli"
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={
                "projects": [
                    {
                        "id": "019e0000-0000-7000-8000-000000000000",
                        "name": "library",
                        "full_name": "/example/path/library",
                        "org_id": "org_abc",
                        "session_count": 10,
                    }
                ]
            },
        )

    args = cli.parse_args(["--env-file", "", "list_matters", "--include-one-shot"])
    result = agentsview.command_list_matters(None, args, transport=httpx.MockTransport(handler))

    assert result == {
        "projects": [
            {
                "id": "019e0000-0000-7000-8000-000000000000",
                "name": "library",
                "full_name": "/example/path/library",
            }
        ]
    }


def test_get_md_uses_expected_request_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert str(request.url) == "https://history.caption.fyi/api/v1/md/doc-id"
        return httpx.Response(
            status_code=200,
            headers={"content-type": "application/json"},
            json={"id": "doc-id", "title": "Hello.md", "raw_markdown": "# Hello"},
        )

    args = cli.parse_args(["--env-file", "", "get_md", "doc-id"])
    result = agentsview.command_get_md(None, args, transport=httpx.MockTransport(handler))

    assert result == {"id": "doc-id", "title": "Hello.md", "raw_markdown": "# Hello"}


def test_get_md_requires_raw_markdown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    args = cli.parse_args(["--env-file", "", "get_md", "doc-id"])

    with pytest.raises(core.CliError, match=r"response missing string 'raw_markdown'"):
        agentsview.command_get_md(
            None,
            args,
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    status_code=200,
                    headers={"content-type": "application/json"},
                    json={"id": "doc-id"},
                )
            ),
        )


def test_run_get_md_writes_default_cache_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    monkeypatch.delenv("CLERK_API_KEY", raising=False)
    monkeypatch.delenv("ORGANIZATION_ID", raising=False)

    monkeypatch.setattr(
        cli,
        "command_get_md",
        lambda config, args: {"id": "doc/id", "title": "Title Already.md", "raw_markdown": "# Hello"},
    )

    exit_code = cli.run(["--env-file", "", "get_md", "doc/id"])

    output_file = tmp_path / "caption_cache" / "md" / "Title_Already.md"
    assert exit_code == 0
    assert capsys.readouterr().out == "Saved get_md output to caption_cache/md/Title_Already.md\n"
    assert output_file.read_text(encoding="utf-8") == "# Hello\n"


def test_run_get_md_strips_repeated_markdown_suffixes_from_default_filename(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    monkeypatch.delenv("CLERK_API_KEY", raising=False)
    monkeypatch.delenv("ORGANIZATION_ID", raising=False)

    monkeypatch.setattr(
        cli,
        "command_get_md",
        lambda config, args: {"id": "doc-id", "title": "Case Notes.MD.md", "raw_markdown": "# Hello"},
    )

    exit_code = cli.run(["--env-file", "", "get_md", "doc-id"])

    output_file = tmp_path / "caption_cache" / "md" / "Case_Notes.md"
    assert exit_code == 0
    assert capsys.readouterr().out == "Saved get_md output to caption_cache/md/Case_Notes.md\n"
    assert output_file.read_text(encoding="utf-8") == "# Hello\n"


def test_run_get_md_honors_output_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv("CAPTION_API_URL", raising=False)
    monkeypatch.delenv("CAPTION_MEILI_URL", raising=False)
    monkeypatch.delenv("CLERK_API_KEY", raising=False)
    monkeypatch.delenv("ORGANIZATION_ID", raising=False)
    output_file = tmp_path / "docs" / "custom.md"

    monkeypatch.setattr(cli, "command_get_md", lambda config, args: {"title": "Ignored", "raw_markdown": "# Hello"})

    exit_code = cli.run(["--env-file", "", "--output-file", str(output_file), "get_md", "doc-id"])

    assert exit_code == 0
    assert capsys.readouterr().out == f"Saved get_md output to {output_file}\n"
    assert output_file.read_text(encoding="utf-8") == "# Hello\n"


def test_md_commands_require_history_auth(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    markdown_file = tmp_path / "README.md"
    markdown_file.write_text("# Hello\n", encoding="utf-8")
    monkeypatch.delenv("CLERK_API_KEY", raising=False)
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")

    args = cli.parse_args(["--env-file", "", "create_md", str(markdown_file)])
    with pytest.raises(core.CliError, match=r"Missing Clerk API key \(--clerk-api-key or CLERK_API_KEY\)"):
        agentsview.command_create_md(None, args, transport=httpx.MockTransport(lambda request: httpx.Response(201)))


def test_md_command_rejects_spa_html_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLERK_API_KEY", "env-token")
    monkeypatch.setenv("ORGANIZATION_ID", "env-org")
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            status_code=200,
            headers={"content-type": "text/html; charset=utf-8"},
            text="<!doctype html><title>AgentsView</title>",
        )
    )

    args = cli.parse_args(["--env-file", "", "get_md", "doc-id"])
    with pytest.raises(core.CliError, match="returned non-JSON response"):
        agentsview.command_get_md(None, args, transport=transport)
