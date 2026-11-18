from __future__ import annotations

import argparse
import difflib
import importlib.metadata
import inspect
import os
import sys
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

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
    command_tail,
    command_token,
    dl_transcript,
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


CONTRACT_VERSION = "3"

EXIT_CODE_DICTIONARY = {
    str(EXIT_SUCCESS): "success (including empty results)",
    str(EXIT_USER_INPUT): "user-input error (bad value, bad local file path, conflicting flags); also doctor --strict probe failure",
    str(EXIT_USAGE): "usage error (argparse: unknown command, unknown flag, missing argument)",
    str(EXIT_CONFIG): "configuration error (missing CAPTION_API_URL, CLERK_API_KEY, or CAPTION_MEILI_URL)",
    str(EXIT_UPSTREAM): "upstream failure (HTTP error, Meilisearch error, malformed server response)",
    str(EXIT_NOT_FOUND): "remote resource not found (HTTP 404)",
}

ENV_VAR_DICTIONARY = {
    "CAPTION_API_URL": "required for Caption API commands",
    "CLERK_API_KEY": "required for authenticated Caption API calls",
    "CAPTION_MEILI_URL": "required for token and search",
}

GLOBAL_OPTION_DICTIONARY = {
    "--env-file": "dotenv file loaded before env resolution (default: $PWD/.env)",
    "--cache-path": "search token cache path (default: search-token.json)",
    "--output": "output format: json, table, or md (per-command defaults vary)",
    "--output-file": "write rendered command output to PATH",
}

SEARCH_INDEX_EXAMPLES = (DEFAULT_SEARCH_INDEX, "transcript_blocks_v2")

# Commands whose output handling differs from the standard render/emit path.
_COMMAND_DOCTOR = "doctor"
_COMMAND_TAIL = "tail"

_Handler = Callable[[RuntimeConfig, argparse.Namespace], Any]


def _search_index_examples_help() -> str:
    examples = tuple(dict.fromkeys(SEARCH_INDEX_EXAMPLES))
    return ", ".join(examples)


def _tool_version() -> str:
    try:
        return importlib.metadata.version("caption-cli")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


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


def _aligned_rows(rows: Mapping[str, str]) -> list[str]:
    # Two-column help rows padded to the longest key, e.g. "  KEY    meaning".
    width = max(len(key) for key in rows)
    return [f"  {key.ljust(width)}  {meaning}" for key, meaning in rows.items()]


def _default_outputs_help(specs: Sequence[CommandSpec]) -> str:
    # Group commands by default --output, e.g. "table: search, list_projects".
    groups: dict[str, list[str]] = {}
    for spec in specs:
        groups.setdefault(spec.default_output, []).append(spec.name)

    return "; ".join(f"{fmt}: {', '.join(names)}" for fmt, names in groups.items())


def _top_level_help_epilog(specs: Sequence[CommandSpec]) -> str:
    lines = [
        "Agent quick start",
        "  caption guide                detailed agent handbook (Markdown, offline)",
        "  caption --output json guide  machine-readable contract: commands, exit codes, env vars",
        "  caption --output json <cmd>  structured output on any read command (stdout=data, stderr=diagnostics)",
        "  caption --output json doctor --strict   health probe; non-zero exit when a feature is unavailable",
        "  --full                       raw server payloads on list_projects/list_folders",
        "",
        "Environment",
    ]

    # Env vars and global options come from the shared dictionaries so help, guide, and JSON agree.
    lines.extend(_aligned_rows(ENV_VAR_DICTIONARY))
    lines += ["", "Global options"]
    lines.extend(_aligned_rows(GLOBAL_OPTION_DICTIONARY))
    lines.append(f"  default --output per command: {_default_outputs_help(specs)}")
    lines += ["", "Exit codes"]
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
    specs = _COMMAND_SPECS
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


def _add_no_arguments(_: argparse.ArgumentParser) -> None:
    return None


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
    _add_api_auth_arguments(parser)
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
            f"Index UID (default: {DEFAULT_SEARCH_INDEX}; "
            f"examples: {_search_index_examples_help()})."
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
    parser.add_argument(
        "--link",
        default=None,
        help=(
            "Share link URL or token (https://app.caption.fyi/shared/<token>); "
            "tails the shared project as a guest, CLERK_API_KEY is not required and not sent"
        ),
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


def _bind(command: Callable[..., Any]) -> _Handler:
    # Generic handler: pass parsed args matching the command's parameter names
    # as keywords, e.g. args.full -> command_list_projects(config, full=...).
    # Resolves the command by name at call time so monkeypatching cli.<name> works.
    def handler(config: RuntimeConfig, args: argparse.Namespace) -> Any:
        resolved = globals()[command.__name__]
        parsed = vars(args)
        names = list(inspect.signature(resolved).parameters)[1:]
        return resolved(config, **{name: parsed[name] for name in names if name in parsed})

    return handler


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
            for spec in _COMMAND_SPECS
        ],
        "global_options": dict(GLOBAL_OPTION_DICTIONARY),
        "exit_codes": EXIT_CODE_DICTIONARY,
        "env_vars": ENV_VAR_DICTIONARY,
    }


