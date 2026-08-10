"""Pure deterministic text and JSON projections for execution plans."""

import json
from typing import Any, Dict, Mapping

from kammat.main.pipeline import ArtifactResolution, ExecutionPlan, PlanIssue


def _artifact_to_primitive(artifact: ArtifactResolution) -> Dict[str, Any]:
    return {
        "id": artifact.identifier,
        "path": str(artifact.path),
        "kind": artifact.kind,
        "supplier": artifact.supplier,
        "producer_stage": artifact.producer_stage,
        "observed_state": artifact.observed_state,
    }


def _issue_to_primitive(issue: PlanIssue) -> Dict[str, Any]:
    return {
        "code": issue.code,
        "level": issue.level,
        "field": issue.field,
        "message": issue.message,
        "hint": issue.hint,
    }


def plan_to_primitive(plan: ExecutionPlan) -> Mapping[str, Any]:
    """Return the stable schema-version-1 JSON-compatible plan mapping."""

    return {
        "schema_version": 1,
        "configuration": str(plan.config.config_path),
        "workspace": str(plan.config.workspace),
        "selection": {
            "mode": plan.selection_mode,
            "roots": list(plan.root_stages),
            "from": plan.selection.from_stage,
            "until": plan.selection.until_stage,
            "explicit_stages": list(plan.selection.explicit_stages),
            "include_dependencies": plan.selection.include_dependencies,
        },
        "stages": [
            {
                "name": stage.spec.name,
                "description": stage.spec.description,
                "reason": stage.reason,
                "dependencies": list(stage.dependencies),
                "inputs": [
                    _artifact_to_primitive(item) for item in stage.inputs
                ],
                "outputs": [
                    _artifact_to_primitive(item) for item in stage.outputs
                ],
            }
            for stage in plan.stages
        ],
        "warnings": [
            _issue_to_primitive(issue) for issue in plan.warnings
        ],
    }


def format_plan_json(plan: ExecutionPlan) -> str:
    """Return deterministic UTF-8 JSON text with one trailing newline."""

    return json.dumps(
        plan_to_primitive(plan),
        ensure_ascii=False,
        indent=2,
    ) + "\n"


def format_plan_text(plan: ExecutionPlan) -> str:
    """Return deterministic human-readable plan text without printing."""

    selection = plan.selection_mode
    if selection == "range":
        start = plan.selection.from_stage or "network"
        finish = plan.selection.until_stage or "gis"
        selection = "range ({0}..{1})".format(start, finish)
    elif selection == "explicit":
        selection = "explicit ({0})".format(
            ", ".join(plan.root_stages) or "none"
        )
    dependency_text = (
        "dependencies included"
        if plan.selection.include_dependencies
        else "dependencies excluded"
    )
    lines = [
        "Configuration: {0}".format(plan.config.config_path),
        "Workspace:     {0}".format(plan.config.workspace),
        "Selection:     {0}, {1}".format(selection, dependency_text),
    ]
    if not plan.stages:
        lines.extend(("", "No stages selected."))
    for number, stage in enumerate(plan.stages, 1):
        lines.extend((
            "",
            "{0}. {1} [{2}]".format(number, stage.spec.name, stage.reason),
            "   {0}".format(stage.spec.description),
        ))
        if stage.dependencies:
            lines.append("   dependencies: {0}".format(
                ", ".join(stage.dependencies)
            ))
        if stage.inputs:
            lines.append("   requires:")
            for item in stage.inputs:
                if item.supplier == "selected-stage":
                    supplier = "{0}, <- {1}".format(
                        item.kind, item.producer_stage
                    )
                else:
                    supplier = "{0}, external ({1})".format(
                        item.kind, item.observed_state
                    )
                lines.append(
                    "     {0}: {1} ({2})".format(
                        item.identifier, item.path, supplier
                    )
                )
        if stage.outputs:
            lines.append("   produces:")
            for item in stage.outputs:
                lines.append("     {0}: {1} ({2})".format(
                    item.identifier, item.path, item.kind
                ))
    if plan.warnings:
        lines.extend(("", "Warnings:"))
        for issue in plan.warnings:
            lines.append("  {0} {1}: {2}".format(
                issue.code, issue.field, issue.message
            ))
    return "\n".join(lines) + "\n"


__all__ = ["format_plan_json", "format_plan_text", "plan_to_primitive"]
