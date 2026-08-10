"""Pure RunEvent presentation and a narrow GUI-thread update applier."""

from dataclasses import replace
from typing import Any, Optional, Tuple

from .run_model import (
    GuiConsoleRecord,
    GuiIssue,
    GuiRunCompletion,
    GuiRunEventEnvelope,
    GuiRunSession,
    GuiRunUpdate,
    GuiRunViewState,
    GuiStageUpdate,
    gui_issue,
)


TERMINAL_EVENT_EXPECTATIONS = {
    "run-succeeded": ("succeeded", frozenset({0})),
    "run-failed": ("failed", frozenset({4, 5, 6})),
    "run-cancelled": ("cancelled", frozenset({130})),
}
SEVERITY_COLORS = {
    "info": "black",
    "warning": "dark orange",
    "error": "firebrick1",
    "success": "green",
    "output": "black",
}
PROGRESS_KEYS = {
    "population": ("-POPPROGR-", "-POPPROGRTS-"),
    "model": ("-MODELPROGR-", "-MODELPROGRTS-"),
}


def _record(severity: str, text: str) -> GuiConsoleRecord:
    return GuiConsoleRecord(severity, text)


def _issue_text(issue: Any) -> str:
    return "{0} {1}: {2}".format(issue.code, issue.field, issue.message)


def issue_record(issue: Any) -> GuiConsoleRecord:
    severity = "error" if issue.level == "error" else "warning"
    return _record(severity, _issue_text(issue))


def issue_update(issue: GuiIssue) -> GuiRunUpdate:
    return GuiRunUpdate(console_records=(issue_record(issue),))


def issues_update(issues: Tuple[Any, ...]) -> GuiRunUpdate:
    return GuiRunUpdate(
        console_records=tuple(issue_record(issue) for issue in issues)
    )


def start_run(
    session: GuiRunSession,
) -> Tuple[GuiRunViewState, GuiRunUpdate]:
    state = GuiRunViewState(
        session_id=session.identifier,
        status="running",
        stage_names=session.stage_names,
        current_stage=None,
        terminal_event_kind=None,
        completed_stages=(),
        failed_stage=None,
        last_sequence=0,
        close_requested=False,
    )
    update = GuiRunUpdate(
        run_enabled=False,
        ensure_run_tab=True,
        hide_window=session.hidden,
    )
    return state, update


def _invalid(
    state: GuiRunViewState,
    code: str,
    field: str,
    message: str,
) -> Tuple[GuiRunViewState, GuiRunUpdate]:
    return state, issue_update(gui_issue(code, field, message))


def _advance_output_state(
    state: GuiRunViewState,
    sequence: int,
) -> GuiRunViewState:
    """Copy validated immutable state on the bounded output hot path."""

    advanced = object.__new__(GuiRunViewState)
    advanced.__dict__.update(state.__dict__)
    object.__setattr__(advanced, "last_sequence", sequence)
    return advanced


def _event_record(envelope: GuiRunEventEnvelope) -> Optional[GuiConsoleRecord]:
    event = envelope.event
    if event.kind == "run-started":
        return _record("info", "Run started")
    if event.kind == "preflight-failed":
        return _record(
            "error",
            "{0} preflight failed [{1}]: {2}".format(
                event.stage, event.exit_code, event.message
            ),
        )
    if event.kind == "stage-started":
        return _record("info", "{0} started".format(event.stage))
    if event.kind == "stage-output":
        return _record("output", event.line or "")
    if event.kind == "stage-succeeded":
        return _record("success", "{0} succeeded".format(event.stage))
    if event.kind == "stage-failed":
        return _record(
            "error",
            "{0} failed [{1}]: {2}".format(
                event.stage, event.exit_code, event.message or "stage execution failed"
            ),
        )
    if event.kind == "stage-cancelled":
        return _record(
            "warning",
            "{0} cancelled [130]: {1}".format(
                event.stage, event.message or "run interrupted"
            ),
        )
    if event.kind == "termination-escalated":
        return _record(
            "warning",
            "{0}: {1}".format(event.stage, event.message)
        )
    return None


