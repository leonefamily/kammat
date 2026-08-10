"""Deterministic text, JSON, ANSI, event, and result presentation."""

import json
import math
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Sequence, Set

from kammat.main.plan_format import format_plan_text, plan_to_primitive

from .model import ConfigAssignment, PreparedPlanView, PresentationPolicy, scalar_to_primitive


ANSI = {
    "success": "\x1b[32m",
    "warning": "\x1b[33m",
    "error": "\x1b[31m",
    "progress": "\x1b[36m",
    "reset": "\x1b[0m",
}


def _primitive(value: Any) -> Any:
    if value is None or type(value) in {bool, int, str}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Path):
        raise TypeError("Path values must be converted before JSON presentation")
    if isinstance(value, Mapping):
        result: Dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON mapping keys must be strings")
            result[key] = _primitive(item)
        return result
    if isinstance(value, (tuple, list)):
        return [_primitive(item) for item in value]
    raise TypeError("value is not JSON-primitive data")


def format_json_document(value: Mapping[str, Any]) -> str:
    return json.dumps(
        _primitive(value),
        ensure_ascii=False,
        indent=2,
        allow_nan=False,
    ) + "\n"


def issue_to_primitive(issue: Any) -> Mapping[str, Any]:
    return {
        "code": str(getattr(issue, "code")),
        "level": str(getattr(issue, "level")),
        "field": str(getattr(issue, "field")),
        "message": str(getattr(issue, "message")),
        "hint": getattr(issue, "hint", None),
    }


def _label(text: str, semantic: str, color: bool) -> str:
    if not color:
        return text
    return ANSI[semantic] + text + ANSI["reset"]


def format_issue_text(issue: Any, color: bool = False) -> str:
    code = str(getattr(issue, "code"))
    level = str(getattr(issue, "level"))
    semantic = "warning" if level == "warning" else "error"
    lines = ["{0} {1}: {2}".format(
        _label(code, semantic, color),
        getattr(issue, "field"),
        getattr(issue, "message"),
    )]
    hint = getattr(issue, "hint", None)
    if hint:
        lines.append("  hint: {0}".format(hint))
    return "\n".join(lines) + "\n"


def format_validation_summary(config: Any, source_version: Optional[int], warnings: int) -> str:
    return (
        "Configuration valid.\n"
        "Configuration: {0}\n"
        "Workspace: {1}\n"
        "Source schema version: {2}\n"
        "Warnings: {3}\n"
    ).format(config.config_path, config.workspace, source_version, warnings)


def validation_document(
    configuration: Path,
    source_version: Optional[int],
    valid: bool,
    issues: Iterable[Any],
) -> Mapping[str, Any]:
    return {
        "schema_version": 1,
        "command": "config validate",
        "configuration": str(configuration),
        "source_version": source_version,
        "valid": valid,
        "issues": [issue_to_primitive(issue) for issue in issues],
    }


def availability_to_primitive(value: Any) -> Mapping[str, Any]:
    return {
        "name": value.stage,
        "description": value.description,
        "dependencies": list(value.dependencies),
        "execution_family": value.execution_family,
        "requirement": value.requirement,
        "status": value.status,
        "detail": value.detail,
    }


def stage_list_document(
    configuration: Optional[Path],
    stages: Sequence[Any],
    issues: Iterable[Any],
) -> Mapping[str, Any]:
    return {
        "schema_version": 1,
        "command": "stage list",
        "configuration": None if configuration is None else str(configuration),
        "stages": [availability_to_primitive(item) for item in stages],
        "issues": [issue_to_primitive(issue) for issue in issues],
    }


def format_stage_list_text(stages: Sequence[Any], verbosity: int = 0) -> str:
    lines = [
        "NAME        DEPENDENCIES         RUNTIME                 AVAILABILITY",
    ]
    for item in stages:
        dependencies = ",".join(item.dependencies) if item.dependencies else "-"
        lines.append("{0:<11} {1:<20} {2:<23} {3}".format(
            item.stage,
            dependencies,
            item.execution_family,
            item.status,
        ))
        if verbosity:
            lines.append("  {0}".format(item.description))
            lines.append("  requires: {0}".format(item.requirement))
            if item.detail:
                lines.append("  detail: {0}".format(item.detail))
    return "\n".join(lines) + "\n"


def assignment_to_primitive(value: ConfigAssignment) -> Mapping[str, Any]:
    return {
        "field": value.field,
        "raw_value": value.raw_value,
        "value": scalar_to_primitive(value.parsed_value),
    }


def prepared_stage_to_primitive(value: Any) -> Mapping[str, Any]:
    invocation = value.invocation
    return {
        "stage": invocation.stage,
        "argv": list(invocation.argv),
        "cwd": str(invocation.cwd),
        "log_path": str(invocation.log_path),
        "environment_override_keys": list(invocation.environment_overrides),
        "environment_path_prepend": {
            key: list(parts)
            for key, parts in invocation.environment_path_prepend.items()
        },
    }


def plan_document(
    command: str,
    view: Optional[PreparedPlanView],
    overrides: Sequence[ConfigAssignment],
    issues: Iterable[Any],
) -> Mapping[str, Any]:
    return {
        "schema_version": 1,
        "command": command,
        "overrides": [assignment_to_primitive(item) for item in overrides],
        "plan": None if view is None else plan_to_primitive(view.plan),
        "prepared_stages": [] if view is None else [
            prepared_stage_to_primitive(item) for item in view.stages
        ],
        "issues": [issue_to_primitive(issue) for issue in issues],
    }


