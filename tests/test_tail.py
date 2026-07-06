from __future__ import annotations

import inspect
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Mapping

import pytest

import caption_cli.cli as cli
import caption_cli.commands as commands
import caption_cli.core as core


def _require_command_callable(name: str) -> Callable[..., Any]:
    target = getattr(commands, name, None)
    assert callable(target), f"caption tail implementation must expose caption_cli.commands.{name}"
    return target


def _install_authorized_payload(monkeypatch: pytest.MonkeyPatch, payload: Mapping[str, Any]) -> list[str]:
    paths: list[str] = []

    def fake_authorized_get(api_url: str, api_token: str, path: str, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
        assert api_url == "https://api.example.com/api"
        assert api_token == "api-token"
        paths.append(path)
        return payload

    def fake_authorized_request(
        api_url: str,
        api_token: str,
        method: str,
        path: str,
        *args: Any,
        **kwargs: Any,
    ) -> Mapping[str, Any]:
        assert method == "GET"
        return fake_authorized_get(api_url, api_token, path, *args, **kwargs)

    monkeypatch.setattr(commands, "_authorized_get", fake_authorized_get, raising=False)
    monkeypatch.setattr(commands, "_authorized_get_json", fake_authorized_get, raising=False)
    monkeypatch.setattr(commands, "_authorized_request", fake_authorized_request, raising=False)
    return paths


def _tail_spec() -> core.CommandSpec:
    for spec in cli._command_specs():
        if spec.name == "tail":
            return spec
    pytest.fail("caption tail must be present in the command spec table")


def _replace_tail_handler(
    monkeypatch: pytest.MonkeyPatch,
    handler: Callable[[core.RuntimeConfig, Any], Any],
) -> dict[str, bool]:
    specs = tuple(cli._command_specs())
    assert any(spec.name == "tail" for spec in specs), "caption tail must be present in _command_specs()"
    called = {"value": False}

    def wrapped(config: core.RuntimeConfig, args: Any) -> Any:
        called["value"] = True
        return handler(config, args)

    monkeypatch.setattr(
        cli,
        "_command_specs",
        lambda: tuple(replace(spec, handler=wrapped) if spec.name == "tail" else spec for spec in specs),
    )
    return called


class FakeSocketClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.init_args = args
        self.init_kwargs = kwargs
        self.handlers: dict[tuple[str | None, str], Callable[..., Any]] = {}
        self.emits: list[tuple[str, Any, str | None]] = []
        self.auth_payloads: list[Any] = []
        self.connect_url: str | None = None
        self.connect_kwargs: dict[str, Any] = {}
        self.connected = False

    def on(
        self,
        event: str,
        handler: Callable[..., Any] | None = None,
        *,
        namespace: str | None = None,
    ) -> Callable[..., Any]:
        def register(callback: Callable[..., Any]) -> Callable[..., Any]:
            self.handlers[(namespace, event)] = callback
            return callback

        if handler is None:
            return register
        return register(handler)

    def event(
        self,
        handler: Callable[..., Any] | None = None,
        *,
        namespace: str | None = None,
    ) -> Callable[..., Any]:
        def register(callback: Callable[..., Any]) -> Callable[..., Any]:
            self.handlers[(namespace, callback.__name__)] = callback
            return callback

        if handler is None:
            return register
        return register(handler)

    def connect(self, url: str, **kwargs: Any) -> None:
        self.connected = True
        self.connect_url = url
        self.connect_kwargs = kwargs
        auth = kwargs.get("auth")
        if callable(auth):
            self.auth_payloads.append(auth())
            self.auth_payloads.append(auth())
        self._invoke_event("ready")

    def emit(self, event: str, data: Any = None, *, namespace: str | None = None) -> None:
        self.emits.append((event, data, namespace))
        if event == "subscribe":
            self._invoke_event("subscribe", data, namespace=namespace)

    def disconnect(self) -> None:
        self.connected = False

    def wait(self) -> None:
        return None

    def sleep(self, seconds: float) -> None:
        return None

    def _invoke_event(self, event: str, payload: Any = None, *, namespace: str | None = "/events") -> None:
        handler = (
            self.handlers.get((namespace, event))
            or self.handlers.get((None, event))
            or self.handlers.get(("/events", event))
        )
        if handler is None:
            return
        if payload is not None:
            handler(payload)
        elif _handler_requires_payload(handler):
            handler({} if payload is None else payload)
        else:
            handler()


def _handler_requires_payload(handler: Callable[..., Any]) -> bool:
    signature = inspect.signature(handler)
    return any(
        parameter.default is inspect.Signature.empty
        and parameter.kind
        in {
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }
        for parameter in signature.parameters.values()
    )


def _install_fake_socketio(monkeypatch: pytest.MonkeyPatch) -> list[FakeSocketClient]:
    clients: list[FakeSocketClient] = []

    def client_factory(*args: Any, **kwargs: Any) -> FakeSocketClient:
        client = FakeSocketClient(*args, **kwargs)
        clients.append(client)
        return client

    fake_socketio = SimpleNamespace(
        Client=client_factory,
        exceptions=SimpleNamespace(ConnectionError=ConnectionError),
    )
    monkeypatch.setattr(commands, "socketio", fake_socketio, raising=False)
    return clients


def test_format_caption_line_uses_channel_names_indexes_and_collapsed_lines() -> None:
    format_caption_line = _require_command_callable("_format_caption_line")

    assert (
        format_caption_line(
            {
                "id": "caption-id-not-rendered",
                "channel": 0,
                "index": 2,
                "content": "We should ship\non Friday.",
                "createdAt": "2026-07-04T12:00:00Z",
            }
        )
        == "microphone-2: We should ship on Friday."
    )
    assert format_caption_line({"channel": 1, "index": 0, "content": "Loopback"}) == "loopback-0: Loopback"
    assert format_caption_line({"channel": 2, "content": "External"}) == "external: External"
    assert format_caption_line({"channel": 9, "content": "Unknown"}) == "9: Unknown"


def test_format_caption_line_keeps_ids_and_timestamps_out_of_stdout() -> None:
    format_caption_line = _require_command_callable("_format_caption_line")

    line = format_caption_line(
        {
            "id": "caption-123",
            "channel": 0,
            "index": None,
            "content": "hello",
            "createdAt": "2026-07-04T12:00:00Z",
            "updatedAt": "2026-07-04T12:01:00Z",
        }
    )

    assert line == "microphone: hello"
    assert "caption-123" not in line
    assert "2026-07-04" not in line


def test_fetch_events_token_uses_events_endpoint_and_validates_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetch_events_token = _require_command_callable("_fetch_events_token")
    paths = _install_authorized_payload(monkeypatch, {"token": "events-token"})

    assert fetch_events_token("https://api.example.com/api", "api-token") == "events-token"
    assert paths == ["/events"]


@pytest.mark.parametrize("payload", [{}, {"token": ""}, {"token": None}, {"token": 123}])
def test_fetch_events_token_rejects_missing_or_non_string_token(
    monkeypatch: pytest.MonkeyPatch,
    payload: Mapping[str, Any],
) -> None:
    fetch_events_token = _require_command_callable("_fetch_events_token")
    _install_authorized_payload(monkeypatch, payload)

    with pytest.raises(core.CliError) as excinfo:
        fetch_events_token("https://api.example.com/api", "api-token")

    assert excinfo.value.exit_code == core.EXIT_UPSTREAM
    assert "/events response missing string 'token'" in excinfo.value.message


def test_resolve_default_transcript_uses_most_recent_project_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_default_transcript = _require_command_callable("_resolve_default_transcript")

    def fake_fetch_current_workspace_id(api_url: str, api_token: str) -> str:
        assert api_url == "https://api.example.com/api"
        assert api_token == "api-token"
        return "workspace-1"

    def fake_fetch_workspace_items(
        api_url: str,
        api_token: str,
        workspace_id: str,
        endpoint: str,
    ) -> list[Mapping[str, Any]]:
        assert workspace_id == "workspace-1"
        assert endpoint == "projects"
        return [
            {
                "id": "project-old",
                "name": "Old",
                "updatedAt": "2026-01-01T00:00:00Z",
                "transcript": "transcript-old",
            },
            {
                "id": "project-new",
                "name": "New",
                "updatedAt": "2026-07-04T00:00:00Z",
                "transcript": "transcript-new",
            },
            {
                "id": "project-missing-updated-at",
                "name": "Missing updatedAt",
                "transcript": "transcript-missing-updated-at",
            },
        ]

    monkeypatch.setattr(commands, "fetch_current_workspace_id", fake_fetch_current_workspace_id)
    monkeypatch.setattr(commands, "fetch_workspace_items", fake_fetch_workspace_items)

    transcript_id, project = resolve_default_transcript("https://api.example.com/api", "api-token")

    assert transcript_id == "transcript-new"
    assert project["id"] == "project-new"


@pytest.mark.parametrize(
    ("projects", "message"),
    [
        ([], "no projects"),
        (
            [{"id": "project-1", "name": "No Transcript", "updatedAt": "2026-07-04T00:00:00Z"}],
            "transcript",
        ),
        (
            [{"id": "project-1", "name": "Bad Transcript", "updatedAt": "2026-07-04T00:00:00Z", "transcript": None}],
            "transcript",
        ),
    ],
)
def test_resolve_default_transcript_reports_empty_or_malformed_project_payloads(
    monkeypatch: pytest.MonkeyPatch,
    projects: list[Mapping[str, Any]],
    message: str,
) -> None:
    resolve_default_transcript = _require_command_callable("_resolve_default_transcript")
    monkeypatch.setattr(commands, "fetch_current_workspace_id", lambda api_url, api_token: "workspace-1")
    monkeypatch.setattr(commands, "fetch_workspace_items", lambda *args, **kwargs: projects)

    with pytest.raises(core.CliError) as excinfo:
        resolve_default_transcript("https://api.example.com/api", "api-token")

    assert excinfo.value.exit_code == core.EXIT_UPSTREAM
    assert message in excinfo.value.message.lower()


@pytest.mark.parametrize(
    ("api_url", "expected_base", "expected_socketio_path"),
    [
        ("https://api.example.com", "https://api.example.com", "socket.io"),
        ("https://api.example.com/api", "https://api.example.com", "/api/socket.io"),
        ("https://api.example.com/api/", "https://api.example.com", "/api/socket.io"),
    ],
)
def test_command_tail_derives_socketio_target_and_skips_default_resolution_for_explicit_transcript(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
    api_url: str,
    expected_base: str,
    expected_socketio_path: str,
) -> None:
    command_tail = _require_command_callable("command_tail")
    clients = _install_fake_socketio(monkeypatch)
    token_calls = {"count": 0}

    def fake_fetch_events_token(
        api_url_arg: str, api_token: str, visa_token: str | None = None
    ) -> str:
        assert api_url_arg == api_url
        assert api_token == "api-token"
        assert visa_token is None
        token_calls["count"] += 1
        if token_calls["count"] == 1:
            return "initial-token"
        if token_calls["count"] == 2:
            return "connect-token"
        raise RuntimeError("events token refresh failed")

    def fail_default_resolution(*args: Any, **kwargs: Any) -> tuple[str, Mapping[str, Any]]:
        raise AssertionError("explicit transcript_id must skip default transcript resolution")

    def fake_fetch_captions(api_url_arg: str, api_token: str, path: str, **kwargs: Any) -> list[Mapping[str, Any]]:
        assert api_url_arg == api_url
        assert api_token == "api-token"
        assert path == "/transcripts/transcript-1/captions"
        return [{"id": "caption-1", "channel": 0, "index": 1, "content": "Backfill row"}]

    monkeypatch.setattr(commands, "_fetch_events_token", fake_fetch_events_token, raising=False)
    monkeypatch.setattr(commands, "_resolve_default_transcript", fail_default_resolution, raising=False)
    monkeypatch.setattr(commands, "_fetch_paginated_object_list", fake_fetch_captions, raising=False)

    test_config = core.RuntimeConfig(
        api_url=api_url,
        api_token="api-token",
        meili_url=None,
        cache_path=tmp_path / "search-token.json",
        output="plain",
    )

    command_tail(test_config, transcript_id="transcript-1", duration=0.01, max_events=1, idle_timeout=None)

    captured = capsys.readouterr()
    assert captured.out == "microphone-1: Backfill row\n"
    assert "events token refresh failed, reusing previous" in captured.err
    assert len(clients) == 1
    client = clients[0]
    assert client.init_kwargs == {"reconnection": True}
    assert client.connect_url == expected_base
    assert client.connect_kwargs["namespaces"] == ["/events"]
    assert client.connect_kwargs["socketio_path"] == expected_socketio_path
    assert client.connect_kwargs["transports"] == ["websocket"]
    assert client.auth_payloads == [{"token": "connect-token"}, {"token": "connect-token"}]
    assert ("subscribe", {"subjectType": "transcript", "id": "transcript-1"}, "/events") in client.emits


def test_command_tail_subscribes_on_connect_when_ready_is_absent(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    command_tail = _require_command_callable("command_tail")

    class ConnectOnlySocketClient(FakeSocketClient):
        def connect(self, url: str, **kwargs: Any) -> None:
            self.connected = True
            self.connect_url = url
            self.connect_kwargs = kwargs
            auth = kwargs.get("auth")
            if callable(auth):
                self.auth_payloads.append(auth())
            self._invoke_event("connect")

    clients: list[ConnectOnlySocketClient] = []

    def socket_factory() -> ConnectOnlySocketClient:
        client = ConnectOnlySocketClient()
        clients.append(client)
        return client

    monkeypatch.setattr(commands, "_fetch_events_token", lambda *args, **kwargs: "events-token", raising=False)
    monkeypatch.setattr(
        commands,
        "_fetch_paginated_object_list",
        lambda *args, **kwargs: [{"id": "caption-1", "channel": 0, "content": "connect row"}],
        raising=False,
    )

    test_config = core.RuntimeConfig(
        api_url="https://api.example.com/api",
        api_token="api-token",
        meili_url=None,
        cache_path=tmp_path / "search-token.json",
        output="plain",
    )

    command_tail(
        test_config,
        transcript_id="transcript-1",
        duration=None,
        max_events=1,
        idle_timeout=None,
        socketio_client_factory=socket_factory,
    )

    assert capsys.readouterr().out == "microphone: connect row\n"
    assert clients[0].emits == [("subscribe", {"subjectType": "transcript", "id": "transcript-1"}, "/events")]


def test_parse_args_for_tail_preserves_explicit_output_signal() -> None:
    args = cli.parse_args(["--env-file", "", "tail", "transcript-1", "--max-events", "1"])
    assert args.command == "tail"
    assert args.transcript_id == "transcript-1"
    assert args.max_events == 1
    assert args.output == "plain"
    assert args.output_supplied is False

    explicit = cli.parse_args(["--env-file", "", "--output", "json", "tail", "transcript-1", "--max-events", "1"])
    assert explicit.output == "json"
    assert explicit.output_supplied is True


@pytest.mark.parametrize(
    ("global_args", "flag", "message_hint"),
    [
        (["--output", "json"], "--output", "format"),
        (["--output-file", "tail.txt"], "--output-file", "stream"),
    ],
)
def test_run_tail_rejects_stream_incompatible_global_output_flags_before_handler(
    monkeypatch: pytest.MonkeyPatch,
    global_args: list[str],
    flag: str,
    message_hint: str,
) -> None:
    _tail_spec()
    called = _replace_tail_handler(monkeypatch, lambda config, args: None)
    monkeypatch.setenv("CAPTION_API_URL", "https://api.example.com")
    monkeypatch.setenv("CLERK_API_KEY", "api-token")

    with pytest.raises(core.CliError) as excinfo:
        cli.run(["--env-file", "", *global_args, "tail", "transcript-1", "--max-events", "1"])

    assert excinfo.value.exit_code == core.EXIT_USER_INPUT
    if flag == "--output-file":
        assert flag in excinfo.value.message
    assert message_hint in excinfo.value.message
    assert called["value"] is False


def test_run_tail_returns_zero_without_rendering_handler_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_tail_handler(config: core.RuntimeConfig, args: Any) -> None:
        assert config.api_url == "https://api.example.com"
        assert config.api_token == "api-token"
        assert config.output == "plain"
        assert args.transcript_id == "transcript-1"
        return None

    called = _replace_tail_handler(monkeypatch, fake_tail_handler)
    monkeypatch.setenv("CAPTION_API_URL", "https://api.example.com")
    monkeypatch.setenv("CLERK_API_KEY", "api-token")
    monkeypatch.setattr(cli, "emit_output", lambda *args, **kwargs: pytest.fail("tail must not use emit_output"))

    assert cli.run(["--env-file", "", "tail", "transcript-1", "--max-events", "1"]) == 0
    assert called["value"] is True


def test_build_auth_headers_requires_some_credential() -> None:
    with pytest.raises(core.CliError) as excinfo:
        core._build_auth_headers(None, None)
    assert excinfo.value.exit_code == core.EXIT_CONFIG


def test_guide_contract_includes_tail_stream_contract() -> None:
    commands_by_name = {command["name"]: command for command in cli.build_capabilities()["commands"]}
    assert "tail" in commands_by_name

    tail = commands_by_name["tail"]
    assert tail["needs_api"] is True
    assert tail["needs_meili"] is False
    assert tail["default_output"] == "plain"
    assert tail["usage"].startswith("caption tail")
    assert "--duration" in tail["usage"]
    assert "--max-events" in tail["usage"]
    assert "--idle-timeout" in tail["usage"]
    notes = "\n".join(tail["notes"])
    notes_lower = notes.lower()
    assert "{channel" in notes
    assert "{content}" in notes
    assert "stdout" in notes_lower
    assert "stderr" in notes_lower