def build_guide() -> str:
    lines = [
        "# caption — agent guide",
        "",
        "caption drives the Caption API and Meilisearch search.",
        "",
        "## Rules of thumb",
        "",
        "- stdout is data; stderr is diagnostics. Pipe `--output json` output straight into `jq`.",
        "- Most read commands accept `--output json`; streaming commands document their fixed stdout format.",
        "- Condensed views announce themselves on stderr; add `--full` for the raw server payload.",
        "- `caption --output json guide` prints this contract machine-readable (commands, exit codes, env vars); works offline.",
        "- Health-check with `caption --output json doctor --strict` (non-zero exit when a feature probe fails).",
        "",
        "## Global options",
        "",
        "Global flags must come before the subcommand.",
        "",
    ]
    lines.extend(f"- `{flag}` — {meaning}" for flag, meaning in GLOBAL_OPTION_DICTIONARY.items())
    lines += [
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
        "",
        "## Commands",
    ]
    for spec in _COMMAND_SPECS:
        requirements = []
        if spec.needs_api:
            requirements.append("Caption API (CAPTION_API_URL)")
        if spec.needs_meili:
            requirements.append("Meilisearch (CAPTION_MEILI_URL)")
        lines += [
            "",
            f"### {spec.name}",
            "",
            f"{spec.help}.",
            "",
            f"- usage: `{spec.usage}`",
            f"- default output: {spec.default_output}",
        ]
        if requirements:
            lines.append(f"- requires: {', '.join(requirements)}")
        lines.extend(f"- {note}" for note in spec.notes)
        if spec.example:
            lines.append(f"- example: `{spec.example}`")
    return "\n".join(lines)


def _handle_guide(config: RuntimeConfig, _: argparse.Namespace) -> Any:
    if config.output == "json":
        return build_capabilities()
    return build_guide()


def render_doctor_output(result: Mapping[str, Any]) -> str:
    # Available features are the names of passing probes.
    features = [probe["name"] for probe in result.get("probes") or () if probe["available"]]
    return "\n".join(["CAPTION FEATURES AVAILABLE:", *features])


