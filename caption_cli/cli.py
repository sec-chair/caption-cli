from __future__ import annotations

import argparse
import difflib
import importlib.metadata
import os
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

from dotenv import load_dotenv

from caption_cli.commands import (
    command_assign_speakers,
    command_create_folder,
    command_create_project,
    command_doctor,
    command_edit_folder,
    command_edit_project,
    command_list_folders,
    command_list_projects,
    command_list_speakers,
    command_rename_speaker,
    command_search,
    command_sync,
    command_tail,
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
    EXIT_CONFIG,
    EXIT_NOT_FOUND,
    EXIT_SUCCESS,
    EXIT_UPSTREAM,
    EXIT_USAGE,
    EXIT_USER_INPUT,
    RuntimeConfig,
    _require_api_url,
    _require_meili_url,
    emit_output,
    render_output,
)


CONTRACT_VERSION = "1"

EXIT_CODE_DICTIONARY = {
    str(EXIT_SUCCESS): "success (including empty results)",
    str(EXIT_USER_INPUT): "user-input error (bad value, bad local file path, conflicting flags); also doctor --strict probe failure",
    str(EXIT_USAGE): "usage error (argparse: unknown command, unknown flag, missing argument)",
    str(EXIT_CONFIG): "configuration error (missing CAPTION_API_URL, CLERK_API_KEY, CAPTION_MEILI_URL, or ORGANIZATION_ID)",
    str(EXIT_UPSTREAM): "upstream failure (HTTP error, Meilisearch error, malformed server response)",
    str(EXIT_NOT_FOUND): "remote resource not found (HTTP 404)",
}

ENV_VAR_DICTIONARY = {
    "CAPTION_API_URL": "required for Caption API commands",
    "CLERK_API_KEY": "required for authenticated Caption API and hosted history calls",
    "CAPTION_MEILI_URL": "required for token and search",
    "ORGANIZATION_ID": "required for hosted history write/read commands",
    "AGENT_VIEWER_DATA_DIR": "overrides the agentsview data dir for sync (default: ~/.agentsview)",
}


def _tool_version() -> str:
    try:
        return importlib.metadata.version("caption-cli")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def default_download_cache_dir() -> Path:
    return Path("caption_cache")


def default_env_file() -> Path:
    return Path.cwd() / ".env"


def _subcommand_help_epilog(spec: CommandSpec) -> str:
    lines = [f"default output: {spec.default_output}"]
    if spec.notes:
        lines.append("notes:")
        lines.extend(f"  - {note}" for note in spec.notes)
    if spec.example:
        lines.append(f"example: {spec.example}")
    return "\n".join(lines)


