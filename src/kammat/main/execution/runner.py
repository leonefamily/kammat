"""Sequential execution of immutable plans."""

from pathlib import Path
import stat
import time
from typing import Callable, Mapping, Protocol, Tuple

from kammat.main.configuration import materialize_workspace
from kammat.main.pipeline import ExecutionPlan
from kammat.main.stages import STAGE_NAMES

from .adapters import ADAPTERS, StageAdapter, prepare_execution
from .model import (
    EventDispatcher,
    ExecutionEnvironment,
    ExecutionIssue,
    OutputExpectation,
    OutputObservation,
    RunContext,
    RunResult,
    StageResult,
    execution_issue,
    utc_now,
)
from .process import ProcessPort


class OutputInspector(Protocol):
    def inspect(
        self,
        expectations: Tuple[OutputExpectation, ...],
    ) -> Tuple[OutputObservation, ...]:
        ...


class MetadataOutputInspector:
    """Classify exact declared paths using lstat only."""

    def inspect(
        self,
        expectations: Tuple[OutputExpectation, ...],
    ) -> Tuple[OutputObservation, ...]:
        observations = []
        for expectation in expectations:
            try:
                mode = expectation.path.lstat().st_mode
            except FileNotFoundError:
                state = "missing"
            except OSError as error:
                state = "unreadable"
            else:
                if stat.S_ISLNK(mode):
                    state = "symlink"
                elif stat.S_ISREG(mode):
                    state = "file"
                elif stat.S_ISDIR(mode):
                    state = "directory"
                else:
                    state = "other"
            observations.append(OutputObservation(
                expectation.identifier,
                expectation.path,
                expectation.kind,
                state,
            ))
        return tuple(observations)


def _output_issues(
    observations: Tuple[OutputObservation, ...],
) -> Tuple[ExecutionIssue, ...]:
    issues = []
    for observation in observations:
        if observation.satisfied:
            continue
        if observation.state == "missing":
            code = "KAM-EXEC-E300"
            message = "declared output is missing: {0}".format(observation.path)
        elif observation.state == "unreadable":
            code = "KAM-EXEC-E302"
            message = "declared output cannot be inspected: {0}".format(
                observation.path
            )
        else:
            code = "KAM-EXEC-E301"
            message = "declared output must be a {0}: {1}".format(
                observation.expected_kind, observation.path
            )
        issues.append(execution_issue(
            code, observation.identifier, message
        ))
    return tuple(issues)


def materialize_log_directory(context: RunContext) -> Path:
    """Create only the confined executor metadata directory."""

    workspace = context.workspace
    root = workspace.resolve(strict=True)
    if root != workspace.resolve():
        raise RuntimeError("workspace resolution changed during log preparation")
    current = workspace
    for name in (".kammat", "logs"):
        current = current / name
        if current.is_symlink():
            raise RuntimeError("executor metadata path may not be a symlink: {0}".format(current))
        if current.exists() and not current.is_dir():
            raise RuntimeError("executor metadata path is not a directory: {0}".format(current))
        nearest = current
        while not nearest.exists():
            nearest = nearest.parent
        try:
            nearest.resolve(strict=True).relative_to(root)
        except ValueError as error:
            raise RuntimeError(
                "executor metadata path escapes workspace: {0}".format(current)
            ) from error
        current.mkdir(exist_ok=True)
        try:
            current.resolve(strict=True).relative_to(root)
        except ValueError as error:
            raise RuntimeError(
                "executor metadata path escapes workspace: {0}".format(current)
            ) from error
    if current != context.log_directory:
        raise RuntimeError("materialized log directory does not match context")
    return current


