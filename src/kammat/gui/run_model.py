"""Immutable, toolkit-neutral models for one GUI pipeline session."""

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Optional, Tuple

from kammat.main.execution import RunEvent, RunResult
from kammat.main.planning import ExecutionPlan, STAGE_NAMES


GUI_ISSUE_CATALOG: Mapping[str, Tuple[str, str]] = MappingProxyType({
    "KAM-GUI-E100": ("warning", "active-run"),
    "KAM-GUI-E101": ("warning", "stale-envelope"),
    "KAM-GUI-E102": ("warning", "sequence"),
    "KAM-GUI-E103": ("error", "worker-completion"),
    "KAM-GUI-E104": ("error", "presentation"),
    "KAM-GUI-E105": ("error", "settings-persistence"),
})
RUN_VIEW_STATUSES = frozenset({"running", "succeeded", "failed", "cancelled"})
CONSOLE_SEVERITIES = frozenset({"info", "warning", "error", "success", "output"})
STAGE_UPDATE_STATUSES = frozenset({"running", "succeeded", "failed", "cancelled"})


@dataclass(frozen=True)
class GuiIssue:
    code: str
    level: str
    field: str
    message: str

    def __post_init__(self) -> None:
        policy = GUI_ISSUE_CATALOG.get(self.code)
        if policy is None:
            raise ValueError("unknown GUI issue code: {0}".format(self.code))
        if self.level != policy[0]:
            raise ValueError(
                "GUI issue level for {0} must be {1}".format(self.code, policy[0])
            )
        if not isinstance(self.field, str) or not self.field:
            raise ValueError("GUI issue field must be non-empty")
        if not isinstance(self.message, str) or not self.message:
            raise ValueError("GUI issue message must be non-empty")


def gui_issue(code: str, field: str, message: str) -> GuiIssue:
    policy = GUI_ISSUE_CATALOG.get(code)
    if policy is None:
        raise ValueError("unknown GUI issue code: {0}".format(code))
    return GuiIssue(code, policy[0], field, message)


@dataclass(frozen=True)
class GuiRunSession:
    identifier: int
    stage_names: Tuple[str, ...]
    hidden: bool

    def __post_init__(self) -> None:
        if type(self.identifier) is not int or self.identifier <= 0:
            raise ValueError("GUI session identifier must be positive")
        names = tuple(self.stage_names)
        if any(not isinstance(name, str) or not name for name in names):
            raise TypeError("GUI session stages must be non-empty strings")
        if any(name not in STAGE_NAMES for name in names):
            raise ValueError("GUI session stage must be canonical")
        if len(names) != len(set(names)):
            raise ValueError("GUI session stages must be unique")
        if names != tuple(name for name in STAGE_NAMES if name in names):
            raise ValueError("GUI session stages must use canonical order")
        if type(self.hidden) is not bool:
            raise TypeError("GUI session hidden flag must be an exact boolean")
        object.__setattr__(self, "stage_names", names)


@dataclass(frozen=True)
class GuiRunEventEnvelope:
    session_id: int
    event: RunEvent

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("GUI event session identifier must be positive")
        if not isinstance(self.event, RunEvent):
            raise TypeError("GUI event envelope requires a RunEvent")


@dataclass(frozen=True)
class GuiRunCompletion:
    session_id: int
    final_posted_sequence: int
    result: Optional[RunResult] = None
    issue: Optional[GuiIssue] = None

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("GUI completion session identifier must be positive")
        if (
            type(self.final_posted_sequence) is not int
            or self.final_posted_sequence < 0
        ):
            raise ValueError("GUI completion sequence must be nonnegative")
        if (self.result is None) == (self.issue is None):
            raise ValueError("GUI completion requires exactly one result or issue")
        if self.result is not None and not isinstance(self.result, RunResult):
            raise TypeError("GUI completion result must be RunResult")
        if self.issue is not None and not isinstance(self.issue, GuiIssue):
            raise TypeError("GUI completion issue must be GuiIssue")


@dataclass(frozen=True)
class GuiConsoleRecord:
    severity: str
    text: str

    def __post_init__(self) -> None:
        if self.severity not in CONSOLE_SEVERITIES:
            raise ValueError("unknown GUI console severity")
        if not isinstance(self.text, str):
            raise TypeError("GUI console text must be a string")