def _top_level_help_epilog(specs: Sequence[CommandSpec]) -> str:
    lines = [
        "Agent quick start",
        "  caption capabilities         machine-readable contract: commands, exit codes, env vars",
        "  caption robot-docs guide     paste-ready agent handbook (Markdown, offline)",
        "  caption --output json <cmd>  structured output on any read command (stdout=data, stderr=diagnostics)",
        "  caption --output json doctor --strict   health probe; non-zero exit when a feature is unavailable",
        "  --full                       raw server payloads on list_projects/list_folders/list_matters/list_md/create_md",
        "",
        "Environment",
        "  CAPTION_API_URL   required for Caption API commands",
        "  CLERK_API_KEY     required for authenticated Caption API calls",
        "  CAPTION_MEILI_URL required for token and search",
        "  ORGANIZATION_ID   required for hosted history write/read commands",
        "  AGENT_VIEWER_DATA_DIR overrides the agentsview data dir for sync (default: ~/.agentsview)",
        "",
        "Global options",
        "  --env-file ENV_FILE      dotenv file loaded before env resolution (default: $PWD/.env)",
        "  --cache-path CACHE_PATH  search token cache path (default: search-token.json)",
        (
            "  --output {json,table,md} output format "
            "(default: json, except search/list_projects/list_folders/list_matters/list_speakers=table "
            "and dl_transcript/get_md=md)"
        ),
        "  --output-file PATH      write rendered output to PATH for large outputs like list_projects, list_folders, list_matters, dl_transcript, get_md",
        "",
        "Exit codes",
    ]
    lines.extend(f"  {code}  {meaning}" for code, meaning in EXIT_CODE_DICTIONARY.items())
    lines += [
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


def build_parser(
    env_file: Path,
) -> tuple[argparse.ArgumentParser, dict[str, CommandSpec], dict[str, argparse.ArgumentParser]]:
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

    subparsers = parser.add_subparsers(dest="command", required=False)
    subparser_map: dict[str, argparse.ArgumentParser] = {}
    for spec in specs:
        subparser = subparsers.add_parser(
            spec.name,
            help=spec.help,
            allow_abbrev=False,
            description=spec.help,
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=_subcommand_help_epilog(spec),
        )
        spec.add_arguments(subparser)
        subparser_map[spec.name] = subparser

    return parser, {spec.name: spec for spec in specs}, subparser_map


def _known_option_strings(parser: argparse.ArgumentParser) -> list[str]:
    return [option for action in parser._actions for option in action.option_strings]


def _reject_unknown_arguments(
    parser: argparse.ArgumentParser,
    subparser: argparse.ArgumentParser | None,
    command: str | None,
    unknown: list[str],
) -> None:
    global_flags = set(_known_option_strings(parser))
    known_flags = set(global_flags)
    if subparser is not None:
        known_flags.update(_known_option_strings(subparser))
    sorted_known_flags = sorted(known_flags)

    hints: list[str] = []
    for token in unknown:
        if not token.startswith("-"):
            continue
        flag = token.split("=", 1)[0]
        if flag in global_flags and command is not None:
            hints.append(
                f"{flag} is a global flag and must come before the subcommand, "
                f"e.g. caption {flag} ... {command} ..."
            )
            continue
        matches = difflib.get_close_matches(flag, sorted_known_flags, n=1, cutoff=0.6)
        if matches:
            hints.append(f"did you mean {matches[0]}?")

    scope = f" for 'caption {command}'" if command else ""
    message = f"unrecognized arguments{scope}: {' '.join(unknown)}"
    if hints:
        message += "; " + " ".join(hints)
    else:
        message += f". Valid flags: {', '.join(sorted_known_flags)}"

    (subparser if subparser is not None else parser).error(message)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    env_file = default_env_file()
    pre_parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    pre_parser.add_argument("--env-file", default=str(env_file))
    pre_args, _ = pre_parser.parse_known_args(argv)
    if pre_args.env_file:
        load_dotenv(dotenv_path=Path(pre_args.env_file), override=True)

    parser, command_specs, subparser_map = build_parser(Path(pre_args.env_file))
    args, unknown = parser.parse_known_args(argv)
    if unknown:
        command = getattr(args, "command", None)
        _reject_unknown_arguments(parser, subparser_map.get(command or ""), command, unknown)
    if args.command is None:
        parser.print_help()
        raise SystemExit(EXIT_SUCCESS)
    args.output_supplied = args.output is not None
    if args.output is None:
        args.output = command_specs[args.command].default_output
    if hasattr(args, "limit") and args.limit is not None and args.limit < 1:
        raise CliError("--limit must be >= 1")
    if hasattr(args, "duration") and args.duration is not None and args.duration <= 0:
        raise CliError("--duration must be > 0")
    if hasattr(args, "max_events") and args.max_events is not None and args.max_events < 1:
        raise CliError("--max-events must be >= 1")
    if hasattr(args, "idle_timeout") and args.idle_timeout is not None and args.idle_timeout <= 0:
        raise CliError("--idle-timeout must be > 0")

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


def _add_robot_docs_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "topic",
        nargs="?",
        default="guide",
        choices=("guide",),
        help="Documentation topic (default: guide)",
    )


def _add_full_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--full",
        action="store_true",
        help="Return the raw server payload without condensing or truncating fields",
    )


def _add_list_workspace_arguments(parser: argparse.ArgumentParser) -> None:
    _add_full_flag(parser)
    _add_api_auth_arguments(parser)


def _add_doctor_arguments(parser: argparse.ArgumentParser) -> None:
    _add_history_auth_arguments(parser)
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when any feature probe fails",
    )


def _add_token_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--show-token",
        action="store_true",
        help="Print the raw Meili search token in output (sensitive)",
    )
    _add_api_auth_arguments(parser)


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
    parser.add_argument(
        "--show-dupes",
        action="store_true",
        help="Show duplicate hits instead of deduping search results by projectId",
    )
    _add_api_auth_arguments(parser)


