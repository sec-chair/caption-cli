from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Sequence

from dotenv import load_dotenv

from caption_cli.commands import (
    command_create_folder,
    command_create_project,
    command_doctor,
    command_edit_folder,
    command_edit_project,
    command_list_folders,
    command_list_projects,
    command_search,
    command_sync,
    command_token,
    dl_transcript,
)
from caption_cli.agentsview import (
    command_create_md,
    command_get_md,
    command_list_matters,
    command_list_md,
    default_db_path,
)
from caption_cli.core import (
    CliError,
    CommandSpec,
    DEFAULT_CACHE_PATH,
    DEFAULT_LIMIT,
    DEFAULT_SEARCH_INDEX,
    RuntimeConfig,
    _require_api_url,
    _require_meili_url,
    emit_output,
    render_output,
)


def default_download_cache_dir() -> Path:
    return Path("caption_cache")


def default_env_file() -> Path:
    return Path.cwd() / ".env"


def _top_level_help_epilog(specs: Sequence[CommandSpec]) -> str:
    lines = [
        "Environment",
        "  CAPTION_API_URL   required for Caption API commands",
        "  CLERK_API_KEY     required for authenticated Caption API calls",
        "  CAPTION_MEILI_URL required for token and search",
        "  ORGANIZATION_ID   required for hosted history write/read commands",
        "",
        "Global options",
        "  --env-file ENV_FILE      dotenv file loaded before env resolution (default: $PWD/.env)",
        "  --cache-path CACHE_PATH  search token cache path (default: search-token.json)",
        (
            "  --output {json,table,md} output format "
            "(default: json, except search/list_projects/list_folders/list_matters=table and dl_transcript/get_md=md)"
        ),
        "  --output-file PATH      write rendered output to PATH for large outputs like list_projects, list_folders, list_matters, dl_transcript, get_md",
        "",
        "Command Cheat Sheet",
    ]
    for spec in specs:
        lines.extend(
            [
                "",
                f"{spec.name}",
                f"  usage: {spec.usage}",
            ]
        )
        if spec.notes:
            lines.append("  notes:")
            for note in spec.notes:
                lines.append(f"    - {note}")
        lines.append(f"  example: {spec.example}")
    return "\n".join(lines)


def build_parser(env_file: Path) -> tuple[argparse.ArgumentParser, dict[str, CommandSpec]]:
    specs = tuple(_command_specs())
    parser = argparse.ArgumentParser(
        prog="caption",
        description="Caption CLI for API and Meilisearch operations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_top_level_help_epilog(specs),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--cache-path",
        default=str(DEFAULT_CACHE_PATH),
    )
    parser.add_argument(
        "--output",
        choices=("json", "table", "md"),
        default=None,
    )
    parser.add_argument(
        "--output-file",
        type=Path,
        default=None,
        help="write rendered command output to PATH",
    )
    parser.add_argument(
        "--env-file",
        default=str(env_file),
        help="dotenv path loaded before env-based defaults are resolved",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)
    for spec in specs:
        subparser = subparsers.add_parser(spec.name, help=spec.help, allow_abbrev=False)
        spec.add_arguments(subparser)

    return parser, {spec.name: spec for spec in specs}


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    env_file = default_env_file()
    pre_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre_parser.add_argument("--env-file", default=str(env_file))
    pre_args, _ = pre_parser.parse_known_args(argv)
    if pre_args.env_file:
        load_dotenv(dotenv_path=Path(pre_args.env_file), override=True)

    parser, command_specs = build_parser(Path(pre_args.env_file))
    args = parser.parse_args(argv)
    if args.output is None:
        args.output = command_specs[args.command].default_output
    if hasattr(args, "limit") and args.limit is not None and args.limit < 1:
        raise CliError("--limit must be >= 1")

    return args


def write_output_file(path: Path, rendered: str, command: str) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{rendered}\n", encoding="utf-8")
    return f"Saved {command} output to {path}"


def _safe_filename(value: str) -> str:
    filename = "".join(char if char.isalnum() or char in "._-" else "_" for char in value.strip())
    return filename or "document"