def _stage_update(envelope: GuiRunEventEnvelope) -> Optional[GuiStageUpdate]:
    event = envelope.event
    if event.stage is None:
        return None
    if event.kind == "stage-started":
        return GuiStageUpdate(
            event.stage,
            "running",
            progress=0,
            timestamp=event.timestamp,
            log_path=event.log_path,
        )
    if event.kind == "stage-succeeded":
        return GuiStageUpdate(
            event.stage,
            "succeeded",
            progress=100,
            timestamp=event.timestamp,
            exit_code=event.exit_code,
            child_exit_code=event.child_exit_code,
            log_path=event.log_path,
        )
    if event.kind in {"stage-failed", "preflight-failed"}:
        return GuiStageUpdate(
            event.stage,
            "failed",
            timestamp=event.timestamp,
            exit_code=event.exit_code,
            child_exit_code=event.child_exit_code,
            message=event.message,
            log_path=event.log_path,
        )
    if event.kind == "stage-cancelled":
        return GuiStageUpdate(
            event.stage,
            "cancelled",
            timestamp=event.timestamp,
            exit_code=event.exit_code,
            child_exit_code=event.child_exit_code,
            message=event.message,
            log_path=event.log_path,
        )
    return None


def reduce_run_event(
    state: GuiRunViewState,
    envelope: GuiRunEventEnvelope,
) -> Tuple[GuiRunViewState, GuiRunUpdate]:
    """Reduce one active-session event without I/O or retained output."""

    if not isinstance(state, GuiRunViewState):
        raise TypeError("state must be GuiRunViewState")
    if not isinstance(envelope, GuiRunEventEnvelope):
        raise TypeError("envelope must be GuiRunEventEnvelope")
    if envelope.session_id != state.session_id:
        return _invalid(
            state,
            "KAM-GUI-E101",
            "event.session",
            "pipeline event belongs to a stale session",
        )
    expected = state.last_sequence + 1
    if envelope.event.sequence != expected:
        return _invalid(
            state,
            "KAM-GUI-E102",
            "event.sequence",
            "pipeline event sequence must be {0}, received {1}".format(
                expected, envelope.event.sequence
            ),
        )
    event = envelope.event
    if event.stage is not None and event.stage not in state.stage_names:
        return _invalid(
            state,
            "KAM-GUI-E104",
            "event.stage",
            "pipeline event names a stage outside the active plan",
        )
    if event.kind == "stage-output":
        return _advance_output_state(
            state, event.sequence
        ), GuiRunUpdate(console_records=(
            GuiConsoleRecord("output", event.line or ""),
        ))

    current = state.current_stage
    completed = state.completed_stages
    failed = state.failed_stage
    terminal = state.terminal_event_kind
    if event.kind == "stage-started":
        current = event.stage
    elif event.kind == "stage-succeeded":
        current = None
        if event.stage not in completed:
            completed = completed + (event.stage,)
    elif event.kind in {"stage-failed", "preflight-failed", "stage-cancelled"}:
        current = None
        failed = event.stage
    elif event.kind in TERMINAL_EVENT_EXPECTATIONS:
        terminal = event.kind

    next_state = replace(
        state,
        current_stage=current,
        terminal_event_kind=terminal,
        completed_stages=completed,
        failed_stage=failed,
        last_sequence=event.sequence,
    )
    record = _event_record(envelope)
    stage_update = _stage_update(envelope)
    return next_state, GuiRunUpdate(
        console_records=() if record is None else (record,),
        stage_updates=() if stage_update is None else (stage_update,),
    )


def _completion_failure(
    state: GuiRunViewState,
    issue: GuiIssue,
) -> Tuple[GuiRunViewState, GuiRunUpdate]:
    failed = replace(state, status="failed", current_stage=None)
    return failed, GuiRunUpdate(
        console_records=(
            issue_record(issue),
            _record("error", "Run failed [5]"),
        ),
        run_enabled=True,
    )


