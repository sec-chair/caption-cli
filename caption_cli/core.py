from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Callable, Collection, Mapping, Sequence

import httpx
import meilisearch

# Exit-code dictionary (published via `caption --output json guide` and --help):
#   0 success · 1 user-input error · 2 usage error (argparse)
#   3 configuration error (missing env) · 4 upstream failure · 5 remote not found
EXIT_SUCCESS = 0
EXIT_USER_INPUT = 1
EXIT_USAGE = 2
EXIT_CONFIG = 3
EXIT_UPSTREAM = 4
EXIT_NOT_FOUND = 5

DEFAULT_CACHE_PATH = "search-token.json"
VISA_TOKEN_HEADER = "x-caption-visa"
DEFAULT_LIMIT = 1000
DEFAULT_SEARCH_INDEX = "transcript_blocks_v2"
HTTP_TIMEOUT_SECONDS = 15.0
PROJECT_OUTPUT_FIELDS = (
    "id",
    "transcript",
    "createdAt",
    "updatedAt",
    "name",
    "folder",
    "description",
)
FOLDER_OUTPUT_FIELDS = (
    "id",
    "createdAt",
    "updatedAt",
    "name",
    "parent",
    "description",
)


@dataclass(slots=True)
class CliError(Exception):
    message: str
    exit_code: int = 1


@dataclass(slots=True)
class SearchToken:
    token: str
    url: str | None = None
    expires_at: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, Any]) -> "SearchToken":
        token = payload.get("token")
        if not isinstance(token, str) or not token:
            raise CliError("/search/token response missing string 'token'")

        raw_url = payload.get("url")
        url = raw_url if isinstance(raw_url, str) and raw_url else None
        raw_expires = payload.get("expiresAt")
        expires_at = (
            raw_expires if isinstance(raw_expires, str) and raw_expires else None
        )
        return cls(token=token, url=url, expires_at=expires_at)

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"token": self.token}
        if self.url:
            payload["url"] = self.url
        if self.expires_at:
            payload["expiresAt"] = self.expires_at
        return payload


@dataclass(slots=True)
class RuntimeConfig:
    api_url: str | None
    api_token: str | None
    meili_url: str | None
    cache_path: Path
    output: str


@dataclass(frozen=True, slots=True)
class CommandSpec:
    name: str
    help: str
    add_arguments: Callable[[argparse.ArgumentParser], None]
    handler: Callable[[RuntimeConfig, argparse.Namespace], Any]
    needs_api: bool = True
    needs_meili: bool = False
    default_output: str = "json"
    usage: str = ""
    notes: tuple[str, ...] = ()
    example: str = ""


def _exit_code_for_status(status_code: int) -> int:
    return EXIT_NOT_FOUND if status_code == HTTPStatus.NOT_FOUND else EXIT_UPSTREAM


def fetch_search_token(api_url: str, api_token: str) -> SearchToken:
    path = "/search/token"
    response = _send(
        api_url, api_token, "GET", path, action="to fetch search token"
    )
    return SearchToken.from_payload(_json_object(response, path))


def _build_auth_headers(
    api_token: str | None, visa_token: str | None = None
) -> dict[str, str]:
    headers: dict[str, str] = {}
    if api_token:
        headers["Authorization"] = f"Bearer {api_token}"
    if visa_token:
        headers[VISA_TOKEN_HEADER] = visa_token
    if not headers:
        raise CliError(
            "Missing API credentials: pass --clerk-api-key/CLERK_API_KEY or a share link via --link",
            exit_code=EXIT_CONFIG,
        )
    return headers


def _send(
    api_url: str,
    api_token: str | None,
    method: str,
    path: str,
    *,
    params: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
    ok_statuses: Collection[int] | None = None,
    client: httpx.Client | None = None,
    visa_token: str | None = None,
    action: str | None = None,
) -> httpx.Response:
    # Single Caption API request path: URL, auth headers, client, error mapping.
    url = f"{api_url.rstrip('/')}/{path.lstrip('/')}"
    headers = _build_auth_headers(api_token, visa_token)
    if client is None:
        with httpx.Client(timeout=HTTP_TIMEOUT_SECONDS) as request_client:
            response = request_client.request(
                method, url, headers=headers, params=params, json=json_body
            )
    else:
        response = client.request(
            method, url, headers=headers, params=params, json=json_body
        )

    # No ok_statuses: any non-error status passes (e.g. 204 ok, 404 fails).
    status = response.status_code
    if ok_statuses is None:
        is_error = status >= HTTPStatus.BAD_REQUEST
    else:
        is_error = status not in ok_statuses
    if not is_error:
        return response

    # e.g. "Failed GET /events (404): nope"
    detail = response.text.strip() or response.reason_phrase
    label = action or f"{method.upper()} {path}"
    raise CliError(
        f"Failed {label} ({status}): {detail}",
        exit_code=_exit_code_for_status(status),
    )