@dataclass(frozen=True)
class GuiStageUpdate:
    stage: str
    status: str
    progress: Optional[int] = None
    timestamp: Optional[datetime] = None
    exit_code: Optional[int] = None
    child_exit_code: Optional[int] = None
    message: Optional[str] = None
    log_path: Optional[Path] = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            raise ValueError("GUI stage update stage must be non-empty")
        if self.stage not in STAGE_NAMES:
            raise ValueError("GUI stage update stage must be canonical")
        if self.status not in STAGE_UPDATE_STATUSES:
            raise ValueError("unknown GUI stage update status")
        if self.progress is not None and (
            type(self.progress) is not int or not 0 <= self.progress <= 100
        ):
            raise ValueError("GUI stage progress must be an integer from 0 to 100")
        if self.exit_code is not None and self.exit_code not in {0, 4, 5, 6, 130}:
            raise ValueError("invalid GUI stage application code")
        if self.child_exit_code is not None and type(self.child_exit_code) is not int:
            raise TypeError("GUI stage child code must be an integer or None")
        if self.message is not None and not isinstance(self.message, str):
            raise TypeError("GUI stage message must be a string or None")
        if self.log_path is not None:
            path = Path(self.log_path)
            if not path.is_absolute():
                raise ValueError("GUI stage log path must be absolute")
            object.__setattr__(self, "log_path", path)


@dataclass(frozen=True)
class GuiRunViewState:
    session_id: int
    status: str
    stage_names: Tuple[str, ...]
    current_stage: Optional[str]
    terminal_event_kind: Optional[str]
    completed_stages: Tuple[str, ...]
    failed_stage: Optional[str]
    last_sequence: int
    close_requested: bool

    def __post_init__(self) -> None:
        if type(self.session_id) is not int or self.session_id <= 0:
            raise ValueError("GUI view session identifier must be positive")
        if self.status not in RUN_VIEW_STATUSES:
            raise ValueError("unknown GUI run status")
        names = tuple(self.stage_names)
        completed = tuple(self.completed_stages)
        if any(not isinstance(name, str) or not name for name in names):
            raise TypeError("GUI view stages must be non-empty strings")
        if any(name not in STAGE_NAMES for name in names):
            raise ValueError("GUI view stage must be canonical")
        if len(names) != len(set(names)):
            raise ValueError("GUI view stages must be unique")
        if len(completed) != len(set(completed)):
            raise ValueError("GUI completed stages must be unique")
        if any(name not in names for name in completed):
            raise ValueError("GUI completed stage is not in the session plan")
        if names != tuple(name for name in STAGE_NAMES if name in names):
            raise ValueError("GUI view stages must use canonical order")
        if completed != tuple(name for name in names if name in completed):
            raise ValueError("GUI completed stages must use plan order")
        if self.current_stage is not None and self.current_stage not in names:
            raise ValueError("GUI current stage is not in the session plan")
        if self.failed_stage is not None and self.failed_stage not in names:
            raise ValueError("GUI failed stage is not in the session plan")
        if type(self.last_sequence) is not int or self.last_sequence < 0:
            raise ValueError("GUI last sequence must be nonnegative")
        if type(self.close_requested) is not bool:
            raise TypeError("GUI close flag must be an exact boolean")
        object.__setattr__(self, "stage_names", names)
        object.__setattr__(self, "completed_stages", completed)


@dataclass(frozen=True)
class GuiRunUpdate:
    console_records: Tuple[GuiConsoleRecord, ...] = ()
    stage_updates: Tuple[GuiStageUpdate, ...] = ()
    run_enabled: Optional[bool] = None
    ensure_run_tab: bool = False
    hide_window: bool = False
    show_window: bool = False
    close_window: bool = False

    def __post_init__(self) -> None:
        records = tuple(self.console_records)
        stages = tuple(self.stage_updates)
        if any(not isinstance(item, GuiConsoleRecord) for item in records):
            raise TypeError("GUI update console records have the wrong type")
        if any(not isinstance(item, GuiStageUpdate) for item in stages):
            raise TypeError("GUI update stage records have the wrong type")
        if self.run_enabled is not None and type(self.run_enabled) is not bool:
            raise TypeError("GUI run-enabled command must be boolean or None")
        for value in (
            self.ensure_run_tab,
            self.hide_window,
            self.show_window,
            self.close_window,
        ):
            if type(value) is not bool:
                raise TypeError("GUI update commands must be exact booleans")
        object.__setattr__(self, "console_records", records)
        object.__setattr__(self, "stage_updates", stages)


