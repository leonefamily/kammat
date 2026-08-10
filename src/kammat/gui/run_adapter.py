"""Whole-plan worker bridge and bounded standalone GUI-tool process port."""

import math
from pathlib import Path
import re
import subprocess
import sys
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Sequence, Tuple

from kammat.main.configuration import (
    FIELD_MAP,
    GUI_KEYS,
    SCHEMA,
    FieldSpec,
    RunConfig,
    apply_config_overrides,
    create_config,
    has_errors,
    load_run_config,
    materialize_workspace,
    write_settings,
)
from kammat.main.execution import (
    ExecutionEnvironment,
    PipelineRunner,
    RunEvent,
    build_run_context,
    run_plan,
)
from kammat.main.planning import (
    ExecutionPlan,
    PlanSelection,
    build_plan,
)

from .run_model import (
    GuiIssue,
    GuiRunCompletion,
    GuiRunEventEnvelope,
    GuiRunSession,
    gui_issue,
)


PIPELINE_EVENT_KEY = "-KAMMAT-PIPELINE-EVENT-"
PIPELINE_DONE_KEY = "-KAMMAT-PIPELINE-DONE-"
RESULT_STAGES = ("analysis", "comparison", "gis")
GUI_TOOL_FILENAMES = frozenset({
    "decay_diagrams.py",
    "pt_counts.py",
    "results.py",
    "ribbon_diagrams.py",
    "vehicle_counts.py",
})
_INTEGER = re.compile(r"^[+-]?[0-9]+$")


def collect_main_gui_values(values: Mapping[str, Any]) -> Mapping[str, Any]:
    """Select only schema-owned primitive GUI inputs from one form snapshot."""

    if not isinstance(values, Mapping):
        raise TypeError("main GUI values must be a mapping")
    return {
        key: values[key]
        for key in GUI_KEYS
        if key in values
    }


def prepare_main_gui_plan(
    values: Mapping[str, Any],
    *,
    config_factory: Callable[[Mapping[str, Any]], Any] = create_config,
    planner: Callable[[RunConfig, PlanSelection], Any] = build_plan,
) -> Tuple[Optional[RunConfig], Optional[ExecutionPlan], Tuple[Any, ...]]:
    """Create and plan one main-form snapshot through the shared services."""

    config_result = config_factory(collect_main_gui_values(values))
    issues = tuple(config_result.issues)
    if config_result.config is None or has_errors(issues):
        return config_result.config, None, issues
    plan_result = planner(config_result.config, PlanSelection())
    combined = issues + tuple(plan_result.issues)
    if plan_result.plan is None or has_errors(plan_result.issues):
        return config_result.config, None, combined
    return config_result.config, plan_result.plan, combined


def persist_main_gui_plan(
    config: RunConfig,
    plan: ExecutionPlan,
    save_form: Callable[[Path], Any],
    *,
    materializer: Callable[[RunConfig], Any] = materialize_workspace,
    writer: Callable[[RunConfig], Any] = write_settings,
    loader: Callable[[Path], Any] = load_run_config,
) -> Optional[GuiIssue]:
    """Persist the exact planned main run before worker installation."""

    if not isinstance(config, RunConfig) or not isinstance(plan, ExecutionPlan):
        raise TypeError("main GUI persistence requires config and plan")
    if plan.config is not config:
        raise ValueError("main GUI plan must retain the exact RunConfig")
    if not callable(save_form):
        raise TypeError("main GUI form saver must be callable")
    try:
        materializer(config)
        saved = save_form(config.workspace / "settings.sg")
        if saved is False:
            raise OSError("form settings save failed")
        writer(config)
        persisted = loader(config.config_path)
        if persisted.config != plan.config or has_errors(persisted.issues):
            raise OSError("persisted settings differ from plan")
    except Exception as error:
        return gui_issue(
            "KAM-GUI-E105",
            "settings",
            "settings persistence failed ({0})".format(type(error).__name__),
        )
    return None


def results_field_specs() -> Mapping[str, FieldSpec]:
    """Return ordered editable results fields from the schema."""

    fields = {}
    for stage in RESULT_STAGES:
        for spec in SCHEMA[stage]:
            if spec.name != "launch":
                fields[stage + "." + spec.name] = FIELD_MAP[stage][spec.name]
    return MappingProxyType(fields)