def format_prepared_plan_text(view: PreparedPlanView, verbosity: int = 0) -> str:
    text = format_plan_text(view.plan)
    lines = [text.rstrip("\n")]
    if view.overrides:
        lines.extend(("", "Overrides:"))
        for item in view.overrides:
            lines.append("  {0} = {1}".format(
                item.field,
                json.dumps(scalar_to_primitive(item.parsed_value), ensure_ascii=False),
            ))
    if verbosity:
        lines.extend(("", "Prepared stages:"))
        for prepared in view.stages:
            invocation = prepared.invocation
            lines.append("  {0}: executable={1}".format(
                invocation.stage,
                invocation.argv[0],
            ))
            lines.append("    log: {0}".format(invocation.log_path))
            lines.append("    env-override-keys: {0}".format(
                json.dumps(list(invocation.environment_overrides))
            ))
            lines.append("    env-path-prepend-keys: {0}".format(
                json.dumps(list(invocation.environment_path_prepend))
            ))
            if verbosity >= 2:
                lines.append("    argv-json: {0}".format(
                    json.dumps(list(invocation.argv), ensure_ascii=False)
                ))
                lines.append("    cwd: {0}".format(invocation.cwd))
                lines.append("    env-path-prepend: {0}".format(json.dumps(
                    {
                        key: list(parts)
                        for key, parts in invocation.environment_path_prepend.items()
                    },
                    ensure_ascii=False,
                )))
    return "\n".join(lines) + "\n"


def format_run_header(version: str, plan: Any) -> str:
    names = " -> ".join(stage.spec.name for stage in plan.stages) or "(none)"
    return (
        "Kammat {0}\n"
        "Config: {1}\n"
        "Workspace: {2}\n"
        "Plan: {3}\n"
    ).format(version, plan.config.config_path, plan.config.workspace, names)


class RunPresenter:
    """Presentation-only event sink with exact-once synthesized terminal lines."""

    def __init__(
        self,
        policy: PresentationPolicy,
        plan: Any,
        stdout: Callable[[str], None],
        stderr: Callable[[str], None],
    ) -> None:
        self._policy = policy
        self._positions = {
            stage.spec.name: (index, len(plan.stages))
            for index, stage in enumerate(plan.stages, 1)
        }
        self._stdout = stdout
        self._stderr = stderr
        self._rendered_failures: Set[str] = set()

    def _position(self, stage: Optional[str]) -> str:
        index, count = self._positions.get(stage, (0, len(self._positions)))
        return "[{0}/{1}]".format(index, count)

    def emit(self, event: Any) -> None:
        kind = event.kind
        stage = event.stage
        if kind in {"run-started", "run-succeeded", "run-failed", "run-cancelled"}:
            return
        if kind == "stage-output":
            if not self._policy.quiet:
                line = event.line
                self._stdout(line if line.endswith("\n") else line + "\n")
            return
        if kind == "stage-started":
            if not self._policy.quiet:
                label = _label(self._position(stage), "progress", self._policy.color)
                self._stdout("{0} {1} running\n".format(label, stage))
            return
        if kind == "stage-succeeded":
            if not self._policy.quiet:
                label = _label(self._position(stage), "success", self._policy.color)
                self._stdout("{0} {1} succeeded\n".format(label, stage))
            return
        if kind in {"preflight-failed", "stage-failed", "stage-cancelled"}:
            word = "cancelled" if kind == "stage-cancelled" else "failed"
            message = "" if not event.message else ": " + event.message
            label = _label(self._position(stage), "error", self._policy.color)
            self._stderr("{0} {1} {2}{3}\n".format(label, stage, word, message))
            if event.log_path is not None:
                self._stderr("Log: {0}\n".format(event.log_path))
            self._rendered_failures.add(stage or "run")
            return
        if kind == "termination-escalated" and not self._policy.quiet:
            self._stderr("Warning: {0}\n".format(event.message))

    def finish(self, result: Any) -> None:
        if result.status == "succeeded":
            if not self._policy.quiet:
                label = _label("Run succeeded.", "success", self._policy.color)
                self._stdout("{0} {1} stage(s).\n".format(label, len(result.stages)))
        elif result.status == "cancelled":
            self._stderr("{0}\n".format(
                _label("Run cancelled (130).", "error", self._policy.color)
            ))
        else:
            self._stderr("{0}\n".format(_label(
                "Run failed (code {0}).".format(result.exit_code),
                "error",
                self._policy.color,
            )))
            for issue in result.issues:
                if getattr(issue, "field", "run").split(":", 1)[0] not in self._rendered_failures:
                    self._stderr(format_issue_text(issue, self._policy.color))
                    break
        if self._policy.verbosity:
            for stage in result.stages:
                self._stdout(
                    "Result {0}: status={1}, code={2}, child={3}, log={4}\n".format(
                        stage.stage,
                        stage.status,
                        stage.exit_code,
                        stage.child_exit_code,
                        stage.log_path,
                    )
                )
                if self._policy.verbosity >= 2:
                    for observation in stage.verified_outputs:
                        self._stdout("  output {0}: {1}\n".format(
                            observation.identifier,
                            observation.state,
                        ))


__all__ = [
    "ANSI",
    "RunPresenter",
    "assignment_to_primitive",
    "availability_to_primitive",
    "format_issue_text",
    "format_json_document",
    "format_prepared_plan_text",
    "format_run_header",
    "format_stage_list_text",
    "format_validation_summary",
    "issue_to_primitive",
    "plan_document",
    "prepared_stage_to_primitive",
    "stage_list_document",
    "validation_document",
]
