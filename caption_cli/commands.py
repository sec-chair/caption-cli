from __future__ import annotations

import os
import re
import sys
import uuid
from typing import Any, Callable, Mapping

import httpx
import meilisearch

from caption_cli import agentsview
from caption_cli.core import (
    CliError,
    RuntimeConfig,
    _authorized_get_list_of_objects,
    _authorized_get_text,
    _authorized_request,
    _folder_view,
    _project_view,
    _require_api_token,
    _require_api_url,
    _require_cached_or_fresh_token,
    _run_with_single_auth_retry,
    _truncate_for_cell,
    fetch_current_workspace_id,
    fetch_search_token,
    fetch_workspace_items,
    resolve_meili_url,
    save_search_token,
    warn_condensed_output,
)

def command_token(config: RuntimeConfig, *, show_token: bool = False) -> dict[str, Any]:
    api_token = _require_api_token(config)
    token_payload = fetch_search_token(_require_api_url(config), api_token)
    save_search_token(config.cache_path, token_payload)

    resolved_url = resolve_meili_url(config)
    return {
        "token": token_payload.token if show_token else "[REDACTED]",
        "url": resolved_url,
        "expiresAt": token_payload.expires_at,
        "cached": str(config.cache_path),
    }


def command_search(
    config: RuntimeConfig,
    query: str,
    index: str,
    limit: int,
    *,
    show_dupes: bool = False,
) -> dict[str, Any]:
    resolved_index = index.strip()
    if not resolved_index:
        raise CliError("--index cannot be empty")

    token_payload = _require_cached_or_fresh_token(config)

    def _operation(client: meilisearch.Client) -> dict[str, Any]:
        result = client.index(resolved_index).search(query, {"limit": limit})
        if show_dupes:
            return result
        return _dedupe_search_result_by_project_id(result)

    return _run_with_single_auth_retry(config, _operation, token_payload)


def _search_hit_project_id(hit: Mapping[str, Any]) -> str | None:
    project_id = hit.get("projectId")
    if project_id is None or project_id == "":
        scope = hit.get("scope") if isinstance(hit.get("scope"), dict) else {}
        project_id = scope.get("projectId")
    if project_id is None or project_id == "":
        return None
    return str(project_id)


def _dedupe_search_result_by_project_id(result: dict[str, Any]) -> dict[str, Any]:
    raw_hits = result.get("hits")
    if not isinstance(raw_hits, list):
        return result

    seen_project_ids: set[str] = set()
    deduped_hits: list[Any] = []
    changed = False
    for hit in raw_hits:
        if not isinstance(hit, dict):
            deduped_hits.append(hit)
            continue

        project_id = _search_hit_project_id(hit)
        if project_id is None:
            deduped_hits.append(hit)
            continue
        if project_id in seen_project_ids:
            changed = True
            continue

        seen_project_ids.add(project_id)
        deduped_hits.append(hit)

    if not changed:
        return result
    return {**result, "hits": deduped_hits}


def _command_list_workspace_items(
    config: RuntimeConfig,
    *,
    endpoint: str,
    item_view: Callable[[Mapping[str, Any]], dict[str, Any]],
    full: bool = False,
) -> dict[str, Any]:
    api_url = _require_api_url(config)
    api_token = _require_api_token(config)
    workspace_id = fetch_current_workspace_id(api_url, api_token)

    raw_items = fetch_workspace_items(
        api_url,
        api_token,
        workspace_id,
        endpoint,
    )
    path = f"/folders/{{folderId}}/{endpoint}"
    items_out: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            raise CliError(f"{path} response contains non-object item")
        items_out.append(dict(item) if full else item_view(item))
    if not full:
        warn_condensed_output(f"list_{endpoint}")

    return {
        "workspaceId": workspace_id,
        "items": items_out,
        "count": len(items_out),
    }


def command_list_projects(config: RuntimeConfig, *, full: bool = False) -> dict[str, Any]:
    return _command_list_workspace_items(config, endpoint="projects", item_view=_project_view, full=full)


def command_list_folders(config: RuntimeConfig, *, full: bool = False) -> dict[str, Any]:
    return _command_list_workspace_items(config, endpoint="folders", item_view=_folder_view, full=full)


