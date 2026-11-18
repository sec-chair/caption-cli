from __future__ import annotations

from pathlib import Path

import pytest

import caption_cli.core as core


@pytest.fixture
def config(tmp_path: Path) -> core.RuntimeConfig:
    return core.RuntimeConfig(
        api_url="http://localhost:8000",
        api_token="api-token",
        meili_url="https://configured.meili",
        cache_path=tmp_path / "search-token.json",
        output="json",
    )
