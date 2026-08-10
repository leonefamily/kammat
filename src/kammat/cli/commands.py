"""command handlers and composition over public application facades."""

from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable, Iterable, List, Mapping, Optional, Sequence, Tuple

from kammat import __version__

from .model import (
    APPLICATION_EXIT_CODES,
    ConfigAssignment,
    PreparedPlanView,
    PresentationPolicy,
    cli_issue,
)
from .present import (
    RunPresenter,
    format_issue_text,
    format_json_document,
    format_prepared_plan_text,
    format_run_header,
    format_stage_list_text,
    format_validation_summary,
    plan_document,
    stage_list_document,
    validation_document,
)


@dataclass(frozen=True)
class CommandServices:
    load_run_config: Callable[..., Any]
    has_errors: Callable[..., bool]
    build_config_template: Callable[..., Any]
    write_config_template: Callable[..., Path]
    format_configuration_json: Callable[..., str]
    apply_config_overrides: Callable[..., Any]
    field_map: Mapping[str, Mapping[str, Any]]
    plan_selection_type: Callable[..., Any]
    build_plan: Callable[..., Any]
    build_execution_environment: Callable[..., Any]
    inspect_stage_availability: Callable[..., Any]
    build_run_context: Callable[..., Any]
    prepare_execution: Callable[..., Any]
    run_plan: Callable[..., Any]
    gui_launcher: Optional[Callable[[], Any]] = None


def default_services() -> CommandServices:
    """Load public facades only after one command is selected."""

    from kammat.main.configure import (
        FIELD_MAP,
        apply_config_overrides,
        build_config_template,
        format_configuration_json,
        has_errors,
        load_run_config,
        write_config_template,
    )
    from kammat.main.execution import (
        build_execution_environment,
        build_run_context,
        inspect_stage_availability,
        prepare_execution,
        run_plan,
    )
    from kammat.main.planning import PlanSelection, build_plan

    return CommandServices(
        load_run_config,
        has_errors,
        build_config_template,
        write_config_template,
        format_configuration_json,
        apply_config_overrides,
        FIELD_MAP,
        PlanSelection,
        build_plan,
        build_execution_environment,
        inspect_stage_availability,
        build_run_context,
        prepare_execution,
        run_plan,
    )


def _write(stream: Any, text: str) -> None:
    stream.write(text)
    flush = getattr(stream, "flush", None)
    if callable(flush):
        flush()


def _absolute(value: Any) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    return Path(os.path.abspath(os.fspath(path)))


def _has_errors(issues: Iterable[Any]) -> bool:
    return any(getattr(issue, "level", None) == "error" for issue in issues)


def _unique_issues(*groups: Iterable[Any]) -> Tuple[Any, ...]:
    result: List[Any] = []
    identities = set()
    for group in groups:
        for issue in group:
            identity = (
                getattr(issue, "code", None),
                getattr(issue, "level", None),
                getattr(issue, "field", None),
                getattr(issue, "message", None),
                getattr(issue, "hint", None),
            )
            if identity not in identities:
                identities.add(identity)
                result.append(issue)
    return tuple(result)


def _render_issues(
    issues: Iterable[Any],
    policy: PresentationPolicy,
    stderr: Any,
) -> None:
    for issue in issues:
        if policy.quiet and getattr(issue, "level", None) == "warning":
            continue
        _write(stderr, format_issue_text(issue, policy.color))