def _doctor_caption_available(config: RuntimeConfig) -> tuple[bool, str | None]:
    try:
        workspace_id = fetch_current_workspace_id(_require_api_url(config), _require_api_token(config))
        uuid.UUID(workspace_id)
    except CliError as exc:
        return False, exc.message
    except ValueError:
        return False, "/users/me/workspace returned a non-UUID workspace id"
    except httpx.HTTPError as exc:
        return False, f"Caption API unreachable: {exc}"
    return True, None


def _doctor_agentsview_available(args: Any) -> tuple[bool, str | None]:
    try:
        payload = agentsview._agentsview_json(
            "GET",
            "/api/v1/md",
            auth=agentsview._agentsview_auth(args),
            params={"limit": 1},
            expected_statuses={200},
        )
    except CliError as exc:
        return False, exc.message
    except httpx.HTTPError as exc:
        return False, f"history server unreachable: {exc}"
    if "documents" not in payload:
        return False, "GET /api/v1/md response missing 'documents'"
    return True, None


def command_doctor(config: RuntimeConfig, args: Any) -> dict[str, Any]:
    core_available, core_reason = _doctor_caption_available(config)
    agentsview_available, agentsview_reason = _doctor_agentsview_available(args)
    probes = [
        {"name": "core", "available": core_available, "reason": core_reason},
        {"name": "agentsview", "available": agentsview_available, "reason": agentsview_reason},
    ]
    organization = getattr(args, "org_id", None) or os.getenv("ORGANIZATION_ID")
    return {
        "organization": organization,
        "features": [probe["name"] for probe in probes if probe["available"]],
        "probes": probes,
    }


def _resolve_workspace_id(api_url: str, api_token: str, workspace_id: str | None) -> str:
    if workspace_id is None:
        return fetch_current_workspace_id(api_url, api_token)
    resolved_workspace_id = workspace_id.strip()
    if not resolved_workspace_id:
        raise CliError("--workspace-id cannot be empty")
    return resolved_workspace_id


