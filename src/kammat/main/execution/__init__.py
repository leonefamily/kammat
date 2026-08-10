"""Stable presentation-neutral execution facade."""

from pathlib import Path
from typing import Callable, Optional, Union

from kammat.main.pipeline import ExecutionPlan

from .adapters import default_execution_environment as _default_environment
from .adapters import inspect_stage_availability, prepare_execution
from .format import execution_result_to_primitive
from .model import (
    ExecutionEnvironment,
    ExecutionIssue,
    OutputExpectation,
    OutputObservation,
    PreparedStage,
    ProcessInvocation,
    ProcessOutcome,
    RunContext,
    RunEvent,
    RunResult,
    StageResult,
    StageAvailability,
)
from .process import (
    PosixProcessLifecycle as _PosixProcessLifecycle,
    SubprocessPort as _SubprocessPort,
    WindowsProcessLifecycle as _WindowsProcessLifecycle,
)
from .runner import (
    MetadataOutputInspector as _MetadataOutputInspector,
    PipelineRunner,
)


PathLike = Union[str, Path]


def build_run_context(
    workspace: PathLike,
    emit: Callable[[RunEvent], None],
    termination_grace_seconds: float = 5.0,
) -> RunContext:
    """Build the exact workspace-local execution context."""

    root = Path(workspace)
    return RunContext(
        root,
        root / ".kammat" / "logs",
        emit,
        termination_grace_seconds,
    )


def build_execution_environment() -> ExecutionEnvironment:
    """Build the exact read-only executable and package environment."""

    return _default_environment()


def _build_pipeline_runner(
    environment: Optional[ExecutionEnvironment] = None,
) -> PipelineRunner:
    """Compose production execution dependencies without mutable globals."""

    effective = environment or _default_environment()
    if effective.platform == "windows":
        lifecycle = _WindowsProcessLifecycle()
    else:
        lifecycle = _PosixProcessLifecycle()
    return PipelineRunner(
        _SubprocessPort(lifecycle),
        _MetadataOutputInspector(),
        effective,
    )


def run_plan(
    plan: ExecutionPlan,
    context: RunContext,
    *,
    environment: Optional[ExecutionEnvironment] = None,
    runner: Optional[PipelineRunner] = None,
) -> RunResult:
    """Execute an error-free immutable plan through one runner."""

    effective_runner = runner or _build_pipeline_runner(environment)
    return effective_runner.run(plan, context)


__all__ = [
    "ExecutionEnvironment",
    "ExecutionIssue",
    "OutputExpectation",
    "OutputObservation",
    "PipelineRunner",
    "PreparedStage",
    "ProcessInvocation",
    "ProcessOutcome",
    "RunContext",
    "RunEvent",
    "RunResult",
    "StageResult",
    "StageAvailability",
    "build_execution_environment",
    "build_run_context",
    "execution_result_to_primitive",
    "inspect_stage_availability",
    "prepare_execution",
    "run_plan",
]