def complete_run(
    state: GuiRunViewState,
    completion: GuiRunCompletion,
) -> Tuple[GuiRunViewState, GuiRunUpdate]:
    """Apply the exact completion only after its final sequence is drained."""

    if not isinstance(state, GuiRunViewState):
        raise TypeError("state must be GuiRunViewState")
    if not isinstance(completion, GuiRunCompletion):
        raise TypeError("completion must be GuiRunCompletion")
    if completion.session_id != state.session_id:
        return _invalid(
            state,
            "KAM-GUI-E101",
            "completion.session",
            "pipeline completion belongs to a stale session",
        )
    if completion.final_posted_sequence != state.last_sequence:
        return _invalid(
            state,
            "KAM-GUI-E102",
            "completion.sequence",
            "pipeline completion is not aligned with applied events",
        )
    if completion.issue is not None:
        return _completion_failure(state, completion.issue)

    result = completion.result
    if result is None:
        raise RuntimeError("validated GUI completion has no result")
    expectation = TERMINAL_EVENT_EXPECTATIONS.get(state.terminal_event_kind)
    if expectation is None and not (
        result.status == "failed" and result.exit_code == 5
    ):
        return _completion_failure(
            state,
            gui_issue(
                "KAM-GUI-E103",
                "completion.result",
                "pipeline result has no delivered terminal event",
            ),
        )
    if expectation is not None and (
        result.status != expectation[0] or result.exit_code not in expectation[1]
    ):
        return _completion_failure(
            state,
            gui_issue(
                "KAM-GUI-E103",
                "completion.result",
                "pipeline terminal event and result are inconsistent",
            ),
        )
    if result.status == "succeeded":
        severity = "success"
        text = "Run succeeded [0]"
    elif result.status == "cancelled":
        severity = "warning"
        text = "Run cancelled [130]"
    else:
        severity = "error"
        text = "Run failed [{0}]".format(result.exit_code)
    terminal_state = replace(
        state,
        status=result.status,
        current_stage=None,
    )
    return terminal_state, GuiRunUpdate(
        console_records=(_record(severity, text),),
        run_enabled=True,
    )


def apply_run_update(
    window: Any,
    update: GuiRunUpdate,
    *,
    console_key: str = "-CONSOLE-",
    tab_key: Optional[str] = "-MAINGROUP-",
    run_key: str = "-RUN-",
    pause_key: Optional[str] = "-PAUSE-",
    resume_key: Optional[str] = "-RESUME-",
) -> Optional[GuiIssue]:
    """Apply one bounded delta on the caller's GUI thread."""

    try:
        for record in update.console_records:
            window[console_key].print(
                record.text,
                text_color=SEVERITY_COLORS[record.severity],
            )
        for stage_update in update.stage_updates:
            keys = PROGRESS_KEYS.get(stage_update.stage)
            if keys is None:
                continue
            progress_key, timestamp_key = keys
            if stage_update.progress is not None:
                window[progress_key].update(
                    current_count=stage_update.progress
                )
            if stage_update.timestamp is not None:
                window[timestamp_key].update(stage_update.timestamp)
        if update.run_enabled is not None:
            window[run_key].update(disabled=not update.run_enabled)
            if pause_key is not None:
                window[pause_key].update(disabled=True)
            if resume_key is not None:
                window[resume_key].update(disabled=True)
        if update.ensure_run_tab and tab_key is not None:
            window[tab_key].Widget.select(1)
        if update.hide_window:
            window.hide()
        if update.show_window:
            window.un_hide()
        if update.close_window:
            window.close()
    except Exception as error:
        return gui_issue(
            "KAM-GUI-E104",
            "window.update",
            "GUI presentation failed ({0})".format(type(error).__name__),
        )
    return None


__all__ = [
    "apply_run_update",
    "complete_run",
    "issue_record",
    "issue_update",
    "issues_update",
    "reduce_run_event",
    "start_run",
]
