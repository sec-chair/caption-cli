from __future__ import annotations

import json
from pathlib import Path

import pytest
from caption_helpers import install_emit_output_capture, set_runtime_env

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


class FakeAuthError(Exception):
    def __init__(self) -> None:
        self.status_code = 401
        self.code = "invalid_api_key"
        self.message = "invalid_api_key"
        super().__init__(self.message)


def write_cache(path: Path, token: str = "cached-token", url: str = "https://cached.meili") -> None:
    path.write_text(json.dumps({"token": token, "url": url}), encoding="utf-8")


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