def parse_config_assignments(
    raw_values: Sequence[str],
    field_map: Mapping[str, Mapping[str, Any]],
) -> Tuple[Tuple[ConfigAssignment, ...], Tuple[Any, ...]]:
    """Parse and aggregate exact scalar stage-field assignments in argument order."""

    assignments: List[ConfigAssignment] = []
    issues: List[Any] = []
    seen = set()
    for index, token in enumerate(raw_values):
        field_label = "set[{0}]".format(index)
        if not isinstance(token, str) or "\x00" in token or "=" not in token:
            issues.append(cli_issue(
                "KAM-CLI-E110",
                field_label,
                "override must use section.field=value syntax",
            ))
            continue
        dotted, raw_value = token.split("=", 1)
        if dotted.count(".") != 1:
            issues.append(cli_issue(
                "KAM-CLI-E110",
                field_label,
                "override field must contain exactly one dot",
            ))
            continue
        stage, field = dotted.split(".", 1)
        if not stage or not field:
            issues.append(cli_issue(
                "KAM-CLI-E110",
                field_label,
                "override field components must be non-empty",
            ))
            continue
        if stage not in field_map or field not in field_map[stage]:
            issues.append(cli_issue(
                "KAM-CLI-E111",
                dotted,
                "override field is unknown or not permitted",
            ))
            continue
        if dotted in seen:
            issues.append(cli_issue(
                "KAM-CLI-E111",
                dotted,
                "duplicate override field is not permitted",
            ))
            continue
        seen.add(dotted)
        try:
            parsed = json.loads(raw_value)
        except json.JSONDecodeError:
            parsed = raw_value
        try:
            assignment = ConfigAssignment(dotted, raw_value, parsed)
        except (TypeError, ValueError):
            issues.append(cli_issue(
                "KAM-CLI-E112",
                dotted,
                "override value must be a finite JSON scalar or literal string",
            ))
            continue
        assignments.append(assignment)
    return tuple(assignments), tuple(issues)


def _load_effective(
    namespace: Any,
    services: CommandServices,
) -> Tuple[Optional[Any], Tuple[ConfigAssignment, ...], Tuple[Any, ...], int]:
    loaded = services.load_run_config(namespace.config_path)
    loaded_issues = tuple(loaded.issues)
    if loaded.config is None or services.has_errors(loaded_issues):
        return None, (), loaded_issues, 3
    assignments, syntax_issues = parse_config_assignments(
        tuple(getattr(namespace, "set_values", ()) or ()),
        services.field_map,
    )
    if syntax_issues:
        return None, assignments, _unique_issues(loaded_issues, syntax_issues), 3
    if not assignments:
        return loaded.config, assignments, loaded_issues, 0
    updated = services.apply_config_overrides(
        loaded.config,
        {assignment.field: assignment.parsed_value for assignment in assignments},
    )
    issues = _unique_issues(
        (item for item in loaded_issues if getattr(item, "level", None) == "warning"),
        updated.issues,
    )
    if updated.config is None or services.has_errors(issues):
        return None, assignments, issues, 3
    return updated.config, assignments, issues, 0


def _selection(namespace: Any, services: CommandServices) -> Any:
    return services.plan_selection_type(
        explicit_stages=tuple(namespace.stage),
        from_stage=namespace.from_stage,
        until_stage=namespace.until_stage,
        include_dependencies=namespace.include_dependencies,
    )


def _plan_failure(
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    assignments: Sequence[ConfigAssignment],
    issues: Sequence[Any],
    code: int,
) -> int:
    if policy.output_mode == "json":
        _write(stdout, format_json_document(plan_document(
            "plan", None, assignments, issues
        )))
    else:
        _render_issues(issues, policy, stderr)
    return code


def handle_config_init(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    services: CommandServices,
) -> int:
    del policy
    try:
        template = services.build_config_template(
            _absolute(namespace.output),
            namespace.profile,
            namespace.workspace,
        )
    except (OSError, TypeError, ValueError) as error:
        issue = cli_issue(
            "KAM-CLI-E101",
            "config init",
            "configuration template cannot be constructed ({0})".format(
                type(error).__name__
            ),
        )
        _write(stderr, format_issue_text(issue))
        return 5
    try:
        destination = services.write_config_template(template)
    except (OSError, TypeError, ValueError) as error:
        issue = cli_issue(
            "KAM-CLI-E102",
            "config init",
            "configuration template cannot be written ({0})".format(
                type(error).__name__
            ),
        )
        _write(stderr, format_issue_text(issue))
        return 5
    _write(stdout, str(destination) + "\n")
    return 0


