from __future__ import annotations

import pytest

import caption_cli.cli as cli


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