def _add_create_project_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="Project name")
    parser.add_argument("--description", help="Project description", default=None)
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Workspace UUID. If omitted, resolves from /users/me/workspace.",
    )
    _add_api_auth_arguments(parser)
    _add_dry_run_flag(parser)


def _add_create_folder_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("name", help="Folder name")
    parser.add_argument("--description", help="Folder description", default=None)
    parser.add_argument("--parent", default=None, help="Parent folder UUID")
    parser.add_argument(
        "--workspace-id",
        default=None,
        help="Workspace UUID. If omitted, resolves from /users/me/workspace.",
    )
    _add_api_auth_arguments(parser)
    _add_dry_run_flag(parser)


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
    _add_api_auth_arguments(parser)
    _add_dry_run_flag(parser)


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
    _add_api_auth_arguments(parser)
    _add_dry_run_flag(parser)


def _add_dl_transcript_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("transcript_id", help="Transcript UUID")
    parser.add_argument(
        "--timestamp",
        action="store_true",
        help="Keep timestamps in transcript output",
    )
    _add_api_auth_arguments(parser)


def _add_tail_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "transcript_id",
        nargs="?",
        default=None,
        help="Transcript UUID; omitted = transcript attached to the most recently updated project",
    )
    parser.add_argument("--duration", type=float, default=None, help="Stop after N seconds")
    parser.add_argument("--max-events", type=int, default=None, help="Stop after N emitted captions")
    parser.add_argument(
        "--idle-timeout",
        type=float,
        default=None,
        help="Stop after N seconds with no emitted caption",
    )
    _add_api_auth_arguments(parser)


def _add_assign_speakers_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--transcript-id", default=None, help="Transcript UUID to assign within")
    parser.add_argument(
        "--project-id",
        default=None,
        help="Project UUID; assigns across every transcript in the project",
    )
    parser.add_argument(
        "--channel",
        required=True,
        help="Capture channel: 0|microphone, 1|loopback, 2|external",
    )
    parser.add_argument(
        "--index",
        type=int,
        default=None,
        help="Diarization index to filter by; omit to update all indexes in the channel",
    )
    parser.add_argument("--speaker-id", default=None, help="Existing speaker UUID to assign")
    parser.add_argument(
        "--name",
        default=None,
        help="Speaker name; reuses or creates a custom speaker in the transcript's project",
    )
    _add_api_auth_arguments(parser)
    _add_dry_run_flag(parser)


def _add_list_speakers_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("transcript_id", help="Transcript UUID")
    _add_api_auth_arguments(parser)


def _add_rename_speaker_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project_id", help="Project UUID")
    parser.add_argument("speaker_id", help="Speaker UUID")
    parser.add_argument("--name", required=True, help="New speaker name")
    _add_api_auth_arguments(parser)
    _add_dry_run_flag(parser)


def _add_sync_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db-path", default=str(default_db_path()), help="SQLite sessions database path")
    parser.add_argument("--session-id", required=True, help="Case-insensitive session ID substring, or * for all")
    parser.add_argument("--project-name", default=None, help="Override the destination project display name")
    parser.add_argument(
        "--test",
        "--dry-run",
        dest="test",
        action="store_true",
        help="Build payloads locally and print JSON without sending (--dry-run is an alias)",
    )
    parser.add_argument("--yes", action="store_true", help="Confirm bulk sends (required for --session-id '*')")
    parser.add_argument("--clerk-api-key", default=None, help="Bearer token override for share requests")
    parser.add_argument("--org-id", default=None, help="Organization header override for share requests")


def _add_history_auth_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--clerk-api-key", default=None, help="Bearer token override for history requests")
    parser.add_argument("--org-id", default=None, help="Organization header override for history requests")


def _add_dry_run_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and print the request that WOULD be sent, without sending it",
    )


def _add_api_auth_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--clerk-api-key",
        default=None,
        help="Bearer token override for Caption API requests (falls back to CLERK_API_KEY)",
    )


def _add_create_md_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("markdown_file", help="Markdown file to submit")
    parser.add_argument("--project-id", default=None, help="Destination project UUID")
    parser.add_argument("--project-name", default=None, help="Destination project display-name search")
    parser.add_argument("--title", default=None, help="Document title; defaults to the Markdown filename")
    _add_full_flag(parser)
    _add_dry_run_flag(parser)
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
    _add_full_flag(parser)
    _add_history_auth_arguments(parser)