def results_form_values(config: RunConfig) -> Mapping[str, Any]:
    """Project one immutable loaded config into exact results widget values."""

    if not isinstance(config, RunConfig):
        raise TypeError("results form requires RunConfig")
    values = {}
    for stage in RESULT_STAGES:
        values[stage + "|launch|"] = config.stages[stage]["launch"]
        for dotted in results_field_specs():
            owner, field = dotted.split(".", 1)
            if owner == stage:
                value = config.stages[stage][field]
                if value is None:
                    values[dotted] = ""
                elif isinstance(value, Path):
                    values[dotted] = str(value)
                else:
                    values[dotted] = value
    return MappingProxyType(values)


def prepare_results_plan(
    config: RunConfig,
    values: Mapping[str, Any],
    *,
    override_service: Callable[[RunConfig, Mapping[str, Any]], Any] = apply_config_overrides,
    planner: Callable[[RunConfig, PlanSelection], Any] = build_plan,
) -> Tuple[Optional[ExecutionPlan], Tuple[Any, ...]]:
    """Apply typed copied edits and plan exact explicit results selections."""

    fields = results_field_specs()
    changes, conversion_issues = results_changes_from_values(values, fields)
    issues = list(conversion_issues)
    selected = []
    for stage in RESULT_STAGES:
        key = stage + "|launch|"
        launch = values.get(key)
        if type(launch) is not bool:
            issues.append(gui_issue(
                "KAM-GUI-E104",
                stage + ".launch",
                "invalid bool value",
            ))
        elif launch:
            selected.append(stage)
    if issues:
        return None, tuple(issues)
    config_result = override_service(config, changes)
    issues.extend(config_result.issues)
    if config_result.config is None or has_errors(config_result.issues):
        return None, tuple(issues)
    selection = PlanSelection(
        explicit_stages=tuple(selected),
        include_dependencies=False,
        selection_mode="explicit",
    )
    plan_result = planner(config_result.config, selection)
    issues.extend(plan_result.issues)
    if plan_result.plan is None or has_errors(plan_result.issues):
        return None, tuple(issues)
    return plan_result.plan, tuple(issues)


class _EventBridge:
    def __init__(
        self,
        session_id: int,
        post_event: Callable[[str, object], None],
    ) -> None:
        if type(session_id) is not int or session_id <= 0:
            raise ValueError("bridge session identifier must be positive")
        if not callable(post_event):
            raise TypeError("bridge post operation must be callable")
        self._session_id = session_id
        self._post_event = post_event
        self._last_posted_sequence = 0

    @property
    def last_posted_sequence(self) -> int:
        return self._last_posted_sequence

    def emit(self, event: RunEvent) -> None:
        envelope = GuiRunEventEnvelope(self._session_id, event)
        self._post_event(PIPELINE_EVENT_KEY, envelope)
        self._last_posted_sequence = event.sequence


def run_gui_plan(
    session: GuiRunSession,
    plan: ExecutionPlan,
    post_event: Callable[[str, object], None],
    *,
    environment: Optional[ExecutionEnvironment] = None,
    runner: Optional[PipelineRunner] = None,
) -> GuiRunCompletion:
    """Execute one exact immutable plan without touching GUI presentation."""

    if not isinstance(session, GuiRunSession):
        raise TypeError("GUI worker requires a GuiRunSession")
    if not isinstance(plan, ExecutionPlan):
        raise TypeError("GUI worker requires an ExecutionPlan")
    planned_names = tuple(stage.spec.name for stage in plan.stages)
    if session.stage_names != planned_names:
        return GuiRunCompletion(
            session.identifier,
            0,
            issue=gui_issue(
                "KAM-GUI-E103",
                "worker.plan",
                "GUI session stages do not match the execution plan",
            ),
        )
    bridge = _EventBridge(session.identifier, post_event)
    try:
        context = build_run_context(plan.config.workspace, bridge.emit)
        result = run_plan(
            plan,
            context,
            environment=environment,
            runner=runner,
        )
        return GuiRunCompletion(
            session.identifier,
            bridge.last_posted_sequence,
            result=result,
        )
    except Exception as error:
        return GuiRunCompletion(
            session.identifier,
            bridge.last_posted_sequence,
            issue=gui_issue(
                "KAM-GUI-E103",
                "worker",
                "pipeline worker failed ({0})".format(type(error).__name__),
            ),
        )