def _dry_run_result(method: str, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
    return {"dry_run": True, "method": method, "path": path, "body": dict(body)}


def _dry_run_workspace_segment(workspace_id: str | None) -> str:
    if workspace_id is None:
        return "{workspaceId from /users/me/workspace}"
    resolved_workspace_id = workspace_id.strip()
    if not resolved_workspace_id:
        raise CliError("--workspace-id cannot be empty")
    return resolved_workspace_id


def _clean_required_id(identifier: str, label: str) -> str:
    cleaned_identifier = identifier.strip()
    if not cleaned_identifier:
        raise CliError(f"{label} cannot be empty")
    return cleaned_identifier


def _strip_transcript_timestamps(transcript_text: str) -> str:
    return re.sub(
        r"(?m)^\[(?:\d{2}:\d{2}\.\d{2}(?:\.\d+)?|\d{4}-\d{2}-\d{2}T[^\]]+)\]\s*",
        "",
        transcript_text,
    )


def _build_create_body(
    *,
    command_name: str,
    name: str,
    description: str | None,
    nullable_link_value: str | None = None,
    nullable_link_field: str | None = None,
    nullable_link_arg: str | None = None,
) -> dict[str, Any]:
    cleaned_name = name.strip()
    if not cleaned_name:
        raise CliError(f"{command_name} requires a non-empty name")

    body: dict[str, Any] = {"name": cleaned_name}
    if description is not None:
        body["description"] = description

    if nullable_link_field is not None and nullable_link_value is not None:
        cleaned_link = nullable_link_value.strip()
        if not cleaned_link:
            raise CliError(f"{nullable_link_arg} cannot be empty")
        body[nullable_link_field] = cleaned_link
    return body


def _build_edit_body(
    *,
    command_name: str,
    name: str | None,
    description: str | None,
    clear_description: bool,
    nullable_link_value: str | None,
    clear_nullable_link: bool,
    nullable_link_field: str,
    nullable_link_arg: str,
    clear_nullable_link_arg: str,
) -> dict[str, Any]:
    if clear_description and description is not None:
        raise CliError("Use either --description or --clear-description, not both")
    if clear_nullable_link and nullable_link_value is not None:
        raise CliError(f"Use either {nullable_link_arg} or {clear_nullable_link_arg}, not both")

    body: dict[str, Any] = {}
    if name is not None:
        cleaned_name = name.strip()
        if not cleaned_name:
            raise CliError("--name cannot be empty")
        body["name"] = cleaned_name
    if clear_description:
        body["description"] = None
    elif description is not None:
        body["description"] = description
    if clear_nullable_link:
        body[nullable_link_field] = None
    elif nullable_link_value is not None:
        cleaned_link = nullable_link_value.strip()
        if not cleaned_link:
            raise CliError(f"{nullable_link_arg} cannot be empty")
        body[nullable_link_field] = cleaned_link
    if not body:
        raise CliError(
            f"{command_name} requires at least one field: "
            f"--name, --description/--clear-description, {nullable_link_arg}/{clear_nullable_link_arg}"
        )
    return body


def command_create_project(
    config: RuntimeConfig,
    *,
    name: str,
    description: str | None,
    workspace_id: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    body = _build_create_body(command_name="create_project", name=name, description=description)
    if dry_run:
        return _dry_run_result("POST", f"/folders/{_dry_run_workspace_segment(workspace_id)}/projects", body)

    api_url = _require_api_url(config)
    api_token = _require_api_token(config)
    resolved_workspace_id = _resolve_workspace_id(api_url, api_token, workspace_id)

    payload = _authorized_request(
        api_url,
        api_token,
        "POST",
        f"/folders/{resolved_workspace_id}/projects",
        json_body=body,
        expected_statuses={201},
    )
    return _project_view(payload)


def command_create_folder(
    config: RuntimeConfig,
    *,
    name: str,
    description: str | None,
    parent: str | None,
    workspace_id: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    body = _build_create_body(
        command_name="create_folder",
        name=name,
        description=description,
        nullable_link_value=parent,
        nullable_link_field="parent",
        nullable_link_arg="--parent",
    )
    if dry_run:
        return _dry_run_result("POST", f"/folders/{_dry_run_workspace_segment(workspace_id)}/folders", body)

    api_url = _require_api_url(config)
    api_token = _require_api_token(config)
    resolved_workspace_id = _resolve_workspace_id(api_url, api_token, workspace_id)

    payload = _authorized_request(
        api_url,
        api_token,
        "POST",
        f"/folders/{resolved_workspace_id}/folders",
        json_body=body,
        expected_statuses={200, 201},
    )
    return _folder_view(payload)


def command_edit_project(
    config: RuntimeConfig,
    *,
    project_id: str,
    name: str | None,
    description: str | None,
    clear_description: bool,
    folder: str | None,
    clear_folder: bool,
    dry_run: bool = False,
) -> dict[str, Any]:
    cleaned_project_id = _clean_required_id(project_id, "project_id")
    body = _build_edit_body(
        command_name="edit_project",
        name=name,
        description=description,
        clear_description=clear_description,
        nullable_link_value=folder,
        clear_nullable_link=clear_folder,
        nullable_link_field="folder",
        nullable_link_arg="--folder",
        clear_nullable_link_arg="--clear-folder",
    )
    if dry_run:
        return _dry_run_result("PATCH", f"/projects/{cleaned_project_id}", body)

    api_url = _require_api_url(config)
    api_token = _require_api_token(config)

    payload = _authorized_request(
        api_url,
        api_token,
        "PATCH",
        f"/projects/{cleaned_project_id}",
        json_body=body,
        expected_statuses={200},
    )
    return _project_view(payload)


def command_edit_folder(
    config: RuntimeConfig,
    *,
    folder_id: str,
    name: str | None,
    description: str | None,
    clear_description: bool,
    parent: str | None,
    clear_parent: bool,
    dry_run: bool = False,
) -> dict[str, Any]:
    cleaned_folder_id = _clean_required_id(folder_id, "folder_id")
    body = _build_edit_body(
        command_name="edit_folder",
        name=name,
        description=description,
        clear_description=clear_description,
        nullable_link_value=parent,
        clear_nullable_link=clear_parent,
        nullable_link_field="parent",
        nullable_link_arg="--parent",
        clear_nullable_link_arg="--clear-parent",
    )
    if dry_run:
        return _dry_run_result("PATCH", f"/folders/{cleaned_folder_id}", body)

    api_url = _require_api_url(config)
    api_token = _require_api_token(config)

    payload = _authorized_request(
        api_url,
        api_token,
        "PATCH",
        f"/folders/{cleaned_folder_id}",
        json_body=body,
        expected_statuses={200},
    )
    return _folder_view(payload)


def dl_transcript(config: RuntimeConfig, *, transcript_id: str, timestamp: bool = False) -> str:
    api_url = _require_api_url(config)
    api_token = _require_api_token(config)
    cleaned_transcript_id = _clean_required_id(transcript_id, "transcript_id")
    transcript_text = _authorized_get_text(
        api_url,
        api_token,
        f"/transcripts/{cleaned_transcript_id}/export/txt",
        params={"includeHeader": "false"},
    )
    if timestamp:
        return transcript_text
    return _strip_transcript_timestamps(transcript_text)


# Mirrors the API's TranscriptChannel enum (0 = Microphone, 1 = Loopback, 2 = External).
TRANSCRIPT_CHANNELS = {
    "microphone": 0,
    "loopback": 1,
    "external": 2,
}

PROJECT_TRANSCRIPTS_PAGE_LIMIT = 100


def _parse_channel(value: str) -> int:
    cleaned = value.strip().lower()
    if cleaned in TRANSCRIPT_CHANNELS:
        return TRANSCRIPT_CHANNELS[cleaned]
    if cleaned in {str(channel) for channel in TRANSCRIPT_CHANNELS.values()}:
        return int(cleaned)
    valid = ", ".join([*(str(v) for v in TRANSCRIPT_CHANNELS.values()), *TRANSCRIPT_CHANNELS])
    raise CliError(f"--channel must be one of: {valid}")


def _build_assign_speakers_body(
    *,
    channel: str,
    index: int | None,
    speaker_id: str | None,
    name: str | None,
) -> dict[str, Any]:
    if (speaker_id is None) == (name is None):
        raise CliError("assign_speakers requires exactly one of --speaker-id or --name")

    body: dict[str, Any] = {"channel": _parse_channel(channel)}
    if index is not None:
        if index < 0:
            raise CliError("--index must be >= 0")
        body["index"] = index
    if speaker_id is not None:
        body["speakerId"] = _clean_required_id(speaker_id, "--speaker-id")
    else:
        cleaned_name = (name or "").strip()
        if not cleaned_name:
            raise CliError("--name cannot be empty")
        body["speakerName"] = cleaned_name
    return body


def _fetch_project_transcript_ids(api_url: str, api_token: str, project_id: str) -> list[str]:
    path = f"/projects/{project_id}/transcripts"
    transcript_ids: list[str] = []
    offset = 0
    while True:
        payload = _authorized_request(
            api_url,
            api_token,
            "GET",
            path,
            params={"offset": offset, "limit": PROJECT_TRANSCRIPTS_PAGE_LIMIT},
        )
        items = payload.get("items")
        if not isinstance(items, list):
            raise CliError(f"{path} returned JSON object missing array 'items'")
        for item in items:
            transcript_id = item.get("id") if isinstance(item, dict) else None
            if not isinstance(transcript_id, str) or not transcript_id:
                raise CliError(f"{path} response contains transcript without string 'id'")
            transcript_ids.append(transcript_id)

        total_count = payload.get("totalCount")
        offset += len(items)
        if not items or not isinstance(total_count, int) or offset >= total_count:
            return transcript_ids


def command_assign_speakers(
    config: RuntimeConfig,
    *,
    transcript_id: str | None,
    project_id: str | None,
    channel: str,
    index: int | None,
    speaker_id: str | None,
    name: str | None,
    dry_run: bool = False,
) -> dict[str, Any]:
    if (transcript_id is None) == (project_id is None):
        raise CliError("assign_speakers requires exactly one of --transcript-id or --project-id")

    body = _build_assign_speakers_body(channel=channel, index=index, speaker_id=speaker_id, name=name)

    if project_id is not None and index is not None:
        print(
            "note: diarization indexes are not stable across transcripts; "
            "--index with --project-id may match different voices per transcript",
            file=sys.stderr,
        )

    if dry_run:
        if transcript_id is not None:
            path = f"/transcripts/{_clean_required_id(transcript_id, 'transcript_id')}/assign-speakers"
        else:
            cleaned_project_id = _clean_required_id(project_id, "project_id")
            path = f"/transcripts/{{transcriptId from /projects/{cleaned_project_id}/transcripts}}/assign-speakers"
        return _dry_run_result("POST", path, body)

    api_url = _require_api_url(config)
    api_token = _require_api_token(config)

    if transcript_id is not None:
        cleaned_transcript_id = _clean_required_id(transcript_id, "transcript_id")
        payload = _authorized_request(
            api_url,
            api_token,
            "POST",
            f"/transcripts/{cleaned_transcript_id}/assign-speakers",
            json_body=body,
            expected_statuses={200, 201},
        )
        return dict(payload)

    cleaned_project_id = _clean_required_id(project_id, "project_id")
    transcript_ids = _fetch_project_transcript_ids(api_url, api_token, cleaned_project_id)
    results: list[dict[str, Any]] = []
    assigned_speaker_id: Any = None
    total_updated = 0
    for candidate_transcript_id in transcript_ids:
        payload = _authorized_request(
            api_url,
            api_token,
            "POST",
            f"/transcripts/{candidate_transcript_id}/assign-speakers",
            json_body=body,
            expected_statuses={200, 201},
        )
        assigned_speaker_id = payload.get("speakerId")
        updated_count = payload.get("updatedCaptionCount")
        if isinstance(updated_count, int):
            total_updated += updated_count
        results.append(
            {"transcriptId": candidate_transcript_id, "updatedCaptionCount": updated_count}
        )

    return {
        "speakerId": assigned_speaker_id,
        "transcriptCount": len(transcript_ids),
        "totalUpdatedCaptionCount": total_updated,
        "results": results,
    }


def command_list_speakers(config: RuntimeConfig, *, transcript_id: str) -> dict[str, Any]:
    api_url = _require_api_url(config)
    api_token = _require_api_token(config)
    cleaned_transcript_id = _clean_required_id(transcript_id, "transcript_id")

    captions = _authorized_get_list_of_objects(
        api_url,
        api_token,
        f"/transcripts/{cleaned_transcript_id}/captions",
    )

    groups: dict[tuple[Any, Any, Any], dict[str, Any]] = {}
    for caption in captions:
        key = (caption.get("channel"), caption.get("index"), caption.get("speaker"))
        group = groups.get(key)
        if group is None:
            groups[key] = {
                "channel": caption.get("channel"),
                "index": caption.get("index"),
                "speakerId": caption.get("speaker"),
                "captionCount": 1,
                "sample": _truncate_for_cell(caption.get("content", "")),
            }
        else:
            group["captionCount"] += 1

    items = sorted(
        groups.values(),
        key=lambda group: (
            group["channel"] if isinstance(group["channel"], int) else -1,
            group["index"] if isinstance(group["index"], int) else -1,
        ),
    )
    return {
        "transcriptId": cleaned_transcript_id,
        "items": items,
        "count": len(items),
    }


def command_rename_speaker(
    config: RuntimeConfig,
    *,
    project_id: str,
    speaker_id: str,
    name: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    cleaned_project_id = _clean_required_id(project_id, "project_id")
    cleaned_speaker_id = _clean_required_id(speaker_id, "speaker_id")
    cleaned_name = name.strip()
    if not cleaned_name:
        raise CliError("--name cannot be empty")

    body = {"name": cleaned_name}
    path = f"/projects/{cleaned_project_id}/speakers/{cleaned_speaker_id}"
    if dry_run:
        return _dry_run_result("PATCH", path, body)

    api_url = _require_api_url(config)
    api_token = _require_api_token(config)

    payload = _authorized_request(
        api_url,
        api_token,
        "PATCH",
        path,
        json_body=body,
        expected_statuses={200},
    )
    return dict(payload)


def command_sync(config: RuntimeConfig, args: Any) -> Any:
    return agentsview.command_sync(config, args)