def _json_object(response: httpx.Response, path: str) -> dict[str, Any]:
    # Callers expecting an object reject arrays/scalars as upstream errors.
    payload = response.json()
    if not isinstance(payload, dict):
        raise CliError(f"{path} returned non-object JSON", exit_code=EXIT_UPSTREAM)
    return payload


def _authorized_request(
    api_url: str,
    api_token: str | None,
    method: str,
    path: str,
    params: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
    expected_statuses: set[int] | None = None,
    client: httpx.Client | None = None,
    visa_token: str | None = None,
) -> Mapping[str, Any]:
    response = _send(
        api_url,
        api_token,
        method,
        path,
        params=params,
        json_body=json_body,
        ok_statuses=expected_statuses,
        client=client,
        visa_token=visa_token,
    )
    return _json_object(response, path)


def _authorized_get(
    api_url: str,
    api_token: str | None,
    path: str,
    params: Mapping[str, Any] | None = None,
    visa_token: str | None = None,
) -> Mapping[str, Any]:
    return _authorized_request(
        api_url, api_token, "GET", path, params=params, visa_token=visa_token
    )


def _authorized_get_json(
    api_url: str,
    api_token: str | None,
    path: str,
    params: Mapping[str, Any] | None = None,
    client: httpx.Client | None = None,
    visa_token: str | None = None,
) -> Any:
    response = _send(
        api_url,
        api_token,
        "GET",
        path,
        params=params,
        ok_statuses={HTTPStatus.OK},
        client=client,
        visa_token=visa_token,
    )
    return response.json()


def _authorized_get_text(
    api_url: str,
    api_token: str,
    path: str,
    params: Mapping[str, Any] | None = None,
) -> str:
    response = _send(
        api_url, api_token, "GET", path, params=params, ok_statuses={HTTPStatus.OK}
    )
    return response.text


def _extract_object_list(payload: Any, path: str) -> list[Mapping[str, Any]]:
    if isinstance(payload, list):
        items = payload
        item_location = "array"
    elif isinstance(payload, Mapping):
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            raise CliError(
                f"{path} returned JSON object missing array 'items'",
                exit_code=EXIT_UPSTREAM,
            )
        items = raw_items
        item_location = "'items' array"
    else:
        raise CliError(f"{path} returned non-array JSON", exit_code=EXIT_UPSTREAM)

    if not all(isinstance(item, dict) for item in items):
        raise CliError(
            f"{path} returned {item_location} containing non-object items",
            exit_code=EXIT_UPSTREAM,
        )
    return items


def warn_condensed_output(command_name: str) -> None:
    print(
        f"note: {command_name} output is a condensed view; pass --full for the raw server payload",
        file=sys.stderr,
    )


def _field_view(payload: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    return {key: payload.get(key) for key in fields}


def _project_view(project_payload: Mapping[str, Any]) -> dict[str, Any]:
    return _field_view(project_payload, PROJECT_OUTPUT_FIELDS)


def _folder_view(folder_payload: Mapping[str, Any]) -> dict[str, Any]:
    return _field_view(folder_payload, FOLDER_OUTPUT_FIELDS)


def fetch_current_workspace_id(api_url: str, api_token: str) -> str:
    payload = _authorized_get(api_url, api_token, "/users/me/workspace")
    workspace_id = payload.get("root")
    if not isinstance(workspace_id, str) or not workspace_id.strip():
        raise CliError("/users/me/workspace response missing string 'root'")
    return workspace_id


def fetch_workspace_items(
    api_url: str,
    api_token: str,
    workspace_id: str,
    endpoint: str,
) -> list[Mapping[str, Any]]:
    path = f"/folders/{workspace_id}/{endpoint}"
    return _extract_object_list(_authorized_get_json(api_url, api_token, path), path)


def load_cached_search_token(cache_path: Path) -> SearchToken | None:
    if not cache_path.exists():
        return None

    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise CliError(f"Failed reading cache file {cache_path}: {exc}") from exc

    if not isinstance(payload, dict):
        raise CliError(f"Cache file {cache_path} must contain a JSON object")

    return SearchToken.from_payload(payload)


def save_search_token(cache_path: Path, search_token: SearchToken) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(search_token.to_payload(), indent=2) + "\n", encoding="utf-8"
    )