def _strip_markdown_suffix(value: str) -> str:
    stem = value.strip()
    while stem.lower().endswith(".md"):
        stem = stem[:-3].rstrip()
    return stem


def _get_md_output_filename(result: Any, args: argparse.Namespace) -> str:
    title = result.get("title") if isinstance(result, dict) else None
    if not isinstance(title, str) or not title.strip():
        title = args.id
    return f"{_safe_filename(_strip_markdown_suffix(title))}.md"


def _default_get_md_output_file(result: Any, args: argparse.Namespace) -> Path:
    return Path(args.cache_dir).expanduser() / "md" / _get_md_output_filename(result, args)


def _add_no_arguments(_: argparse.ArgumentParser) -> None:
    return None


def _add_token_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--show-token",
        action="store_true",
        help="Print the raw Meili search token in output (sensitive)",
    )


def _add_search_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("query", help="Search query string")
    parser.add_argument(
        "--index",
        default=DEFAULT_SEARCH_INDEX,
        help=(
            "Index UID (for example: transcript_captions_v1, workspace_folders_v1, "
            "projects_v1, transcript_sessions_v1)."
        ),
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help=f"Maximum results (default: {DEFAULT_LIMIT})")


def _add_create_project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="Project name")
    parser.add_argument("--description", help="Project description", default=None)
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Workspace UUID. If omitted, resolves from /users/me/workspace.",
    )


def _add_create_folder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="Folder name")
    parser.add_argument("--description", help="Folder description", default=None)
    parser.add_argument("--parent", default=None, help="Parent folder UUID")
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Workspace UUID. If omitted, resolves from /users/me/workspace.",
    )


def _add_edit_project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project UUID")
    parser.add_argument("--name", default=None, help="New project name")
    parser.add_argument("--description", default=None, help="New project description")
    parser.add_argument(
        "--clear-description",
        action="store_true",
        help="Set description to null",
    )
    parser.add_argument("--folder", default=None, help="Folder UUID")
    parser.add_argument(
        "--clear-folder",
        action="store_true",
        help="Set folder to null",
    )


def _add_edit_folder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("folder_id", help="Folder UUID")
    parser.add_argument("--name", default=None, help="New folder name")
    parser.add_argument("--description", default=None, help="New folder description")
    parser.add_argument(
        "--clear-description",
        action="store_true",
        help="Set description to null",
    )
    parser.add_argument("--parent", default=None, help="Parent folder UUID")
    parser.add_argument(
        "--clear-parent",
        action="store_true",
        help="Set parent to null",
    )


def _add_dl_transcript_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("transcript_id", help="Transcript UUID")
    parser.add_argument(
        "--timestamp",
        action="store_true",
        help="Keep timestamps in transcript output",
    )


def _add_sync_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", default=str(default_db_path()), help="SQLite sessions database path")
    parser.add_argument("--session-id", required=True, help="Case-insensitive session ID substring, or * for all")
    parser.add_argument("--project-name", default=None, help="Override the destination project display name")
    parser.add_argument("--test", action="store_true", help="Build payloads locally and print JSON without sending")
    parser.add_argument("--clerk-api-key", default=None, help="Bearer token override for share requests")
    parser.add_argument("--org-id", default=None, help="Organization header override for share requests")


def _add_history_auth_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--clerk-api-key", default=None, help="Bearer token override for history requests")
    parser.add_argument("--org-id", default=None, help="Organization header override for history requests")


def _add_create_md_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("markdown_file", help="Markdown file to submit")
    parser.add_argument("--project-id", default=None, help="Destination project UUID")
    parser.add_argument("--project-name", default=None, help="Destination project display-name search")
    parser.add_argument("--title", default=None, help="Document title; defaults to the Markdown filename")
    _add_history_auth_arguments(parser)


