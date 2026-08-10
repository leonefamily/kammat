"""Canonical standard-library parser, compatibility adapter, and CLI boundary."""

import argparse
import sys
from typing import Any, List, Optional, Sequence, Tuple

from kammat import __version__

from .model import PresentationPolicy, cli_issue


def _formatter(prog: str) -> argparse.HelpFormatter:
    return argparse.RawDescriptionHelpFormatter(prog, max_help_position=28)


def _leaf(
    subparsers: Any,
    name: str,
    help_text: str,
    description: str,
    example: str,
) -> argparse.ArgumentParser:
    return subparsers.add_parser(
        name,
        help=help_text,
        description=description,
        epilog="Example:\n  " + example,
        formatter_class=_formatter,
    )


def _add_selection(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--stage",
        action="append",
        default=[],
        metavar="NAME",
        help="select a stage by canonical name; repeat to preserve explicit order",
    )
    parser.add_argument(
        "--from",
        dest="from_stage",
        metavar="NAME",
        help="start a canonical open or closed stage range",
    )
    parser.add_argument(
        "--until",
        dest="until_stage",
        metavar="NAME",
        help="finish a canonical open or closed stage range",
    )
    parser.add_argument(
        "--no-deps",
        action="store_false",
        dest="include_dependencies",
        default=True,
        help="exclude dependency stages unless explicitly selected",
    )
    parser.add_argument(
        "--set",
        action="append",
        default=[],
        dest="set_values",
        metavar="SECTION.FIELD=VALUE",
        help="apply one in-memory scalar configuration override; repeat as needed",
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the exact parser without importing application or GUI code."""

    parser = argparse.ArgumentParser(
        prog="kammat",
        description="Configure, inspect, plan, and run the Kammat pipeline.",
        epilog=(
            "Global presentation options must precede COMMAND.\n"
            "Use 'kammat COMMAND --help' for command paths and examples."
        ),
        formatter_class=_formatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="kammat " + __version__,
        help="print the package version and exit",
    )
    presentation = parser.add_mutually_exclusive_group()
    presentation.add_argument(
        "--quiet",
        action="store_true",
        help="suppress warnings and nonessential run output",
    )
    presentation.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="add information; repeat once for debug detail",
    )
    parser.add_argument(
        "--no-color",
        action="store_true",
        help="disable ANSI semantic labels",
    )
    commands = parser.add_subparsers(
        dest="command",
        metavar="COMMAND",
        required=True,
    )

    gui = _leaf(
        commands,
        "gui",
        "launch the existing graphical interface",
        "Launch the existing GUI lazily without changing its run behavior.",
        "kammat gui",
    )
    gui.set_defaults(handler_token="gui")

    config = commands.add_parser(
        "config",
        help="create, validate, or display configuration",
        description="Create, validate, or display schema-version-1 configuration.",
        formatter_class=_formatter,
    )
    config_commands = config.add_subparsers(
        dest="config_command",
        metavar="COMMAND",
        required=True,
    )
    config_init = _leaf(
        config_commands,
        "init",
        "create a deterministic starting configuration",
        "Create a minimal or full JSON template without overwriting or creating directories.",
        "kammat config init --output ./study.json --profile full --workspace ./workspace",
    )
    config_init.add_argument(
        "--output",
        required=True,
        metavar="FILE",
        help="new JSON destination; its real parent must already exist",
    )
    config_init.add_argument(
        "--profile",
        choices=("minimal", "full"),
        default="minimal",
        help="template profile (default: minimal)",
    )
    config_init.add_argument(
        "--workspace",
        metavar="PATH",
        help="workspace relative to the template parent (default: ./workspace)",
    )
    config_init.set_defaults(handler_token="config-init")

    config_validate = _leaf(
        config_commands,
        "validate",
        "validate configuration without writing or executing",
        "Load once and report all ordered configuration diagnostics without side effects.",
        "kammat config validate --config ./study.json --json",
    )
    config_validate.add_argument(
        "-c",
        "--config",
        dest="config_path",
        required=True,
        metavar="FILE",
        help="JSON configuration; contained relative paths use its parent",
    )
    config_validate.add_argument(
        "--json",
        action="store_true",
        help="emit one schema-version-1 validation document",
    )
    config_validate.set_defaults(handler_token="config-validate")

    config_show = _leaf(
        config_commands,
        "show",
        "display normalized effective configuration",
        "Display schema-version-1 JSON in portable or resolved path form without writing.",
        "kammat config show --config ./study.json --resolved",
    )
    config_show.add_argument(
        "-c",
        "--config",
        dest="config_path",
        required=True,
        metavar="FILE",
        help="JSON configuration; contained relative paths use its parent",
    )
    config_show.add_argument(
        "--resolved",
        action="store_true",
        help="emit normalized absolute native paths (default: portable paths)",
    )
    config_show.set_defaults(handler_token="config-show")

    stage = commands.add_parser(
        "stage",
        help="inspect canonical pipeline stages",
        description="Inspect canonical stage and runtime metadata without starting tools.",
        formatter_class=_formatter,
    )
    stage_commands = stage.add_subparsers(
        dest="stage_command",
        metavar="COMMAND",
        required=True,
    )
    stage_list = _leaf(
        stage_commands,
        "list",
        "list canonical stages and runtime availability",
        "List the exact canonical registry with bounded read-only runtime inspection.",
        "kammat -v stage list --config ./study.json",
    )
    stage_list.add_argument(
        "-c",
        "--config",
        dest="config_path",
        metavar="FILE",
        help="optional JSON configuration for exact runtime metadata",
    )
    stage_list.add_argument(
        "--json",
        action="store_true",
        help="emit one schema-version-1 stage inventory document",
    )
    stage_list.set_defaults(handler_token="stage-list")

    plan = _leaf(
        commands,
        "plan",
        "preview selected stages and prepared invocations",
        "Load, select, plan, and preflight without creating workspace, logs, or processes.",
        "kammat -vv plan --config ./study.json --stage population --set population.ncores=4 --json",
    )
    plan.add_argument(
        "-c",
        "--config",
        dest="config_path",
        required=True,
        metavar="FILE",
        help="JSON configuration; contained relative paths use its parent",
    )
    _add_selection(plan)
    plan.add_argument(
        "--json",
        action="store_true",
        help="emit one CLI description json profile (that can be streamed to other components as machine ready in future) for example MATSim.",
    )
    plan.set_defaults(handler_token="plan")

    run = _leaf(
        commands,
        "run",
        "execute selected stages through the shared runner",
        "Load, select, and execute through the runner, or preview with --dry-run.",
        "kammat run --config ./study.json --from population --until analysis --dry-run",
    )
    run.add_argument(
        "-c",
        "--config",
        dest="config_path",
        required=True,
        metavar="FILE",
        help="JSON configuration; contained relative paths use its parent",
    )
    _add_selection(run)
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="use the exact plan/preflight presentation path without execution",
    )
    run.set_defaults(handler_token="run")
    return parser


def adapt_legacy_argv(argv: Sequence[str]) -> Tuple[List[str], bool]:
    """Adapt only the exact historical two-token configuration invocation."""

    values = list(argv)
    if len(values) == 2 and values[0] in {"-c", "--config-path"}:
        return ["run", "--config", values[1]], True
    return values, False


def _isatty(stream: Any) -> bool:
    method = getattr(stream, "isatty", None)
    if not callable(method):
        return False
    try:
        return method() is True
    except OSError:
        return False


def _validate_namespace(parser: argparse.ArgumentParser, namespace: Any) -> None:
    if namespace.verbose > 2:
        parser.error("-v/--verbose may be specified at most twice")
    if getattr(namespace, "handler_token", None) in {"plan", "run"}:
        if namespace.stage and (namespace.from_stage is not None or namespace.until_stage is not None):
            parser.error("--stage cannot be combined with --from or --until")


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    stdout: Optional[Any] = None,
    stderr: Optional[Any] = None,
    services: Optional[Any] = None,
) -> int:
    """Parse, dispatch, present, and return one stable application code."""

    output = sys.stdout if stdout is None else stdout
    diagnostics = sys.stderr if stderr is None else stderr
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    if not effective_argv:
        parser.print_help(file=output)
        return 0
    canonical_argv, legacy = adapt_legacy_argv(effective_argv)
    namespace = parser.parse_args(canonical_argv)
    _validate_namespace(parser, namespace)
    output_mode = "json" if (
        getattr(namespace, "json", False)
        or getattr(namespace, "handler_token", None) == "config-show"
    ) else "text"
    color = (
        output_mode == "text"
        and not namespace.no_color
        and _isatty(output)
    )
    policy = PresentationPolicy(
        namespace.quiet,
        namespace.verbose,
        color,
        output_mode,
    )
    try:
        from .commands import dispatch

        return dispatch(
            namespace,
            policy,
            output,
            diagnostics,
            legacy_invocation=legacy,
            services=services,
        )
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        from .present import format_issue_text

        issue = cli_issue(
            "KAM-CLI-E100",
            "command",
            "controlled command failure ({0})".format(type(error).__name__),
        )
        diagnostics.write(format_issue_text(issue, policy.color))
        flush = getattr(diagnostics, "flush", None)
        if callable(flush):
            flush()
        return 5


__all__ = ["adapt_legacy_argv", "build_parser", "main"]
