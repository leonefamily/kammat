"""Immutable presentation-neutral execution models."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable, Mapping, Optional, Tuple


STAGE_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
RUN_STATUSES = STAGE_STATUSES
PROCESS_STATUSES = STAGE_STATUSES
OUTPUT_KINDS = frozenset({"file", "directory"})
OUTPUT_STATES = frozenset({
    "file", "directory", "missing", "symlink", "other", "unreadable",
})
AVAILABILITY_STATES = frozenset({
    "available", "unavailable", "configuration-required",
})
EVENT_KINDS = frozenset({
    "run-started",
    "preflight-failed",
    "stage-started",
    "stage-output",
    "stage-succeeded",
    "stage-failed",
    "stage-cancelled",
    "termination-escalated",
    "run-succeeded",
    "run-failed",
    "run-cancelled",
})
APPLICATION_EXIT_CODES = frozenset({0, 2, 3, 4, 5, 6, 130})
EXECUTION_ISSUE_CATALOG = MappingProxyType({
    "KAM-EXEC-E100": ("error", "adapter-registry"),
    "KAM-EXEC-E101": ("error", "invocation-preparation"),
    "KAM-EXEC-E102": ("error", "external-dependency"),
    "KAM-EXEC-E200": ("error", "workspace-log"),
    "KAM-EXEC-E201": ("error", "process-start"),
    "KAM-EXEC-E202": ("error", "process-stream"),
    "KAM-EXEC-E203": ("error", "child-exit"),
    "KAM-EXEC-E204": ("error", "event-callback"),
    "KAM-EXEC-E300": ("error", "output-missing"),
    "KAM-EXEC-E301": ("error", "output-kind"),
    "KAM-EXEC-E302": ("error", "output-inspection"),
    "KAM-EXEC-W100": ("warning", "forced-termination"),
    "KAM-EXEC-W101": ("warning", "interrupted"),
})


def utc_now() -> datetime:
    """Return a timezone-aware UTC timestamp."""

    return datetime.now(timezone.utc)


def _absolute(path: Path, label: str) -> Path:
    normalized = Path(path)
    if not normalized.is_absolute():
        raise ValueError("{0} must be absolute".format(label))
    if "\x00" in str(normalized):
        raise ValueError("{0} may not contain NUL".format(label))
    return Path(os.path.normpath(str(normalized)))


def _utc(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("{0} must be timezone-aware".format(label))
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("{0} must use UTC".format(label))
    return value


def _frozen_mapping(values: Mapping[str, str], label: str) -> Mapping[str, str]:
    copied = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or "\x00" in key:
            raise ValueError("{0} keys must be non-empty strings without NUL".format(label))
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("{0} values must be strings without NUL".format(label))
        copied[key] = value
    return MappingProxyType(copied)


def _frozen_path_mapping(
    values: Mapping[str, Tuple[str, ...]],
) -> Mapping[str, Tuple[str, ...]]:
    copied = {}
    for key, parts in values.items():
        if not isinstance(key, str) or not key or "\x00" in key:
            raise ValueError("environment path keys must be non-empty strings without NUL")
        normalized = tuple(parts)
        if any(not isinstance(part, str) or not part or "\x00" in part for part in normalized):
            raise ValueError("environment path parts must be non-empty strings without NUL")
        copied[key] = normalized
    return MappingProxyType(copied)


@dataclass(frozen=True)
class ExecutionIssue:
    code: str
    level: str
    field: str
    message: str
    hint: Optional[str] = None

    def __post_init__(self) -> None:
        policy = EXECUTION_ISSUE_CATALOG.get(self.code)
        if policy is None:
            raise ValueError("unknown execution issue code: {0}".format(self.code))
        if self.level != policy[0]:
            raise ValueError(
                "execution issue level for {0} must be {1}".format(
                    self.code, policy[0]
                )
            )
        if not isinstance(self.field, str) or not self.field or "\x00" in self.field:
            raise ValueError("execution issue field must be non-empty")
        if not isinstance(self.message, str) or not self.message or "\x00" in self.message:
            raise ValueError("execution issue message must be non-empty")
        if self.hint is not None and (
            not isinstance(self.hint, str) or not self.hint
        ):
            raise ValueError("execution issue hint must be non-empty or None")


def execution_issue(
    code: str,
    field: str,
    message: str,
    hint: Optional[str] = None,
) -> ExecutionIssue:
    """Construct an issue using the catalog-owned severity."""

    policy = EXECUTION_ISSUE_CATALOG.get(code)
    if policy is None:
        raise ValueError("unknown execution issue code: {0}".format(code))
    return ExecutionIssue(code, policy[0], field, message, hint)


@dataclass(frozen=True)
class RunContext:
    workspace: Path
    log_directory: Path
    emit: Callable[["RunEvent"], None]
    termination_grace_seconds: float = 5.0

    def __post_init__(self) -> None:
        workspace = _absolute(self.workspace, "workspace")
        log_directory = _absolute(self.log_directory, "log directory")
        if log_directory != workspace / ".kammat" / "logs":
            raise ValueError("log directory must be workspace/.kammat/logs")
        if not callable(self.emit):
            raise TypeError("run event sink must be callable")
        grace = self.termination_grace_seconds
        if isinstance(grace, bool) or not isinstance(grace, (int, float)):
            raise TypeError("termination grace must be numeric")
        if not 0.0 < float(grace) <= 60.0:
            raise ValueError("termination grace must be in (0, 60]")
        object.__setattr__(self, "workspace", workspace)
        object.__setattr__(self, "log_directory", log_directory)
        object.__setattr__(self, "termination_grace_seconds", float(grace))


@dataclass(frozen=True)
class ExecutionEnvironment:
    platform: str
    python_executable: Path
    java_executable: Optional[Path]
    package_root: Path

    def __post_init__(self) -> None:
        if self.platform not in {"posix", "windows"}:
            raise ValueError("execution platform must be posix or windows")
        python_executable = _absolute(self.python_executable, "Python executable")
        package_root = _absolute(self.package_root, "package root")
        java_executable = self.java_executable
        if java_executable is not None:
            java_executable = _absolute(java_executable, "Java executable")
        object.__setattr__(self, "python_executable", python_executable)
        object.__setattr__(self, "java_executable", java_executable)
        object.__setattr__(self, "package_root", package_root)


@dataclass(frozen=True)
class StageAvailability:
    """Immutable presentation-neutral runtime discovery for one stage."""

    stage: str
    description: str
    dependencies: Tuple[str, ...]
    execution_family: str
    requirement: str
    status: str
    detail: Optional[str] = None

    def __post_init__(self) -> None:
        for label, value in (
            ("stage", self.stage),
            ("description", self.description),
            ("execution family", self.execution_family),
            ("requirement", self.requirement),
        ):
            if not isinstance(value, str) or not value or "\x00" in value:
                raise ValueError("availability {0} must be non-empty".format(label))
        dependencies = tuple(self.dependencies)
        if any(not isinstance(item, str) or not item for item in dependencies):
            raise ValueError("availability dependencies must be names")
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("availability dependencies must be unique")
        if self.status not in AVAILABILITY_STATES:
            raise ValueError("unknown availability state")
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail or "\x00" in self.detail
        ):
            raise ValueError("availability detail must be non-empty or None")
        object.__setattr__(self, "dependencies", dependencies)


@dataclass(frozen=True)
class OutputExpectation:
    identifier: str
    path: Path
    kind: str

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier or "\x00" in self.identifier:
            raise ValueError("output expectation identifier must be non-empty")
        if self.kind not in OUTPUT_KINDS:
            raise ValueError("unknown output expectation kind")
        object.__setattr__(self, "path", _absolute(self.path, "output path"))


@dataclass(frozen=True)
class OutputObservation:
    identifier: str
    path: Path
    expected_kind: str
    state: str

    def __post_init__(self) -> None:
        if not isinstance(self.identifier, str) or not self.identifier or "\x00" in self.identifier:
            raise ValueError("output observation identifier must be non-empty")
        if self.expected_kind not in OUTPUT_KINDS:
            raise ValueError("unknown expected output kind")
        if self.state not in OUTPUT_STATES:
            raise ValueError("unknown output observation state")
        object.__setattr__(self, "path", _absolute(self.path, "output path"))

    @property
    def satisfied(self) -> bool:
        return self.state == self.expected_kind


@dataclass(frozen=True)
class ProcessInvocation:
    stage: str
    argv: Tuple[str, ...]
    cwd: Path
    environment_overrides: Mapping[str, str]
    environment_path_prepend: Mapping[str, Tuple[str, ...]]
    log_path: Path

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("process stage must be non-empty")
        argv = tuple(self.argv)
        if not argv:
            raise ValueError("process argv must not be empty")
        if any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
            raise ValueError("process argv must contain non-empty strings without NUL")
        cwd = _absolute(self.cwd, "process cwd")
        log_path = _absolute(self.log_path, "process log path")
        if log_path.name != self.stage + ".log":
            raise ValueError("process log filename must match stage")
        if log_path.parent != cwd / ".kammat" / "logs":
            raise ValueError("process log path must be confined to cwd/.kammat/logs")
        object.__setattr__(self, "argv", argv)
        object.__setattr__(self, "cwd", cwd)
        object.__setattr__(self, "log_path", log_path)
        object.__setattr__(
            self,
            "environment_overrides",
            _frozen_mapping(self.environment_overrides, "environment"),
        )
        object.__setattr__(
            self,
            "environment_path_prepend",
            _frozen_path_mapping(self.environment_path_prepend),
        )


@dataclass(frozen=True)
class PreparedStage:
    planned_stage: Any
    invocation: ProcessInvocation
    outputs: Tuple[OutputExpectation, ...]

    def __post_init__(self) -> None:
        spec = getattr(self.planned_stage, "spec", None)
        name = getattr(spec, "name", None)
        if not isinstance(name, str) or name != self.invocation.stage:
            raise ValueError("prepared stage identity must match invocation")
        outputs = tuple(self.outputs)
        identifiers = tuple(output.identifier for output in outputs)
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("prepared outputs must have unique identifiers")
        planned_outputs = tuple(
            getattr(output, "identifier", None)
            for output in getattr(self.planned_stage, "outputs", ())
        )
        positions = tuple(
            planned_outputs.index(identifier)
            if identifier in planned_outputs else -1
            for identifier in identifiers
        )
        if -1 in positions or positions != tuple(sorted(positions)):
            raise ValueError("prepared outputs must be an ordered planned subset")
        object.__setattr__(self, "outputs", outputs)


@dataclass(frozen=True)
class ProcessOutcome:
    stage: str
    status: str
    child_exit_code: Optional[int]
    started_at: datetime
    finished_at: datetime
    log_path: Path
    line_count: int
    forced_termination: bool = False
    issues: Tuple[ExecutionIssue, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("process outcome stage must be non-empty")
        if self.status not in PROCESS_STATUSES:
            raise ValueError("unknown process outcome status")
        if self.child_exit_code is not None and type(self.child_exit_code) is not int:
            raise TypeError("child exit code must be an integer or None")
        started = _utc(self.started_at, "process start")
        finished = _utc(self.finished_at, "process finish")
        if finished < started:
            raise ValueError("process finish precedes start")
        if type(self.line_count) is not int or self.line_count < 0:
            raise ValueError("process line count must be nonnegative")
        issues = tuple(self.issues)
        if self.status == "succeeded" and self.child_exit_code != 0:
            raise ValueError("successful process must have child exit code zero")
        if self.status == "succeeded" and any(issue.level == "error" for issue in issues):
            raise ValueError("successful process may not contain an error issue")
        if self.status == "failed" and not any(issue.level == "error" for issue in issues):
            raise ValueError("failed process requires an error issue")
        if self.status == "cancelled" and not any(
            issue.code == "KAM-EXEC-W101" for issue in issues
        ):
            raise ValueError("cancelled process requires an interruption warning")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        object.__setattr__(self, "log_path", _absolute(self.log_path, "process log path"))
        object.__setattr__(self, "issues", issues)


@dataclass(frozen=True)
class StageResult:
    stage: str
    status: str
    exit_code: int
    child_exit_code: Optional[int]
    started_at: datetime
    finished_at: datetime
    verified_outputs: Tuple[OutputObservation, ...]
    log_path: Optional[Path]
    issues: Tuple[ExecutionIssue, ...] = ()
    message: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("stage result stage must be non-empty")
        if self.status not in STAGE_STATUSES:
            raise ValueError("unknown stage result status")
        if self.exit_code not in {0, 4, 5, 6, 130}:
            raise ValueError("invalid stage application exit code")
        started = _utc(self.started_at, "stage start")
        finished = _utc(self.finished_at, "stage finish")
        if finished < started:
            raise ValueError("stage finish precedes start")
        outputs = tuple(self.verified_outputs)
        issues = tuple(self.issues)
        if self.status == "succeeded":
            if (
                self.exit_code != 0
                or self.child_exit_code != 0
                or any(not item.satisfied for item in outputs)
            ):
                raise ValueError(
                    "successful stage must have zero codes and satisfied outputs"
                )
            if any(issue.level == "error" for issue in issues):
                raise ValueError("successful stage may not contain error issues")
        elif self.status == "cancelled":
            if self.exit_code != 130:
                raise ValueError("cancelled stage must have code 130")
            if not any(issue.code == "KAM-EXEC-W101" for issue in issues):
                raise ValueError("cancelled stage requires an interruption warning")
        elif self.exit_code not in {4, 5, 6}:
            raise ValueError("failed stage must have code 4, 5, or 6")
        elif not any(issue.level == "error" for issue in issues):
            raise ValueError("failed stage requires an error issue")
        if self.status == "failed" and self.exit_code == 6:
            if self.child_exit_code != 0 or not any(not item.satisfied for item in outputs):
                raise ValueError(
                    "output failure requires child code zero and an unsatisfied output"
                )
        log_path = None if self.log_path is None else _absolute(self.log_path, "stage log path")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        object.__setattr__(self, "verified_outputs", outputs)
        object.__setattr__(self, "log_path", log_path)
        object.__setattr__(self, "issues", issues)


@dataclass(frozen=True)
class RunResult:
    status: str
    exit_code: int
    started_at: datetime
    finished_at: datetime
    stages: Tuple[StageResult, ...]
    issues: Tuple[ExecutionIssue, ...] = ()

    def __post_init__(self) -> None:
        if self.status not in RUN_STATUSES:
            raise ValueError("unknown run result status")
        if self.exit_code not in {0, 4, 5, 6, 130}:
            raise ValueError("invalid run application exit code")
        started = _utc(self.started_at, "run start")
        finished = _utc(self.finished_at, "run finish")
        if finished < started:
            raise ValueError("run finish precedes start")
        stages = tuple(self.stages)
        issues = tuple(self.issues)
        names = tuple(stage.stage for stage in stages)
        if len(names) != len(set(names)):
            raise ValueError("run stages must be unique")
        if self.status == "succeeded":
            if self.exit_code != 0 or any(stage.status != "succeeded" for stage in stages):
                raise ValueError("successful run requires successful stages and code zero")
            if any(issue.level == "error" for issue in issues):
                raise ValueError("successful run may not contain error issues")
        elif self.status == "cancelled":
            if self.exit_code != 130:
                raise ValueError("cancelled run must have code 130")
            if not any(
                issue.code == "KAM-EXEC-W101"
                for issue in issues
            ) and not any(
                issue.code == "KAM-EXEC-W101"
                for stage in stages for issue in stage.issues
            ):
                raise ValueError("cancelled run requires an interruption warning")
        elif self.exit_code not in {4, 5, 6}:
            raise ValueError("failed run must have code 4, 5, or 6")
        elif not any(issue.level == "error" for issue in issues) and not any(
            issue.level == "error" for stage in stages for issue in stage.issues
        ):
            raise ValueError("failed run requires an error issue")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "issues", issues)


@dataclass(frozen=True)
class RunEvent:
    sequence: int
    kind: str
    timestamp: datetime
    stage: Optional[str] = None
    message: Optional[str] = None
    line: Optional[str] = None
    exit_code: Optional[int] = None
    child_exit_code: Optional[int] = None
    log_path: Optional[Path] = None

    def __post_init__(self) -> None:
        if type(self.sequence) is not int or self.sequence <= 0:
            raise ValueError("event sequence must be positive")
        if self.kind not in EVENT_KINDS:
            raise ValueError("unknown event kind")
        object.__setattr__(self, "timestamp", _utc(self.timestamp, "event timestamp"))
        if self.stage is not None and (not isinstance(self.stage, str) or not self.stage):
            raise ValueError("event stage must be non-empty or None")
        if self.message is not None and not isinstance(self.message, str):
            raise TypeError("event message must be a string or None")
        if self.line is not None and not isinstance(self.line, str):
            raise TypeError("event line must be a string or None")
        if self.exit_code is not None and self.exit_code not in APPLICATION_EXIT_CODES:
            raise ValueError("event has an invalid application exit code")
        if self.child_exit_code is not None and type(self.child_exit_code) is not int:
            raise TypeError("event child exit code must be an integer or None")
        if self.log_path is not None:
            object.__setattr__(self, "log_path", _absolute(self.log_path, "event log path"))
            if self.stage is not None and self.log_path.name != self.stage + ".log":
                raise ValueError("event log filename must match stage")

        run_kinds = {"run-started", "run-succeeded", "run-failed", "run-cancelled"}
        if self.kind in run_kinds and self.stage is not None:
            raise ValueError("run event may not name a stage")
        if self.kind == "run-started" and any(item is not None for item in (
            self.line, self.exit_code, self.child_exit_code, self.log_path,
        )):
            raise ValueError("run-started has forbidden payload")
        if self.kind == "stage-output":
            if self.stage is None or self.line is None or self.log_path is None:
                raise ValueError("stage-output requires stage, line, and log path")
            if self.exit_code is not None or self.child_exit_code is not None:
                raise ValueError("stage-output may not contain exit codes")
        elif self.line is not None:
            raise ValueError("only stage-output may contain a line")
        if self.kind in {"stage-started", "stage-succeeded", "stage-failed",
                         "stage-cancelled", "termination-escalated",
                         "preflight-failed"} and self.stage is None:
            raise ValueError("stage event requires a stage")
        if self.kind == "preflight-failed":
            if not self.message or self.log_path is not None or self.child_exit_code is not None:
                raise ValueError("preflight-failed requires a message and no child/log payload")
        if self.kind == "stage-started" and any(
            item is not None
            for item in (self.message, self.exit_code, self.child_exit_code)
        ):
            raise ValueError("stage-started has forbidden payload")
        if self.kind == "termination-escalated":
            if not self.message or self.log_path is None or self.exit_code is not None:
                raise ValueError("termination-escalated requires message/log and no exit code")
        if self.kind in run_kinds and self.child_exit_code is not None:
            raise ValueError("run event may not contain a child exit code")
        if self.kind in run_kinds and self.log_path is not None:
            raise ValueError("run event may not contain a stage log path")
        terminal_codes = {
            "stage-succeeded": 0,
            "run-succeeded": 0,
            "stage-cancelled": 130,
            "run-cancelled": 130,
        }
        expected = terminal_codes.get(self.kind)
        if expected is not None and self.exit_code != expected:
            raise ValueError("terminal event has the wrong exit code")
        if self.kind in {"stage-failed", "run-failed", "preflight-failed"} and (
            self.exit_code not in {4, 5, 6}
        ):
            raise ValueError("failed event requires code 4, 5, or 6")
        if self.kind == "stage-started" and self.log_path is None:
            raise ValueError("stage-started requires a log path")
        if self.kind == "stage-succeeded":
            if self.log_path is None or self.child_exit_code not in {None, 0}:
                raise ValueError("stage-succeeded requires a log and zero child code")
        if self.kind == "termination-escalated" and self.child_exit_code is not None:
            raise ValueError("termination-escalated may not contain a child exit code")


class EventDispatcher:
    """Allocate event sequence locally and contain callback failures."""

    def __init__(
        self,
        sink: Callable[[RunEvent], None],
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        if not callable(sink) or not callable(clock):
            raise TypeError("event dispatcher sink and clock must be callable")
        self._sink = sink
        self._clock = clock
        self._sequence = 0
        self._failure: Optional[ExecutionIssue] = None

    @property
    def failure(self) -> Optional[ExecutionIssue]:
        return self._failure

    @property
    def sequence(self) -> int:
        return self._sequence

    def emit(self, kind: str, **payload: Any) -> bool:
        self._sequence += 1
        event = RunEvent(
            sequence=self._sequence,
            kind=kind,
            timestamp=self._clock(),
            **payload
        )
        if self._failure is not None:
            return False
        try:
            self._sink(event)
            return True
        except Exception as error:
            self._failure = execution_issue(
                "KAM-EXEC-E204",
                "run:callback",
                "event callback failed ({0})".format(type(error).__name__),
            )
            return False


@dataclass(frozen=True)
class PreparationResult:
    stages: Tuple[PreparedStage, ...]
    issues: Tuple[ExecutionIssue, ...] = ()

    def __post_init__(self) -> None:
        stages = tuple(self.stages)
        issues = tuple(self.issues)
        has_error = any(issue.level == "error" for issue in issues)
        if has_error and stages:
            raise ValueError("failed preparation may not expose partial stages")
        object.__setattr__(self, "stages", stages)
        object.__setattr__(self, "issues", issues)


__all__ = [
    "APPLICATION_EXIT_CODES",
    "AVAILABILITY_STATES",
    "EVENT_KINDS",
    "EXECUTION_ISSUE_CATALOG",
    "EventDispatcher",
    "ExecutionEnvironment",
    "ExecutionIssue",
    "OUTPUT_KINDS",
    "OUTPUT_STATES",
    "OutputExpectation",
    "OutputObservation",
    "PreparationResult",
    "PreparedStage",
    "ProcessInvocation",
    "ProcessOutcome",
    "RunContext",
    "RunEvent",
    "RunResult",
    "StageResult",
    "StageAvailability",
    "execution_issue",
    "utc_now",
]