def _add_list_md_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--project", default=None, help="Project display name filter")
    parser.add_argument("--exclude-project", dest="exclude_project", default=None, help="Project display name exclusion")
    parser.add_argument("--tag", action="append", default=None, help="Tag filter; repeat or pass comma-separated values")
    parser.add_argument(
        "--created-by",
        dest="created_by",
        action="append",
        default=None,
        help="Clerk user id filter; repeat or pass comma-separated values",
    )
    parser.add_argument("--sort", choices=("recent", "most_starred"), default=None, help="Sort order")
    parser.add_argument("--cursor", default=None, help="Pagination cursor")
    parser.add_argument("--limit", type=int, default=None, help="Page size, max 500")
    _add_history_auth_arguments(parser)


def _add_list_matters_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include-one-shot",
        action="store_true",
        help="Include one-shot projects by sending include_one_shot=true",
    )
    _add_history_auth_arguments(parser)


def _add_get_md_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("id", help="Markdown document UUID")
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=default_download_cache_dir(),
        help="Directory for cached get_md Markdown files (default: caption_cache)",
    )
    _add_history_auth_arguments(parser)


def _handle_token(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_token(config, show_token=args.show_token)


def _handle_search(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_search(config, query=args.query, index=args.index, limit=args.limit)


def _handle_list_projects(config: RuntimeConfig, _: argparse.Namespace) -> dict[str, Any]:
    return command_list_projects(config)


def _handle_list_folders(config: RuntimeConfig, _: argparse.Namespace) -> dict[str, Any]:
    return command_list_folders(config)


def _handle_create_project(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_create_project(
        config,
        name=args.name,
        description=args.description,
        workspace_id=args.workspace_id,
    )


def _handle_create_folder(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_create_folder(
        config,
        name=args.name,
        description=args.description,
        parent=args.parent,
        workspace_id=args.workspace_id,
    )


def _handle_edit_project(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_edit_project(
        config,
        project_id=args.project_id,
        name=args.name,
        description=args.description,
        clear_description=args.clear_description,
        folder=args.folder,
        clear_folder=args.clear_folder,
    )


def _handle_edit_folder(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_edit_folder(
        config,
        folder_id=args.folder_id,
        name=args.name,
        description=args.description,
        clear_description=args.clear_description,
        parent=args.parent,
        clear_parent=args.clear_parent,
    )


def _handle_dl_transcript(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return dl_transcript(config, transcript_id=args.transcript_id, timestamp=args.timestamp)


def _handle_sync(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return command_sync(config, args)


def _handle_create_md(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return command_create_md(config, args)


def _handle_list_md(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return command_list_md(config, args)


def _handle_list_matters(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return command_list_matters(config, args)


def _handle_get_md(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return command_get_md(config, args)


def _handle_doctor(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return command_doctor(config, args)


def render_doctor_output(features: Sequence[str]) -> str:
    lines = ["CAPTION FEATURES AVAILABLE:"]
    lines.extend(feature for feature in ("core", "agentsview") if feature in features)
    return "\n".join(lines)


def _command_specs() -> Sequence[CommandSpec]:
    return (
        CommandSpec(
            name="doctor",
            help="Probe available Caption features",
            add_arguments=_add_history_auth_arguments,
            handler=_handle_doctor,
            needs_api=False,
            default_output="plain",
            usage="caption doctor [--clerk-api-key TOKEN] [--org-id ORG]",
            notes=(
                "Probes Caption API core support and hosted history Markdown support.",
                "Probe failures are hidden and only available features are printed.",
            ),
            example="caption doctor",
        ),
        CommandSpec(
            name="token",
            help="Fetch and cache /search/token credentials",
            add_arguments=_add_token_arguments,
            handler=_handle_token,
            needs_meili=True,
            usage="caption token [--show-token]",
            notes=(
                "Fetches Meilisearch credentials from GET {CAPTION_API_URL}/search/token.",
                "Writes token payload to --cache-path.",
                "Output redacts token by default; use --show-token only when explicitly needed.",
            ),
            example="caption token --show-token",
        ),
        CommandSpec(
            name="search",
            help="Search one Meilisearch index",
            add_arguments=_add_search_arguments,
            handler=_handle_search,
            needs_meili=True,
            default_output="table",
            usage="caption search <query> [--index INDEX] [--limit N]",
            notes=(
                "--limit must be >= 1.",
                "Uses cached token and refreshes once on Meili auth failures.",
            ),
            example="caption search \"roadmap\" --index projects_v1 --limit 10",
        ),
        CommandSpec(
            name="list_projects",
            help="List all projects in the current user's workspace",
            add_arguments=_add_no_arguments,
            handler=_handle_list_projects,
            default_output="table",
            usage="caption list_projects",
            notes=("Fetches workspace via /users/me/workspace and paginates projects.",),
            example="caption list_projects",
        ),
        CommandSpec(
            name="list_folders",
            help="List all folders in the current user's workspace",
            add_arguments=_add_no_arguments,
            handler=_handle_list_folders,
            default_output="table",
            usage="caption list_folders",
            notes=("Fetches workspace via /users/me/workspace and paginates folders.",),
            example="caption list_folders",
        ),
        CommandSpec(
            name="create_project",
            help="Create a new project in a workspace",
            add_arguments=_add_create_project_arguments,
            handler=_handle_create_project,
            usage="caption create_project <name> [--description TEXT] [--workspace-id UUID]",
            notes=("If --workspace-id is omitted, workspace ID is resolved from /users/me/workspace.",),
            example="caption create_project \"My Project\" --description \"First draft\"",
        ),
        CommandSpec(
            name="create_folder",
            help="Create a new folder in a workspace",
            add_arguments=_add_create_folder_arguments,
            handler=_handle_create_folder,
            usage="caption create_folder <name> [--description TEXT] [--parent UUID] [--workspace-id UUID]",
            notes=("If --workspace-id is omitted, workspace ID is resolved from /users/me/workspace.",),
            example="caption create_folder \"My Folder\" --parent <parent-folder-uuid>",
        ),
        CommandSpec(
            name="edit_project",
            help="Edit a project via PATCH /projects/{projectId}",
            add_arguments=_add_edit_project_arguments,
            handler=_handle_edit_project,
            usage=(
                "caption edit_project <project_id> "
                "[--name TEXT] [--description TEXT|--clear-description] [--folder UUID|--clear-folder]"
            ),
            notes=(
                "At least one field is required.",
                "Conflicting nullable pairs are rejected.",
            ),
            example="caption edit_project <project-uuid> --name \"Renamed\" --clear-folder",
        ),
        CommandSpec(
            name="edit_folder",
            help="Edit a folder via PATCH /workspaces/folders/{folderId}",
            add_arguments=_add_edit_folder_arguments,
            handler=_handle_edit_folder,
            usage=(
                "caption edit_folder <folder_id> "
                "[--name TEXT] [--description TEXT|--clear-description] [--parent UUID|--clear-parent]"
            ),
            notes=(
                "At least one field is required.",
                "Conflicting nullable pairs are rejected.",
            ),
            example="caption edit_folder <folder-uuid> --description \"Updated\" --clear-parent",
        ),
        CommandSpec(
            name="dl_transcript",
            help="Download captions for a transcript",
            add_arguments=_add_dl_transcript_arguments,
            handler=_handle_dl_transcript,
            default_output="md",
            usage="caption dl_transcript <transcript_id> [--timestamp]",
            notes=(
                "Default output strips leading timestamps from each transcript line for token efficiency.",
                "Pass --timestamp to preserve them in output.",
            ),
            example="caption --output json dl_transcript <transcript-uuid>",
        ),
        CommandSpec(
            name="list_matters",
            help="List matters from the hosted history server",
            add_arguments=_add_list_matters_arguments,
            handler=_handle_list_matters,
            needs_api=False,
            default_output="table",
            usage="caption list_matters [--include-one-shot] [--clerk-api-key TOKEN] [--org-id ORG]",
            notes=(
                "GETs https://history.caption.fyi/api/v1/projects.",
                "This is separate from list_projects, which uses the main Caption workspace API.",
            ),
            example="caption list_matters --include-one-shot",
        ),
        CommandSpec(
            name="sync",
            help="Build or send terminal sessions parsed into SQLite by agentsview",
            add_arguments=_add_sync_arguments,
            handler=_handle_sync,
            needs_api=False,
            usage=(
                "caption sync "
                "--session-id VALUE [--project-name TEXT] [--test] [--db-path PATH] "
                "[--clerk-api-key TOKEN] [--org-id ORG]"
            ),
            notes=(
                "Matches sessions by case-insensitive substring on the raw session ID; use * to select all sessions.",
                "--project-name overrides session.project in every built payload.",
                "Use --test to print the built JSON payloads without sending anything.",
                "Without --test, builds payloads from the local SQLite DB, then PUTs them to https://history.caption.fyi/api/v1/shares/{session_id}.",
            ),
            example="caption sync --session-id s1 --org-id org_123",
        ),
        CommandSpec(
            name="create_md",
            help="Create a Markdown document on the hosted history server",
            add_arguments=_add_create_md_arguments,
            handler=_handle_create_md,
            needs_api=False,
            usage=(
                "caption create_md <markdown_file> "
                "[--project-id UUID|--project-name TEXT] [--title TEXT] [--clerk-api-key TOKEN] [--org-id ORG]"
            ),
            notes=(
                "POSTs to https://history.caption.fyi/api/v1/projects/md.",
                "Reads raw_markdown from the file exactly as UTF-8 text.",
                "--title defaults to the Markdown filename.",
                "Output truncates raw_markdown and plain_text fields to 100 characters.",
                "If both project selectors are supplied, the server gives --project-id precedence.",
            ),
            example='caption create_md README.md --project-name "caption-cli endpoint probe" --title "CLI README"',
        ),
        CommandSpec(
            name="list_md",
            help="List Markdown document summaries from the hosted history server",
            add_arguments=_add_list_md_arguments,
            handler=_handle_list_md,
            needs_api=False,
            usage=(
                "caption list_md [--project TEXT] [--exclude-project TEXT] [--tag TAG] "
                "[--created-by USER] [--sort recent|most_starred] [--cursor CURSOR] [--limit N]"
            ),
            notes=(
                "GETs https://history.caption.fyi/api/v1/md.",
                "--tag and --created-by may be repeated; repeated values are sent as comma-separated query values.",
            ),
            example="caption list_md --limit 50 --sort recent",
        ),
        CommandSpec(
            name="get_md",
            help="Fetch one Markdown document from the hosted history server",
            add_arguments=_add_get_md_arguments,
            handler=_handle_get_md,
            needs_api=False,
            default_output="md",
            usage="caption get_md <id> [--clerk-api-key TOKEN] [--org-id ORG]",
            notes=(
                "GETs https://history.caption.fyi/api/v1/md/{id}.",
                "Saves raw_markdown to --cache-dir/md/{title}.md by default; use --output-file to choose another path.",
            ),
            example="caption get_md 019de4db-d14d-7f84-b659-dd9f53d7962c",
        ),
    )


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    command_specs = {spec.name: spec for spec in _command_specs()}
    selected_command = command_specs.get(args.command)
    if selected_command is None:
        raise CliError(f"Unsupported command: {args.command}")

    config = RuntimeConfig(
        api_url=os.getenv("CAPTION_API_URL"),
        api_token=os.getenv("CLERK_API_KEY"),
        meili_url=os.getenv("CAPTION_MEILI_URL"),
        cache_path=Path(args.cache_path),
        output=args.output,
    )
    if selected_command.needs_api:
        _require_api_url(config)
    if selected_command.needs_meili:
        _require_meili_url(config)

    result = selected_command.handler(config, args)
    if args.command == "doctor":
        print(render_doctor_output(result))
        return 0

    output_file = args.output_file
    if args.command == "get_md" and output_file is None and config.output == "md":
        output_file = _default_get_md_output_file(result, args)

    if output_file is not None:
        rendered = render_output(
            result,
            config.output,
            command_name=args.command,
            search_index=getattr(args, "index", None),
        )
        print(write_output_file(output_file, rendered, args.command))
        return 0

    emit_output(
        result,
        config.output,
        command_name=args.command,
        search_index=getattr(args, "index", None),
    )
    return 0
