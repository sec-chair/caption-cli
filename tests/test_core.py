from __future__ import annotations

from pathlib import Path

import httpx
import pytest

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


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
        core._authorized_request(
            "http://localhost:8000",
            "api-token",
            "GET",
            "/projects/missing",
            client=httpx.Client(transport=not_found_transport),
        )
    assert excinfo.value.exit_code == core.EXIT_NOT_FOUND

    server_error_transport = httpx.MockTransport(lambda request: httpx.Response(500, text="boom"))
    with pytest.raises(core.CliError) as excinfo:
        core._authorized_request(
            "http://localhost:8000",
            "api-token",
            "GET",
            "/projects",
            client=httpx.Client(transport=server_error_transport),
        )
    assert excinfo.value.exit_code == core.EXIT_UPSTREAM


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
        visa_token=None,
    ) -> dict[str, object]:
        get_offsets.append(params["offset"])
        return full_page

    monkeypatch.setattr(commands, "_authorized_get_json", fake_authorized_get_json)

    with pytest.raises(core.CliError) as excinfo:
        commands._fetch_paginated_object_list("https://api", "token", "/transcripts/t1/captions")

    assert get_offsets == [0, 100]
    assert excinfo.value.exit_code == core.EXIT_UPSTREAM
    assert "pagination did not advance at offset 100" in excinfo.value.message
