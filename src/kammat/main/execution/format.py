"""Primitive projections for immutable execution values."""

from datetime import datetime
from typing import Any, Dict

from .model import (
    ExecutionIssue,
    OutputObservation,
    ProcessInvocation,
    RunEvent,
    RunResult,
    StageResult,
)


def _timestamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _issue(value: ExecutionIssue) -> Dict[str, Any]:
    return {
        "code": value.code,
        "level": value.level,
        "field": value.field,
        "message": value.message,
        "hint": value.hint,
    }


def _observation(value: OutputObservation) -> Dict[str, Any]:
    return {
        "id": value.identifier,
        "path": str(value.path),
        "expected_kind": value.expected_kind,
        "state": value.state,
        "satisfied": value.satisfied,
    }


def _stage(value: StageResult) -> Dict[str, Any]:
    return {
        "stage": value.stage,
        "status": value.status,
        "exit_code": value.exit_code,
        "child_exit_code": value.child_exit_code,
        "started_at": _timestamp(value.started_at),
        "finished_at": _timestamp(value.finished_at),
        "verified_outputs": [_observation(item) for item in value.verified_outputs],
        "log_path": None if value.log_path is None else str(value.log_path),
        "issues": [_issue(item) for item in value.issues],
        "message": value.message,
    }


def execution_result_to_primitive(value: RunResult) -> Dict[str, Any]:
    """Return the versioned JSON-safe run result representation."""

    return {
        "schema_version": 1,
        "status": value.status,
        "exit_code": value.exit_code,
        "started_at": _timestamp(value.started_at),
        "finished_at": _timestamp(value.finished_at),
        "stages": [_stage(stage) for stage in value.stages],
        "issues": [_issue(item) for item in value.issues],
    }


def event_to_primitive(value: RunEvent) -> Dict[str, Any]:
    """Return a JSON-safe event representation in semantic key order."""

    return {
        "sequence": value.sequence,
        "kind": value.kind,
        "timestamp": _timestamp(value.timestamp),
        "stage": value.stage,
        "message": value.message,
        "line": value.line,
        "exit_code": value.exit_code,
        "child_exit_code": value.child_exit_code,
        "log_path": None if value.log_path is None else str(value.log_path),
    }


def invocation_to_primitive(value: ProcessInvocation) -> Dict[str, Any]:
    """Return diagnostic argv data without synthesizing a shell command."""

    return {
        "stage": value.stage,
        "argv": list(value.argv),
        "cwd": str(value.cwd),
        "environment_override_keys": list(value.environment_overrides),
        "environment_path_prepend": {
            key: list(parts)
            for key, parts in value.environment_path_prepend.items()
        },
        "log_path": str(value.log_path),
    }


__all__ = [
    "event_to_primitive",
    "execution_result_to_primitive",
    "invocation_to_primitive",
]