def _require_api_url(config: RuntimeConfig) -> str:
    if config.api_url and config.api_url.strip():
        return config.api_url.strip()
    raise CliError(
        "Missing Caption API URL. Set CAPTION_API_URL", exit_code=EXIT_CONFIG
    )


def _require_meili_url(config: RuntimeConfig) -> str:
    if config.meili_url and config.meili_url.strip():
        return config.meili_url.strip()
    raise CliError(
        "Missing Meilisearch URL. Set CAPTION_MEILI_URL", exit_code=EXIT_CONFIG
    )


def build_meili_client(meili_url: str, meili_token: str) -> meilisearch.Client:
    return meilisearch.Client(meili_url, api_key=meili_token)


def _stringify_error(err: Exception) -> str:
    message = getattr(err, "message", None)
    if isinstance(message, str) and message:
        return message
    return str(err)


def _is_meili_auth_error(err: Exception) -> bool:
    status_code = getattr(err, "status_code", None)
    if status_code in {401, 403}:
        return True

    code = getattr(err, "code", None)
    if isinstance(code, str) and code in {
        "invalid_api_key",
        "missing_authorization_header",
    }:
        return True

    message = _stringify_error(err).lower()
    return any(
        token in message
        for token in ("invalid_api_key", "api key", "unauthorized", "forbidden")
    )


def _require_api_token(config: RuntimeConfig) -> str:
    if config.api_token and config.api_token.strip():
        return config.api_token.strip()
    raise CliError(
        "Missing Clerk API key. Pass --clerk-api-key or set CLERK_API_KEY",
        exit_code=EXIT_CONFIG,
    )


def _require_cached_or_fresh_token(config: RuntimeConfig) -> SearchToken:
    cached = load_cached_search_token(config.cache_path)
    if cached:
        return cached

    api_token = _require_api_token(config)
    fresh = fetch_search_token(_require_api_url(config), api_token)
    save_search_token(config.cache_path, fresh)
    return fresh


def _run_with_single_auth_retry(
    config: RuntimeConfig,
    operation: Callable[[meilisearch.Client], Any],
    initial_token: SearchToken,
) -> Any:
    initial_url = _require_meili_url(config)
    client = build_meili_client(initial_url, initial_token.token)

    try:
        return operation(client)
    except Exception as exc:
        if not _is_meili_auth_error(exc):
            raise CliError(_stringify_error(exc), exit_code=EXIT_UPSTREAM) from exc

        api_token = _require_api_token(config)
        refreshed_token = fetch_search_token(_require_api_url(config), api_token)
        save_search_token(config.cache_path, refreshed_token)

        retry_url = _require_meili_url(config)
        retry_client = build_meili_client(retry_url, refreshed_token.token)

        try:
            return operation(retry_client)
        except Exception as retry_exc:
            raise CliError(
                _stringify_error(retry_exc), exit_code=EXIT_UPSTREAM
            ) from retry_exc


def _render_table(value: Any) -> str:
    if isinstance(value, dict):
        items = value.get("items")
        if isinstance(items, list) and all(isinstance(item, dict) for item in items):
            lines: list[str] = []
            for metadata_key in ("workspaceId", "transcriptId"):
                metadata_value = value.get(metadata_key)
                if metadata_value:
                    lines.append(f"{metadata_key}: {metadata_value}")
            lines.append(f"count: {len(items)}")
            if not items:
                return "\n".join(lines)
            columns = list(items[0].keys())
            lines.append("\t".join(columns))
            for item in items:
                lines.append(
                    "\t".join(
                        "" if item.get(column) is None else str(item.get(column))
                        for column in columns
                    )
                )
            return "\n".join(lines)

        lines = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                lines.append(f"{key}: {json.dumps(item, ensure_ascii=True)}")
            else:
                lines.append(f"{key}: {item}")
        return "\n".join(lines)

    if isinstance(value, list):
        return "\n".join(json.dumps(item, ensure_ascii=True) for item in value)

    return str(value)


def _truncate_for_cell(value: Any, *, limit: int = 72) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return f"{text[: limit - 3]}..."