def gui_tool_argv(script_path: Path) -> Tuple[str, str]:
    path = Path(script_path)
    if not path.is_absolute():
        raise ValueError("GUI tool script path must be absolute")
    if (
        path.parent != Path(__file__).resolve().parent
        or path.name not in GUI_TOOL_FILENAMES
    ):
        raise ValueError("GUI tool script is outside the packaged tool set")
    return sys.executable, str(path)


def launch_gui_tool(
    argv: Sequence[str],
    *,
    process_runner: Optional[Callable[..., Any]] = None,
) -> int:
    """Run one non-pipeline GUI tool with explicit argv and no shell."""

    if type(argv) is not tuple or not argv:
        raise TypeError("GUI tool argv must be a nonempty tuple")
    if any(not isinstance(token, str) or not token for token in argv):
        raise ValueError("GUI tool argv tokens must be nonempty strings")
    if len(argv) != 2 or argv[0] != sys.executable:
        raise ValueError("GUI tool argv must use the current interpreter")
    script = Path(argv[1])
    if (
        not script.is_absolute()
        or script.parent != Path(__file__).resolve().parent
        or script.name not in GUI_TOOL_FILENAMES
    ):
        raise ValueError("GUI tool argv names an unsupported script")
    runner = process_runner or subprocess.run
    completed = runner(argv, shell=False, check=False)
    returncode = getattr(completed, "returncode", completed)
    if type(returncode) is not int:
        raise TypeError("GUI tool process result must expose an integer return code")
    return returncode


def convert_results_value(
    spec: FieldSpec,
    value: Any,
    *,
    field: str,
) -> Tuple[Any, Optional[GuiIssue]]:
    """Convert one results-widget scalar using its owning FieldSpec."""

    if not isinstance(spec, FieldSpec):
        raise TypeError("results conversion requires FieldSpec")
    try:
        if value == "" and spec.nullable and spec.value_kind != "bool":
            converted = None
        elif spec.value_kind == "bool":
            if type(value) is not bool:
                raise ValueError("expected a checkbox boolean")
            converted = value
        elif spec.value_kind == "int":
            if type(value) is int:
                converted = value
            elif isinstance(value, str) and _INTEGER.fullmatch(value):
                converted = int(value, 10)
            else:
                raise ValueError("expected a base-10 integer")
        elif spec.value_kind == "float":
            if type(value) is bool:
                raise ValueError("expected a finite number")
            if type(value) in {int, float}:
                converted = float(value)
            elif isinstance(value, str) and value:
                converted = float(value)
            else:
                raise ValueError("expected a finite number")
            if not math.isfinite(converted):
                raise ValueError("expected a finite number")
        elif spec.value_kind in {"str", "path"}:
            if not isinstance(value, str):
                raise ValueError("expected text")
            converted = None if value == "" and spec.nullable else value
        else:
            raise ValueError("unsupported schema value kind")
    except (TypeError, ValueError, OverflowError):
        return None, gui_issue(
            "KAM-GUI-E104",
            field,
            "invalid {0} value".format(spec.value_kind),
        )
    return converted, None


def results_changes_from_values(
    values: Mapping[str, Any],
    fields: Mapping[str, FieldSpec],
) -> Tuple[Mapping[str, Any], Tuple[GuiIssue, ...]]:
    """Copy exact canonical results edits without mutating the source mapping."""

    changes = {}
    issues = []
    for dotted, spec in fields.items():
        if dotted not in values:
            issues.append(gui_issue(
                "KAM-GUI-E104",
                dotted,
                "results widget value is missing",
            ))
            continue
        converted, issue = convert_results_value(
            spec,
            values[dotted],
            field=dotted,
        )
        if issue is not None:
            issues.append(issue)
        else:
            changes[dotted] = converted
    return changes, tuple(issues)


__all__ = [
    "PIPELINE_DONE_KEY",
    "PIPELINE_EVENT_KEY",
    "GUI_TOOL_FILENAMES",
    "RESULT_STAGES",
    "collect_main_gui_values",
    "convert_results_value",
    "gui_tool_argv",
    "launch_gui_tool",
    "prepare_main_gui_plan",
    "persist_main_gui_plan",
    "prepare_results_plan",
    "results_changes_from_values",
    "results_field_specs",
    "results_form_values",
    "run_gui_plan",
]
