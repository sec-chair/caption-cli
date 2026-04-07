from __future__ import annotations

from pathlib import Path

import pytest

import setup_claude


def test_build_env_values_collects_root_keys_org_id_and_org_credentials() -> None:
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

    result = setup_claude.build_env_values(payload)

    assert result.env_values == {
        "CAPTION_API_URL": "https://dev-api.caption.fyi",
        "CAPTION_MEILI_URL": "https://meili.example.com",
        "ORGANIZATION_ID": "org_123",
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

    result = setup_claude.build_env_values(payload)

    assert result.env_values == {
        "CAPTION_API_URL": "https://dev-api.caption.fyi",
        "CAPTION_MEILI_URL": "https://meili.example.com",
    }
    assert result.skipped_null_keys == ("CLERK_API_KEY",)


def test_choose_organization_payload_prompts_and_filters_to_selected_org(capsys: pytest.CaptureFixture[str]) -> None:
    payload = {
        "organizations": [
            {
                "organization_id": "org_123",
                "organization_name": "Vela Wood",
                "credentials": [{"name": "artifact_api_token", "value": "artifact-token"}],
            },
            {
                "organization_id": "org_456",
                "organization_name": "Acme",
                "credentials": [{"name": "artifact_api_token", "value": "acme-token"}],
            },
        ]
    }

    prompts: list[str] = []

    def fake_prompt(message: str) -> str:
        prompts.append(message)
        return "2"

    selected_payload = setup_claude.choose_organization_payload(payload, prompt=fake_prompt)

    assert selected_payload["organizations"] == [payload["organizations"][1]]
    assert prompts == ["Select organization to load [1-2]: "]
    assert capsys.readouterr().out == (
        "Multiple organizations found. Select which organization's credentials to load:\n"
        "  1. Vela Wood: org_123\n"
        "  2. Acme: org_456\n"
    )


def test_choose_organization_payload_reprompts_on_invalid_selection(capsys: pytest.CaptureFixture[str]) -> None:
    payload = {
        "organizations": [
            {"organization_id": "org_123", "organization_name": "Vela Wood", "credentials": []},
            {"organization_id": "org_456", "organization_name": "Acme", "credentials": []},
        ]
    }

    responses = iter(["", "x", "3", "1"])

    selected_payload = setup_claude.choose_organization_payload(payload, prompt=lambda _: next(responses))

    assert selected_payload["organizations"] == [payload["organizations"][0]]
    assert capsys.readouterr().out == (
        "Multiple organizations found. Select which organization's credentials to load:\n"
        "  1. Vela Wood: org_123\n"
        "  2. Acme: org_456\n"
        "Enter the number of the organization to load.\n"
        "Enter a valid number.\n"
        "Enter a number between 1 and 2.\n"
    )


def test_write_env_file_appends_organization_id(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"

    result = setup_claude.write_env_file(env_file, {"ORGANIZATION_ID": "org_123"})

    assert env_file.read_text(encoding="utf-8") == "ORGANIZATION_ID='org_123'\n"
    assert result.appended_new_keys == ("ORGANIZATION_ID",)
    assert result.appended_conflicting_keys == ()
    assert result.skipped_existing_keys == ()