def handle_config_validate(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    services: CommandServices,
) -> int:
    loaded = services.load_run_config(namespace.config_path)
    issues = tuple(loaded.issues)
    valid = loaded.config is not None and not services.has_errors(issues)
    code = 0 if valid else 3
    configuration = (
        loaded.config.config_path if loaded.config is not None
        else _absolute(namespace.config_path)
    )
    if namespace.json:
        _write(stdout, format_json_document(validation_document(
            configuration,
            loaded.source_version,
            valid,
            issues,
        )))
        return code
    _render_issues(issues, policy, stderr)
    if valid:
        warning_count = sum(issue.level == "warning" for issue in issues)
        _write(stdout, format_validation_summary(
            loaded.config,
            loaded.source_version,
            warning_count,
        ))
    return code


def handle_config_show(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    services: CommandServices,
) -> int:
    loaded = services.load_run_config(namespace.config_path)
    issues = tuple(loaded.issues)
    if loaded.config is None or services.has_errors(issues):
        _render_issues(issues, policy, stderr)
        return 3
    _render_issues(
        (issue for issue in issues if issue.level == "warning"),
        policy,
        stderr,
    )
    _write(stdout, services.format_configuration_json(
        loaded.config,
        resolved=namespace.resolved,
    ))
    return 0


def handle_stage_list(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    services: CommandServices,
) -> int:
    config = None
    issues: Tuple[Any, ...] = ()
    configuration = None
    if namespace.config_path is not None:
        loaded = services.load_run_config(namespace.config_path)
        issues = tuple(loaded.issues)
        configuration = (
            loaded.config.config_path if loaded.config is not None
            else _absolute(namespace.config_path)
        )
        if loaded.config is None or services.has_errors(issues):
            if namespace.json:
                _write(stdout, format_json_document(stage_list_document(
                    configuration, (), issues
                )))
            else:
                _render_issues(issues, policy, stderr)
            return 3
        config = loaded.config
    environment = services.build_execution_environment()
    stages = services.inspect_stage_availability(config, environment)
    if namespace.json:
        _write(stdout, format_json_document(stage_list_document(
            configuration, stages, issues
        )))
    else:
        _render_issues(
            (issue for issue in issues if issue.level == "warning"),
            policy,
            stderr,
        )
        _write(stdout, format_stage_list_text(stages, policy.verbosity))
    return 0


def handle_plan(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    services: CommandServices,
) -> int:
    config, assignments, config_issues, code = _load_effective(namespace, services)
    if config is None:
        return _plan_failure(
            policy, stdout, stderr, assignments, config_issues, code
        )
    selection = _selection(namespace, services)
    try:
        planned = services.build_plan(config, selection)
    except Exception as error:
        owner_issues = tuple(getattr(error, "issues", ()))
        if owner_issues:
            return _plan_failure(
                policy,
                stdout,
                stderr,
                assignments,
                _unique_issues(config_issues, owner_issues),
                3,
            )
        raise
    if planned.plan is None:
        return _plan_failure(
            policy,
            stdout,
            stderr,
            assignments,
            _unique_issues(config_issues, planned.issues),
            4,
        )
    environment = services.build_execution_environment()
    context = services.build_run_context(config.workspace, lambda event: None)
    preparation = services.prepare_execution(planned.plan, context, environment)
    if preparation.issues:
        return _plan_failure(
            policy,
            stdout,
            stderr,
            assignments,
            _unique_issues(config_issues, preparation.issues),
            4,
        )
    view = PreparedPlanView(planned.plan, assignments, preparation.stages)
    if policy.output_mode == "json":
        _write(stdout, format_json_document(plan_document(
            "plan",
            view,
            assignments,
            tuple(issue for issue in config_issues if issue.level == "warning"),
        )))
    else:
        _render_issues(
            (issue for issue in config_issues if issue.level == "warning"),
            policy,
            stderr,
        )
        _write(stdout, format_prepared_plan_text(view, policy.verbosity))
    return 0