class GuiRunController:
    """Per-window session state and completion-order gate."""

    def __init__(self) -> None:
        self._next_identifier = 1
        self._session: Optional[GuiRunSession] = None
        self._plan: Optional[ExecutionPlan] = None
        self._state: Optional[GuiRunViewState] = None
        self._pending: Optional[GuiRunCompletion] = None
        self._last_terminal_state: Optional[GuiRunViewState] = None
        self._last_result_code: Optional[int] = None

    @property
    def active(self) -> bool:
        return self._session is not None

    @property
    def session(self) -> Optional[GuiRunSession]:
        return self._session

    @property
    def plan(self) -> Optional[ExecutionPlan]:
        return self._plan

    @property
    def state(self) -> Optional[GuiRunViewState]:
        return self._state

    @property
    def last_terminal_state(self) -> Optional[GuiRunViewState]:
        return self._last_terminal_state

    @property
    def last_result_code(self) -> Optional[int]:
        return self._last_result_code

    def begin(
        self,
        plan: ExecutionPlan,
        hidden: bool,
    ) -> Tuple[Optional[GuiIssue], Optional[GuiRunUpdate]]:
        if self.active:
            return (
                gui_issue(
                    "KAM-GUI-E100",
                    "run",
                    "a pipeline run is already active for this window",
                ),
                None,
            )
        if not isinstance(plan, ExecutionPlan):
            raise TypeError("GUI controller requires an ExecutionPlan")
        from .run_present import start_run

        names = tuple(stage.spec.name for stage in plan.stages)
        session = GuiRunSession(self._next_identifier, names, hidden)
        self._next_identifier += 1
        state, update = start_run(session)
        self._session = session
        self._plan = plan
        self._state = state
        self._pending = None
        return None, update

    def accept_event(
        self,
        envelope: GuiRunEventEnvelope,
    ) -> Tuple[GuiRunUpdate, ...]:
        from .run_present import issue_update, reduce_run_event

        if self._state is None or self._session is None:
            return (issue_update(gui_issue(
                "KAM-GUI-E101",
                "event",
                "pipeline event does not belong to an active session",
            )),)
        previous_sequence = self._state.last_sequence
        state, update = reduce_run_event(self._state, envelope)
        self._state = state
        updates = [update]
        if (
            state.last_sequence != previous_sequence
            and self._pending is not None
            and state.last_sequence == self._pending.final_posted_sequence
        ):
            updates.append(self._apply_completion(self._pending))
        return tuple(updates)

    def accept_completion(
        self,
        completion: GuiRunCompletion,
    ) -> Tuple[GuiRunUpdate, ...]:
        from .run_present import issue_update

        if self._state is None or self._session is None:
            return (issue_update(gui_issue(
                "KAM-GUI-E101",
                "completion",
                "pipeline completion does not belong to an active session",
            )),)
        if completion.session_id != self._session.identifier:
            return (issue_update(gui_issue(
                "KAM-GUI-E101",
                "completion",
                "pipeline completion belongs to a stale session",
            )),)
        if completion.final_posted_sequence > self._state.last_sequence:
            self._pending = completion
            return ()
        if completion.final_posted_sequence < self._state.last_sequence:
            return (issue_update(gui_issue(
                "KAM-GUI-E102",
                "completion.sequence",
                "pipeline completion sequence precedes applied events",
            )),)
        return (self._apply_completion(completion),)

    def request_close(self) -> GuiRunUpdate:
        from .run_present import issue_update

        if self._state is None:
            return GuiRunUpdate(close_window=True)
        self._state = replace(self._state, close_requested=True)
        return issue_update(GuiIssue(
            "KAM-GUI-E100",
            "warning",
            "window.close",
            "close is deferred until the active pipeline run finishes",
        ))

    def _apply_completion(self, completion: GuiRunCompletion) -> GuiRunUpdate:
        from .run_present import complete_run

        if self._state is None or self._session is None:
            raise RuntimeError("cannot complete an inactive GUI session")
        state, update = complete_run(self._state, completion)
        update = replace(
            update,
            show_window=self._session.hidden or update.show_window,
            close_window=state.close_requested or update.close_window,
        )
        self._last_terminal_state = state
        expected_status = {
            "run-succeeded": "succeeded",
            "run-failed": "failed",
            "run-cancelled": "cancelled",
        }.get(self._state.terminal_event_kind if self._state is not None else None)
        boundary_failure = completion.issue is not None or (
            completion.result is not None
            and (
                expected_status is None
                and not (
                    completion.result.status == "failed"
                    and completion.result.exit_code == 5
                )
                or expected_status is not None
                and completion.result.status != expected_status
            )
        )
        if boundary_failure:
            self._last_result_code = 5
        else:
            self._last_result_code = completion.result.exit_code
        self._session = None
        self._plan = None
        self._state = None
        self._pending = None
        return update


__all__ = [
    "CONSOLE_SEVERITIES",
    "GUI_ISSUE_CATALOG",
    "GuiConsoleRecord",
    "GuiIssue",
    "GuiRunCompletion",
    "GuiRunController",
    "GuiRunEventEnvelope",
    "GuiRunSession",
    "GuiRunUpdate",
    "GuiRunViewState",
    "GuiStageUpdate",
    "gui_issue",
]