def _add_list_matters_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--include-one-shot",
        action="store_true",
        help="Include one-shot projects by sending include_one_shot=true",
    )
    _add_full_flag(parser)
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
    return command_search(
        config,
        query=args.query,
        index=args.index,
        limit=args.limit,
        show_dupes=args.show_dupes,
    )


def _handle_list_projects(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_list_projects(config, full=args.full)


def _handle_list_folders(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_list_folders(config, full=args.full)


def _handle_create_project(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_create_project(
        config,
        name=args.name,
        description=args.description,
        workspace_id=args.workspace_id,
        dry_run=args.dry_run,
    )


def _handle_create_folder(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_create_folder(
        config,
        name=args.name,
        description=args.description,
        parent=args.parent,
        workspace_id=args.workspace_id,
        dry_run=args.dry_run,
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
        dry_run=args.dry_run,
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
        dry_run=args.dry_run,
    )


def _handle_dl_transcript(config: RuntimeConfig, args: argparse.Namespace) -> Any:
    return dl_transcript(config, transcript_id=args.transcript_id, timestamp=args.timestamp)


def _handle_tail(config: RuntimeConfig, args: argparse.Namespace) -> None:
    return command_tail(
        config,
        transcript_id=args.transcript_id,
        duration=args.duration,
        max_events=args.max_events,
        idle_timeout=args.idle_timeout,
    )


def _handle_assign_speakers(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_assign_speakers(
        config,
        transcript_id=args.transcript_id,
        project_id=args.project_id,
        channel=args.channel,
        index=args.index,
        speaker_id=args.speaker_id,
        name=args.name,
        dry_run=args.dry_run,
    )


def _handle_list_speakers(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_list_speakers(config, transcript_id=args.transcript_id)


def _handle_rename_speaker(config: RuntimeConfig, args: argparse.Namespace) -> dict[str, Any]:
    return command_rename_speaker(
        config,
        project_id=args.project_id,
        speaker_id=args.speaker_id,
        name=args.name,
        dry_run=args.dry_run,
    )


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


def build_capabilities() -> dict[str, Any]:
    return {
        "tool": "caption",
        "version": _tool_version(),
        "contract_version": CONTRACT_VERSION,
        "commands": [
            {
                "name": spec.name,
                "help": spec.help,
                "usage": spec.usage,
                "notes": list(spec.notes),
                "example": spec.example,
                "default_output": spec.default_output,
                "needs_api": spec.needs_api,
                "needs_meili": spec.needs_meili,
            }
            for spec in _command_specs()
        ],
        "global_options": {
            "--env-file": "dotenv file loaded before env resolution (default: $PWD/.env)",
            "--cache-path": "search token cache path (default: search-token.json)",
            "--output": "output format: json, table, or md (per-command defaults vary)",
            "--output-file": "write rendered command output to PATH",
        },
        "exit_codes": EXIT_CODE_DICTIONARY,
        "env_vars": ENV_VAR_DICTIONARY,
    }


def _handle_capabilities(_: RuntimeConfig, __: argparse.Namespace) -> dict[str, Any]:
    return build_capabilities()


def build_robot_docs_guide() -> str:
    lines = [
        "# caption — agent guide",
        "",
        "caption drives the Caption API, Meilisearch search, and the hosted history (agentsview) server.",
        "",
        "## Rules of thumb",
        "",
        "- stdout is data; stderr is diagnostics. Pipe `--output json` output straight into `jq`.",
        "- Most read commands accept `--output json`; streaming commands document their fixed stdout format.",
        "- Condensed views announce themselves on stderr; add `--full` for the raw server payload.",
        "- Start a session with `caption capabilities` (machine-readable contract, works offline).",
        "- Health-check with `caption --output json doctor --strict` (non-zero exit when a feature probe fails).",
        "- `sync --test` builds payloads locally and prints them without sending anything.",
        "",
        "## Exit codes",
        "",
    ]
    lines.extend(f"- `{code}` — {meaning}" for code, meaning in EXIT_CODE_DICTIONARY.items())
    lines += [
        "",
        "## Environment",
        "",
    ]
    lines.extend(f"- `{name}` — {meaning}" for name, meaning in ENV_VAR_DICTIONARY.items())
    lines += [
        "",
        "## Authentication",
        "",
        "- Every authenticated command accepts `--clerk-api-key`, falling back to `CLERK_API_KEY` (a `.env` in $PWD is loaded automatically; override with `--env-file`).",
        "- Hosted history commands (sync, create_md, list_md, get_md, list_matters, doctor) accept `--clerk-api-key` and `--org-id` flags, falling back to `CLERK_API_KEY` / `ORGANIZATION_ID`.",
        "",
        "## Commands",
    ]
    for spec in _command_specs():
        lines += [
            "",
            f"### {spec.name}",
            "",
            f"{spec.help}.",
            "",
            f"- usage: `{spec.usage}`",
            f"- default output: {spec.default_output}",
        ]
        lines.extend(f"- {note}" for note in spec.notes)
        if spec.example:
            lines.append(f"- example: `{spec.example}`")
    return "\n".join(lines)


def _handle_robot_docs(_: RuntimeConfig, __: argparse.Namespace) -> str:
    return build_robot_docs_guide()


def render_doctor_output(result: Mapping[str, Any]) -> str:
    organization = result.get("organization")
    features = result.get("features") or ()
    lines = [
        f"ORGANIZATION: {organization if organization is not None else 'None'}",
        "CAPTION FEATURES AVAILABLE:",
    ]
    lines.extend(feature for feature in ("core", "agentsview") if feature in features)
    return "\n".join(lines)


def _command_specs() -> Sequence[CommandSpec]:
    return (
        CommandSpec(
            name="doctor",
            help="Probe available Caption features",
            add_arguments=_add_doctor_arguments,
            handler=_handle_doctor,
            needs_api=False,
            default_output="plain",
            usage="caption doctor [--strict] [--clerk-api-key TOKEN] [--org-id ORG]",
            notes=(
                "Probes Caption API core support and hosted history Markdown support.",
                "Failed probes print their reason to stderr; pass --strict to also exit non-zero.",
                "Use --output json for the full structured result: {organization, features, probes}.",
            ),
            example="caption --output json doctor --strict",
        ),
        CommandSpec(
            name="capabilities",
            help="Print the machine-readable CLI contract (commands, exit codes, env vars)",
            add_arguments=_add_no_arguments,
            handler=_handle_capabilities,
            needs_api=False,
            default_output="json",
            usage="caption capabilities",
            notes=(
                "Generated from the same command table that drives --help; needs no network or credentials.",
                "Includes per-command usage/notes/examples, the exit-code dictionary, and the env-var dictionary.",
            ),
            example="caption capabilities",
        ),
        CommandSpec(
            name="robot-docs",
            help="Print the paste-ready agent handbook for this CLI",
            add_arguments=_add_robot_docs_arguments,
            handler=_handle_robot_docs,
            needs_api=False,
            default_output="md",
            usage="caption robot-docs guide",
            notes=(
                "Markdown handbook generated from the live command table; needs no network or credentials.",
                "Covers output formats, exit codes, env vars, auth order, and per-command usage.",
            ),
            example="caption robot-docs guide",
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
            usage="caption search <query> [--index INDEX] [--limit N] [--show-dupes]",
            notes=(
                "--limit must be >= 1.",
                "Uses cached token and refreshes once on Meili auth failures.",
            ),
            example="caption search \"roadmap\" --index projects_v1 --limit 10",
        ),
        CommandSpec(
            name="list_projects",
            help="List all projects in the current user's workspace",
            add_arguments=_add_list_workspace_arguments,
            handler=_handle_list_projects,
            default_output="table",
            usage="caption list_projects [--full]",
            notes=(
                "Fetches workspace via /users/me/workspace, then /folders/{workspaceId}/projects.",
                "Default output condenses each project to a fixed field set; pass --full for the raw payloads.",
            ),
            example="caption --output json list_projects --full",
        ),
        CommandSpec(
            name="list_folders",
            help="List all folders in the current user's workspace",
            add_arguments=_add_list_workspace_arguments,
            handler=_handle_list_folders,
            default_output="table",
            usage="caption list_folders [--full]",
            notes=(
                "Fetches workspace via /users/me/workspace, then /folders/{workspaceId}/folders.",
                "Default output condenses each folder to a fixed field set; pass --full for the raw payloads.",
            ),
            example="caption --output json list_folders --full",
        ),
        CommandSpec(
            name="create_project",
            help="Create a new project in a workspace",
            add_arguments=_add_create_project_arguments,
            handler=_handle_create_project,
            usage="caption create_project <name> [--description TEXT] [--workspace-id UUID] [--dry-run]",
            notes=("If --workspace-id is omitted, workspace ID is resolved from /users/me/workspace.",),
            example="caption create_project \"My Project\" --description \"First draft\"",
        ),
        CommandSpec(
            name="create_folder",
            help="Create a new folder in a workspace",
            add_arguments=_add_create_folder_arguments,
            handler=_handle_create_folder,
            usage="caption create_folder <name> [--description TEXT] [--parent UUID] [--workspace-id UUID] [--dry-run]",
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
                "[--name TEXT] [--description TEXT|--clear-description] [--folder UUID|--clear-folder] [--dry-run]"
            ),
            notes=(
                "At least one field is required.",
                "Conflicting nullable pairs are rejected.",
                "--dry-run validates inputs and prints {dry_run, method, path, body} without sending.",
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
                "[--name TEXT] [--description TEXT|--clear-description] [--parent UUID|--clear-parent] [--dry-run]"
            ),
            notes=(
                "At least one field is required.",
                "Conflicting nullable pairs are rejected.",
                "--dry-run validates inputs and prints {dry_run, method, path, body} without sending.",
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
            name="tail",
            help="Stream finalized captions for one transcript",
            add_arguments=_add_tail_arguments,
            handler=_handle_tail,
            default_output="plain",
            usage="caption tail [transcript_id] [--duration SECS|--max-events N|--idle-timeout SECS]",
            notes=(
                "Streams finalized caption rows from the events gateway until interrupted or a bound is hit.",
                "Stdout is fixed line format: {channel}-{index}: {content}; example: microphone-1: We should ship on Friday.",
                "Timestamps, ids, and JSON framing are stripped by design; diagnostics go to stderr.",
                "During reconnect/backfill, output is deduped by caption id but not guaranteed to be createdAt-ordered.",
                "Keeps tailing the same transcript even if a new session starts.",
                "Deleted captions are noted on stderr only.",
                "Pass --duration, --max-events, or --idle-timeout when scripting.",
            ),
            example="caption tail --idle-timeout 300",
        ),
        CommandSpec(
            name="assign_speakers",
            help="Assign a speaker to transcript captions by channel and optional diarization index",
            add_arguments=_add_assign_speakers_arguments,
            handler=_handle_assign_speakers,
            usage=(
                "caption assign_speakers (--transcript-id UUID | --project-id UUID) "
                "--channel {0|1|2|microphone|loopback|external} [--index N] "
                "(--speaker-id UUID | --name TEXT) [--dry-run]"
            ),
            notes=(
                "POSTs to /transcripts/{transcriptId}/assign-speakers.",
                "--name reuses or creates a custom speaker scoped to the transcript's project (preferred).",
                "--speaker-id is not project-ownership-checked by the API; only pass IDs from the same project.",
                "--project-id fans out over every transcript in the project and aggregates the results.",
                "Omitting --index updates all diarization indexes in the channel.",
                "--dry-run validates inputs and prints {dry_run, method, path, body} without sending.",
            ),
            example="caption assign_speakers --transcript-id <transcript-uuid> --channel microphone --index 1 --name Alice",
        ),
        CommandSpec(
            name="list_speakers",
            help="Summarize speaker assignments for a transcript's captions",
            add_arguments=_add_list_speakers_arguments,
            handler=_handle_list_speakers,
            default_output="table",
            usage="caption list_speakers <transcript_id>",
            notes=(
                "Derives (channel, index, speakerId) groups from GET /transcripts/{transcriptId}/captions.",
                "Shows speaker IDs only; caption payloads do not include speaker names.",
                "Use it to pick --channel/--index targets before assign_speakers.",
            ),
            example="caption list_speakers <transcript-uuid>",
        ),
        CommandSpec(
            name="rename_speaker",
            help="Rename a custom speaker across a project",
            add_arguments=_add_rename_speaker_arguments,
            handler=_handle_rename_speaker,
            usage="caption rename_speaker <project_id> <speaker_id> --name TEXT [--dry-run]",
            notes=(
                "PATCHes /projects/{projectId}/speakers/{speakerId}.",
                "Only custom speakers can be renamed; user-backed speakers are rejected by the API.",
                "The rename applies to every caption using the speaker within the project.",
                "--dry-run validates inputs and prints {dry_run, method, path, body} without sending.",
            ),
            example="caption rename_speaker <project-uuid> <speaker-uuid> --name \"Alice\"",
        ),
        CommandSpec(
            name="list_matters",
            help="List matters from the hosted history server",
            add_arguments=_add_list_matters_arguments,
            handler=_handle_list_matters,
            needs_api=False,
            default_output="table",
            usage="caption list_matters [--include-one-shot] [--full] [--clerk-api-key TOKEN] [--org-id ORG]",
            notes=(
                "GETs https://history.caption.fyi/api/v1/projects.",
                "This is separate from list_projects, which uses the main Caption workspace API.",
                "Default output condenses each matter to id/name/full_name; pass --full for the raw payloads.",
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
                "--session-id VALUE [--project-name TEXT] [--test|--dry-run] [--yes] [--db-path PATH] "
                "[--clerk-api-key TOKEN] [--org-id ORG]"
            ),
            notes=(
                "Matches sessions by case-insensitive substring on the raw session ID; use * to select all sessions.",
                "--session-id '*' without --test requires --yes (it sends every session).",
                "--project-name overrides session.project in every built payload.",
                "Use --test (alias: --dry-run) to print the built JSON payloads without sending anything.",
                "Without --test, builds payloads from the local SQLite DB, then PUTs them to https://history.caption.fyi/api/v1/shares/{session_id}.",
                "Exits 4 (upstream failure) when any session fails to send; the error message embeds the full sent/failures report.",
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
                "[--project-id UUID|--project-name TEXT] [--title TEXT] [--dry-run] [--clerk-api-key TOKEN] [--org-id ORG]"
            ),
            notes=(
                "POSTs to https://history.caption.fyi/api/v1/projects/md.",
                "Reads raw_markdown from the file exactly as UTF-8 text.",
                "--title defaults to the Markdown filename.",
                "JSON output (the default) returns the full document; table/plain output truncates raw_markdown and plain_text to 100 characters unless --full is passed.",
                "--dry-run validates inputs and prints {dry_run, method, path, body} without sending.",
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
                "[--created-by USER] [--sort recent|most_starred] [--cursor CURSOR] [--limit N] [--full]"
            ),
            notes=(
                "GETs https://history.caption.fyi/api/v1/md.",
                "--tag and --created-by may be repeated; repeated values are sent as comma-separated query values.",
                "Default output condenses each document to summary fields; pass --full for the raw payloads.",
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
        api_token=getattr(args, "clerk_api_key", None) or os.getenv("CLERK_API_KEY"),
        meili_url=os.getenv("CAPTION_MEILI_URL"),
        cache_path=Path(args.cache_path),
        output=args.output,
    )
    dry_run_requested = bool(getattr(args, "dry_run", False))
    if selected_command.needs_api and not dry_run_requested:
        _require_api_url(config)
    if selected_command.needs_meili and not dry_run_requested:
        _require_meili_url(config)

    if args.command == "tail":
        if args.output_supplied:
            raise CliError("tail has one fixed stdout line format: {channel}-{index}: {content}")
        if args.output_file is not None:
            raise CliError("tail streams output and cannot use --output-file")
        selected_command.handler(config, args)
        return 0

    result = selected_command.handler(config, args)
    if args.command == "doctor":
        failed_probes = [probe for probe in result["probes"] if not probe["available"]]
        for probe in failed_probes:
            reason = probe["reason"] or "unknown reason"
            print(f"doctor: probe '{probe['name']}' failed: {reason}", file=sys.stderr)
        rendered = (
            render_doctor_output(result)
            if config.output == "plain"
            else render_output(result, config.output, command_name="doctor")
        )
        if args.output_file is not None:
            print(write_output_file(args.output_file, rendered, "doctor"), file=sys.stderr)
        else:
            print(rendered)
        return 1 if (failed_probes and args.strict) else 0

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
        print(write_output_file(output_file, rendered, args.command), file=sys.stderr)
        return 0

    emit_output(
        result,
        config.output,
        command_name=args.command,
        search_index=getattr(args, "index", None),
    )
    return 0