def handle_run(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    services: CommandServices,
) -> int:
    config, assignments, config_issues, code = _load_effective(namespace, services)
    del assignments
    if config is None:
        _render_issues(config_issues, policy, stderr)
        return code
    selection = _selection(namespace, services)
    try:
        planned = services.build_plan(config, selection)
    except Exception as error:
        owner_issues = tuple(getattr(error, "issues", ()))
        if owner_issues:
            _render_issues(_unique_issues(config_issues, owner_issues), policy, stderr)
            return 3
        raise
    if planned.plan is None:
        _render_issues(_unique_issues(config_issues, planned.issues), policy, stderr)
        return 4
    _render_issues(
        _unique_issues(
            (issue for issue in config_issues if issue.level == "warning"),
            planned.issues,
        ),
        policy,
        stderr,
    )
    if not policy.quiet:
        _write(stdout, format_run_header(__version__, planned.plan))
    environment = services.build_execution_environment()
    presenter = RunPresenter(
        policy,
        planned.plan,
        lambda text: _write(stdout, text),
        lambda text: _write(stderr, text),
    )
    context = services.build_run_context(config.workspace, presenter.emit)
    result = services.run_plan(
        planned.plan,
        context,
        environment=environment,
    )
    presenter.finish(result)
    return result.exit_code


def handle_gui(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    services: CommandServices,
) -> int:
    del namespace, policy, stdout
    try:
        launcher = services.gui_launcher
        if launcher is None:
            from kammat.gui.main import main as launcher
        value = launcher()
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        issue = cli_issue(
            "KAM-CLI-E201",
            "gui",
            "GUI cannot be launched ({0})".format(type(error).__name__),
        )
        _write(stderr, format_issue_text(issue))
        return 5
    if value is None:
        return 0
    if type(value) is int and value in APPLICATION_EXIT_CODES:
        return value
    issue = cli_issue(
        "KAM-CLI-E201",
        "gui",
        "GUI returned an unsupported application code",
    )
    _write(stderr, format_issue_text(issue))
    return 5


def dispatch(
    namespace: Any,
    policy: PresentationPolicy,
    stdout: Any,
    stderr: Any,
    *,
    legacy_invocation: bool = False,
    services: Optional[CommandServices] = None,
) -> int:
    """Dispatch one parsed leaf through an injected or production service bundle."""

    effective = services or default_services()
    if legacy_invocation and not policy.quiet:
        warning = cli_issue(
            "KAM-CLI-W100",
            "argv",
            "historical top-level configuration invocation was adapted to run",
            "use: kammat run --config FILE",
        )
        _write(stderr, format_issue_text(warning, policy.color))
    handlers = {
        "gui": handle_gui,
        "config-init": handle_config_init,
        "config-validate": handle_config_validate,
        "config-show": handle_config_show,
        "stage-list": handle_stage_list,
        "plan": handle_plan,
        "run": handle_run,
    }
    token = getattr(namespace, "handler_token", None)
    handler = handlers.get(token)
    if handler is None:
        issue = cli_issue("KAM-CLI-E100", "command", "command handler is unavailable")
        _write(stderr, format_issue_text(issue, policy.color))
        return 5
    if token == "run" and namespace.dry_run:
        return handle_plan(namespace, policy, stdout, stderr, effective)
    return handler(namespace, policy, stdout, stderr, effective)


__all__ = [
    "CommandServices",
    "default_services",
    "dispatch",
    "handle_config_init",
    "handle_config_show",
    "handle_config_validate",
    "handle_gui",
    "handle_plan",
    "handle_run",
    "handle_stage_list",
    "parse_config_assignments",
]