class PipelineRunner:
    """Prepare once, then execute an immutable plan sequentially."""

    def __init__(
        self,
        process_port: ProcessPort,
        output_inspector: OutputInspector,
        environment: ExecutionEnvironment,
        adapters: Mapping[str, StageAdapter] = ADAPTERS,
        utc_clock: Callable[[], object] = utc_now,
        monotonic_clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._process_port = process_port
        self._output_inspector = output_inspector
        self._environment = environment
        self._adapters = adapters
        self._utc_clock = utc_clock
        self._monotonic_clock = monotonic_clock

    @staticmethod
    def _failed_run(
        started: object,
        finished: object,
        code: int,
        stages: Tuple[StageResult, ...],
        issues: Tuple[ExecutionIssue, ...],
    ) -> RunResult:
        return RunResult("failed", code, started, finished, stages, issues)

    def run(self, plan: ExecutionPlan, context: RunContext) -> RunResult:
        if context.workspace != plan.config.workspace:
            raise ValueError("run context workspace must equal plan workspace")
        started = self._utc_clock()
        dispatcher = EventDispatcher(context.emit, self._utc_clock)
        dispatcher.emit("run-started")
        if dispatcher.failure is not None:
            return self._failed_run(
                started,
                self._utc_clock(),
                5,
                (),
                (dispatcher.failure,),
            )

        preparation = prepare_execution(
            plan, context, self._environment, self._adapters
        )
        if preparation.issues:
            code = 4 if all(
                issue.code == "KAM-EXEC-E102" for issue in preparation.issues
            ) else 5
            emitted = set()
            for issue in preparation.issues:
                stage = issue.field.split(":", 1)[0]
                if stage in STAGE_NAMES and stage not in emitted:
                    dispatcher.emit(
                        "preflight-failed",
                        stage=stage,
                        message=issue.message,
                        exit_code=code,
                    )
                    emitted.add(stage)
            dispatcher.emit("run-failed", exit_code=code)
            issues = list(preparation.issues)
            if dispatcher.failure is not None and dispatcher.failure not in issues:
                issues.append(dispatcher.failure)
                code = 5
            return self._failed_run(
                started, self._utc_clock(), code, (), tuple(issues)
            )

        if not preparation.stages:
            dispatcher.emit("run-succeeded", exit_code=0)
            if dispatcher.failure is not None:
                return self._failed_run(
                    started,
                    self._utc_clock(),
                    5,
                    (),
                    (dispatcher.failure,),
                )
            return RunResult("succeeded", 0, started, self._utc_clock(), (), ())

        try:
            materialize_workspace(plan.config)
            materialize_log_directory(context)
        except (OSError, RuntimeError, ValueError) as error:
            issue = execution_issue(
                "KAM-EXEC-E200",
                "run:workspace",
                "workspace or log directory cannot be prepared ({0})".format(
                    type(error).__name__
                ),
            )
            dispatcher.emit("run-failed", exit_code=5)
            issues = [issue]
            if dispatcher.failure is not None:
                issues.append(dispatcher.failure)
            return self._failed_run(
                started, self._utc_clock(), 5, (), tuple(issues)
            )

        results = []
        try:
            for prepared in preparation.stages:
                name = prepared.invocation.stage
                stage_started = self._utc_clock()
                dispatcher.emit(
                    "stage-started",
                    stage=name,
                    log_path=prepared.invocation.log_path,
                )
                if dispatcher.failure is not None:
                    stage_result = StageResult(
                        name,
                        "failed",
                        5,
                        None,
                        stage_started,
                        self._utc_clock(),
                        (),
                        prepared.invocation.log_path,
                        (dispatcher.failure,),
                        dispatcher.failure.message,
                    )
                    results.append(stage_result)
                    return self._failed_run(
                        started,
                        self._utc_clock(),
                        5,
                        tuple(results),
                        (),
                    )

                outcome = self._process_port.run(
                    prepared.invocation, context, dispatcher
                )
                if outcome.status == "cancelled":
                    if outcome.forced_termination:
                        dispatcher.emit(
                            "termination-escalated",
                            stage=name,
                            message="process-tree termination escalated to kill",
                            log_path=outcome.log_path,
                        )
                    stage_result = StageResult(
                        name,
                        "cancelled",
                        130,
                        outcome.child_exit_code,
                        stage_started,
                        outcome.finished_at,
                        (),
                        outcome.log_path,
                        outcome.issues,
                        "run interrupted by user",
                    )
                    results.append(stage_result)
                    dispatcher.emit(
                        "stage-cancelled",
                        stage=name,
                        message=stage_result.message,
                        exit_code=130,
                        child_exit_code=outcome.child_exit_code,
                        log_path=outcome.log_path,
                    )
                    dispatcher.emit("run-cancelled", exit_code=130)
                    return RunResult(
                        "cancelled",
                        130,
                        started,
                        self._utc_clock(),
                        tuple(results),
                        (),
                    )

                if outcome.status == "failed":
                    stage_result = StageResult(
                        name,
                        "failed",
                        5,
                        outcome.child_exit_code,
                        stage_started,
                        outcome.finished_at,
                        (),
                        outcome.log_path,
                        outcome.issues,
                        outcome.issues[0].message if outcome.issues else "stage execution failed",
                    )
                    results.append(stage_result)
                    dispatcher.emit(
                        "stage-failed",
                        stage=name,
                        message=stage_result.message,
                        exit_code=5,
                        child_exit_code=outcome.child_exit_code,
                        log_path=outcome.log_path,
                    )
                    dispatcher.emit("run-failed", exit_code=5)
                    return self._failed_run(
                        started,
                        self._utc_clock(),
                        5,
                        tuple(results),
                        (),
                    )

                observations = self._output_inspector.inspect(prepared.outputs)
                output_issues = _output_issues(observations)
                if output_issues:
                    stage_result = StageResult(
                        name,
                        "failed",
                        6,
                        outcome.child_exit_code,
                        stage_started,
                        self._utc_clock(),
                        observations,
                        outcome.log_path,
                        output_issues,
                        output_issues[0].message,
                    )
                    results.append(stage_result)
                    dispatcher.emit(
                        "stage-failed",
                        stage=name,
                        message=stage_result.message,
                        exit_code=6,
                        child_exit_code=outcome.child_exit_code,
                        log_path=outcome.log_path,
                    )
                    dispatcher.emit("run-failed", exit_code=6)
                    return self._failed_run(
                        started,
                        self._utc_clock(),
                        6,
                        tuple(results),
                        (),
                    )

                succeeded = StageResult(
                    name,
                    "succeeded",
                    0,
                    outcome.child_exit_code,
                    stage_started,
                    self._utc_clock(),
                    observations,
                    outcome.log_path,
                    outcome.issues,
                    None,
                )
                dispatcher.emit(
                    "stage-succeeded",
                    stage=name,
                    exit_code=0,
                    child_exit_code=outcome.child_exit_code,
                    log_path=outcome.log_path,
                )
                if dispatcher.failure is not None:
                    failed = StageResult(
                        name,
                        "failed",
                        5,
                        outcome.child_exit_code,
                        stage_started,
                        self._utc_clock(),
                        observations,
                        outcome.log_path,
                        (dispatcher.failure,),
                        dispatcher.failure.message,
                    )
                    results.append(failed)
                    return self._failed_run(
                        started,
                        self._utc_clock(),
                        5,
                        tuple(results),
                        (),
                    )
                results.append(succeeded)
        except KeyboardInterrupt:
            issue = execution_issue(
                "KAM-EXEC-W101",
                "run:between-stages",
                "run interrupted by user",
            )
            dispatcher.emit("run-cancelled", exit_code=130)
            return RunResult(
                "cancelled",
                130,
                started,
                self._utc_clock(),
                tuple(results),
                (issue,),
            )

        dispatcher.emit("run-succeeded", exit_code=0)
        if dispatcher.failure is not None:
            return self._failed_run(
                started,
                self._utc_clock(),
                5,
                tuple(results),
                (dispatcher.failure,),
            )
        return RunResult(
            "succeeded",
            0,
            started,
            self._utc_clock(),
            tuple(results),
            (),
        )


__all__ = [
    "MetadataOutputInspector",
    "OutputInspector",
    "PipelineRunner",
    "materialize_log_directory",
]