def _command_specs() -> Sequence[CommandSpec]:
    return (
        CommandSpec(
            name=_COMMAND_DOCTOR,
            help="Probe available Caption features",
            add_arguments=_add_doctor_arguments,
            handler=_bind(command_doctor),
            needs_api=False,
            default_output="plain",
            usage="caption doctor [--strict] [--clerk-api-key TOKEN]",
            notes=(
                "Probes Caption API core support.",
                "Failed probes print their reason to stderr; pass --strict to also exit non-zero.",
                "Use --output json for the full structured result: {probes: [{name, available, reason}]}.",
            ),
            example="caption --output json doctor --strict",
        ),
        CommandSpec(
            name="guide",
            help="Print the detailed agent handbook for this CLI",
            add_arguments=_add_no_arguments,
            handler=_handle_guide,
            needs_api=False,
            default_output="md",
            usage="caption [--output json] guide",
            notes=(
                "Markdown handbook generated from the live command table; needs no network or credentials.",
                "Covers global options, output formats, exit codes, env vars, auth order, and per-command usage.",
                "caption --output json guide prints the machine-readable contract (commands, exit codes, env vars).",
            ),
            example="caption guide",
        ),
        CommandSpec(
            name="token",
            help="Fetch and cache /search/token credentials",
            add_arguments=_add_token_arguments,
            handler=_bind(command_token),
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
            handler=_bind(command_search),
            needs_meili=True,
            default_output="table",
            usage="caption search <query> [--index INDEX] [--limit N] [--show-dupes]",
            notes=(
                "--limit must be >= 1.",
                "Uses cached token and refreshes once on Meili auth failures.",
            ),
            example=f"caption search \"roadmap\" --index {DEFAULT_SEARCH_INDEX} --limit 10",
        ),
        CommandSpec(
            name="list_projects",
            help="List all projects in the current user's workspace",
            add_arguments=_add_list_workspace_arguments,
            handler=_bind(command_list_projects),
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
            handler=_bind(command_list_folders),
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
            handler=_bind(command_create_project),
            usage="caption create_project <name> [--description TEXT] [--workspace-id UUID] [--dry-run]",
            notes=("If --workspace-id is omitted, workspace ID is resolved from /users/me/workspace.",),
            example="caption create_project \"My Project\" --description \"First draft\"",
        ),
        CommandSpec(
            name="create_folder",
            help="Create a new folder in a workspace",
            add_arguments=_add_create_folder_arguments,
            handler=_bind(command_create_folder),
            usage="caption create_folder <name> [--description TEXT] [--parent UUID] [--workspace-id UUID] [--dry-run]",
            notes=("If --workspace-id is omitted, workspace ID is resolved from /users/me/workspace.",),
            example="caption create_folder \"My Folder\" --parent <parent-folder-uuid>",
        ),
        CommandSpec(
            name="edit_project",
            help="Edit a project via PATCH /projects/{projectId}",
            add_arguments=_add_edit_project_arguments,
            handler=_bind(command_edit_project),
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
            handler=_bind(command_edit_folder),
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
            handler=_bind(dl_transcript),
            default_output="md",
            usage="caption dl_transcript <transcript_id> [--timestamp]",
            notes=(
                "Default output strips leading timestamps from each transcript line for token efficiency.",
                "Pass --timestamp to preserve them in output.",
            ),
            example="caption --output json dl_transcript <transcript-uuid>",
        ),
        CommandSpec(
            name=_COMMAND_TAIL,
            help="Stream finalized captions for one transcript",
            add_arguments=_add_tail_arguments,
            handler=_bind(command_tail),
            default_output="plain",
            usage="caption tail [transcript_id] [--link URL_OR_TOKEN] [--duration SECS|--max-events N|--idle-timeout SECS]",
            notes=(
                "Streams finalized caption rows from the events gateway until interrupted or a bound is hit.",
                "--link accepts a share URL (https://app.caption.fyi/shared/<token>) or bare token and tails the shared project as a guest; CLERK_API_KEY is not required and never sent in link mode (CAPTION_API_URL is still required).",
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
            handler=_bind(command_assign_speakers),
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
            handler=_bind(command_list_speakers),
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
            handler=_bind(command_rename_speaker),
            usage="caption rename_speaker <project_id> <speaker_id> --name TEXT [--dry-run]",
            notes=(
                "PATCHes /projects/{projectId}/speakers/{speakerId}.",
                "Only custom speakers can be renamed; user-backed speakers are rejected by the API.",
                "The rename applies to every caption using the speaker within the project.",
                "--dry-run validates inputs and prints {dry_run, method, path, body} without sending.",
            ),
            example="caption rename_speaker <project-uuid> <speaker-uuid> --name \"Alice\"",
        ),
    )


# Built once at import, before any monkeypatching, so _bind captures the real command names.
_COMMAND_SPECS = _command_specs()


def _run_tail(spec: CommandSpec, config: RuntimeConfig, args: argparse.Namespace) -> int:
    # Streams to stdout itself; rendering options do not apply.
    if args.output_supplied:
        raise CliError("tail has one fixed stdout line format: {channel}-{index}: {content}")
    if args.output_file is not None:
        raise CliError("tail streams output and cannot use --output-file")

    spec.handler(config, args)
    return EXIT_SUCCESS


def _run_doctor(spec: CommandSpec, config: RuntimeConfig, args: argparse.Namespace) -> int:
    # Reports failed probes on stderr; --strict turns them into a non-zero exit.
    result = spec.handler(config, args)
    failed_probes = [probe for probe in result["probes"] if not probe["available"]]
    for probe in failed_probes:
        reason = probe["reason"] or "unknown reason"
        print(f"doctor: probe '{probe['name']}' failed: {reason}", file=sys.stderr)

    rendered = (
        render_doctor_output(result)
        if config.output == "plain"
        else render_output(result, config.output, command_name=spec.name)
    )
    if args.output_file is not None:
        print(write_output_file(args.output_file, rendered, spec.name), file=sys.stderr)
    else:
        print(rendered)
    return EXIT_USER_INPUT if (failed_probes and args.strict) else EXIT_SUCCESS


def _run_standard(spec: CommandSpec, config: RuntimeConfig, args: argparse.Namespace) -> int:
    # Render the result to --output-file or emit it to stdout.
    result = spec.handler(config, args)
    output_file = args.output_file

    if output_file is not None:
        rendered = render_output(
            result,
            config.output,
            command_name=args.command,
            search_index=getattr(args, "index", None),
        )
        print(write_output_file(output_file, rendered, args.command), file=sys.stderr)
        return EXIT_SUCCESS

    emit_output(
        result,
        config.output,
        command_name=args.command,
        search_index=getattr(args, "index", None),
    )
    return EXIT_SUCCESS


_Runner = Callable[[CommandSpec, RuntimeConfig, argparse.Namespace], int]

# Per-command output handling; commands not listed use _run_standard.
_RUNNERS: dict[str, _Runner] = {
    _COMMAND_DOCTOR: _run_doctor,
    _COMMAND_TAIL: _run_tail,
}


def run(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    selected_command = next(spec for spec in _COMMAND_SPECS if spec.name == args.command)

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

    runner = _RUNNERS.get(selected_command.name, _run_standard)
    return runner(selected_command, config, args)
