from __future__ import annotations

from pathlib import Path

from dotenv import dotenv_values

import claude_setup


def test_build_env_values_collects_root_keys_and_org_credentials() -> None:
    payload = {
        "primary_email_address": "alin@velawood.com",
        "organizations": [
            {
                "organization_id": "org_123",
                "organization_name": "Vela Wood",
                "role": "org:admin",
                "credentials": [
                    {"name": "artifact_api_token", "value": "artifact-token"},
                    {"name": "matters_db", "value": "postgres://user:pass@db.example.com/app"},
                    {"service": {"nd_api_key": "nd-key"}},
                ],
            }
        ],
        "clerk_api_key": None,
        "caption_api_url": "https://dev-api.caption.fyi",
        "caption_meili_url": "https://meili.example.com",
    }

    result = claude_setup.build_env_values(payload, "setup-token")

    assert result.env_values == {
        "CAPTION_TOKEN": "setup-token",
        "CAPTION_API_URL": "https://dev-api.caption.fyi",
        "CAPTION_MEILI_URL": "https://meili.example.com",
        "ARTIFACT_API_TOKEN": "artifact-token",
        "MATTERS_DB": "postgres://user:pass@db.example.com/app",
        "SERVICE_ND_API_KEY": "nd-key",
    }
    assert result.skipped_null_keys == ("CLERK_API_KEY",)


def test_build_env_values_does_not_fill_null_root_key_with_auth_token() -> None:
    payload = {
        "primary_email_address": "alin@velawood.com",
        "organizations": [],
        "clerk_api_key": None,
        "caption_api_url": "https://dev-api.caption.fyi",
        "caption_meili_url": "https://meili.example.com",
    }

    result = claude_setup.build_env_values(payload, "setup-token")

    assert result.env_values == {
        "CAPTION_TOKEN": "setup-token",
        "CAPTION_API_URL": "https://dev-api.caption.fyi",
        "CAPTION_MEILI_URL": "https://meili.example.com",
    }
    assert result.skipped_null_keys == ("CLERK_API_KEY",)


def test_write_env_file_append_only_preserves_conflicts(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CLERK_API_KEY=old-token\n", encoding="utf-8")

    result = claude_setup.write_env_file(
        env_file,
        {
            "CLERK_API_KEY": "new-token",
            "CAPTION_API_URL": "https://dev-api.caption.fyi",
        },
        mode="append",
    )

    assert dotenv_values(env_file) == {
        "CLERK_API_KEY": "old-token",
        "CAPTION_API_URL": "https://dev-api.caption.fyi",
    }
    assert result.added_keys == ("CAPTION_API_URL",)
    assert result.updated_keys == ()
    assert result.preserved_conflicts == ("CLERK_API_KEY",)


def test_write_env_file_overwrite_updates_conflicts(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("CLERK_API_KEY=old-token\n", encoding="utf-8")

    result = claude_setup.write_env_file(
        env_file,
        {
            "CLERK_API_KEY": "new-token",
            "CAPTION_API_URL": "https://dev-api.caption.fyi",
        },
        mode="overwrite",
    )

    assert dotenv_values(env_file) == {
        "CLERK_API_KEY": "new-token",
        "CAPTION_API_URL": "https://dev-api.caption.fyi",
    }
    assert result.added_keys == ("CAPTION_API_URL",)
    assert result.updated_keys == ("CLERK_API_KEY",)
    assert result.preserved_conflicts == ()