def _cell(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("|", "\\|")


def _to_yyyymmdd(value: Any) -> str:
    if not isinstance(value, str) or len(value) < 10:
        return ""
    candidate = value[:10]
    if len(candidate) == 10 and candidate[4] == "-" and candidate[7] == "-":
        return candidate.replace("-", "")
    return ""


def _search_summary_header(
    value: Mapping[str, Any], hits: Sequence[Mapping[str, Any]]
) -> list[str]:
    return [f"hits: {value.get('estimatedTotalHits')} | unique: {len(hits)}"]


def _search_hit_project_id(hit: Mapping[str, Any]) -> str | None:
    project_id = hit.get("projectId")
    if project_id is None or project_id == "":
        scope = hit.get("scope") if isinstance(hit.get("scope"), dict) else {}
        project_id = scope.get("projectId")
    if project_id is None or project_id == "":
        return None
    return str(project_id)


def _hit_speaker_name(hit: Mapping[str, Any]) -> Any:
    speaker = hit.get("speaker") if isinstance(hit.get("speaker"), dict) else {}
    return speaker.get("name")


def _hit_speakers(hit: Mapping[str, Any]) -> str:
    # e.g. ["Ann", "Bo"] -> "Ann, Bo"; non-list -> "".
    speakers = hit.get("speakers")
    if not isinstance(speakers, list):
        return ""
    joined = ", ".join(str(item) for item in speakers)
    return _truncate_for_cell(joined, limit=40)


def _hit_updated_day(hit: Mapping[str, Any]) -> str:
    return _to_yyyymmdd(hit.get("updatedAt"))


def _hit_content(hit: Mapping[str, Any]) -> str:
    return _truncate_for_cell(hit.get("content", ""))


# Search table columns per index: (header label, cell extractor).
# Rendered as "| # | <label> | ... |" with one row per hit.
_SearchColumn = tuple[str, Callable[[Mapping[str, Any]], Any]]
_SEARCH_COLUMNS: dict[str, tuple[_SearchColumn, ...]] = {
    "transcript_captions_v1": (
        ("projectId (uuid)", _search_hit_project_id),
        ("speaker.name", _hit_speaker_name),
        ("updatedAt (YYYYMMDD)", _hit_updated_day),
        ("content", _hit_content),
    ),
    "transcript_sessions_v1": (
        ("projectId (uuid)", _search_hit_project_id),
        ("updatedAt (YYYYMMDD)", _hit_updated_day),
        ("speakers", _hit_speakers),
        ("content", _hit_content),
    ),
    "projects_v1": (
        ("id (project uuid)", lambda hit: hit.get("id")),
        ("updatedAt (YYYYMMDD)", _hit_updated_day),
        ("name", lambda hit: _truncate_for_cell(hit.get("name", ""), limit=40)),
        (
            "description",
            lambda hit: _truncate_for_cell(hit.get("description"), limit=60),
        ),
    ),
}


def _render_search_summary_table(value: Any, index_uid: str | None) -> str:
    if not isinstance(value, dict):
        return _render_table(value)
    raw_hits = value.get("hits")
    if not isinstance(raw_hits, list):
        return _render_table(value)
    hits = [hit for hit in raw_hits if isinstance(hit, dict)]

    lines = _search_summary_header(value, hits)
    if not hits:
        lines.append("No hits.")
        return "\n".join(lines)

    # Unknown search index: retain existing generic table rendering behavior.
    columns = _SEARCH_COLUMNS.get(index_uid or "")
    if columns is None:
        return _render_table(value)

    # Markdown table: "#" column right-aligned, then one column per extractor.
    labels = [label for label, _ in columns]
    lines.append(f"| # | {' | '.join(labels)} |")
    lines.append("|---:|" + "---|" * len(columns))
    for i, hit in enumerate(hits, start=1):
        row = [str(i)] + [_cell(extract(hit)) for _, extract in columns]
        lines.append(f"| {' | '.join(row)} |")
    return "\n".join(lines)


def render_output(
    value: Any,
    output_format: str,
    *,
    command_name: str | None = None,
    search_index: str | None = None,
) -> str:
    if output_format == "json":
        return json.dumps(value, indent=2)
    if output_format == "md" and isinstance(value, str):
        return value
    if output_format == "table" and command_name == "search":
        return _render_search_summary_table(value, search_index)
    return _render_table(value)


def emit_output(
    value: Any,
    output_format: str,
    *,
    command_name: str | None = None,
    search_index: str | None = None,
) -> None:
    print(
        render_output(
            value,
            output_format,
            command_name=command_name,
            search_index=search_index,
        )
    )
