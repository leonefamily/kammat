# -*- coding: utf-8 -*-
"""
Created on Mon Mar  6 16:58:57 2023

@author: dgrishchuk
"""


"""Results GUI composed over shared configuration, planning, and execution."""

from typing import Any, Mapping, Optional

import PySimpleGUI as sg

from kammat.main.configuration import RunConfig, has_errors, load_run_config

#TODO(idrees): fix the naming of variables and modules
from kammat.gui.run_adapter import (
    PIPELINE_DONE_KEY,
    PIPELINE_EVENT_KEY,
    RESULT_STAGES,
    prepare_results_plan,
    results_field_specs,
    results_form_values,
    run_gui_plan,
)
from kammat.gui.run_model import (
    GuiRunCompletion,
    GuiRunController,
    GuiRunEventEnvelope,
    gui_issue,
)
from kammat.gui.run_present import apply_run_update, issue_update, issues_update
from kammat.gui.tk_compat import ensure_pysimplegui_tcl_compat


sg.theme('default1')


def _apply_pipeline_updates(window: Any, updates: tuple):
    first_issue = None
    for update in updates:
        issue = apply_run_update(
            window,
            update,
            tab_key=None,
            pause_key=None,
            resume_key=None,
        )
        if issue is not None:
            if first_issue is None:
                first_issue = issue
            try:
                window['-CONSOLE-'].print(
                    '{0} {1}: {2}'.format(
                        issue.code, issue.field, issue.message
                    ),
                    text_color='firebrick1',
                )
            except Exception:
                pass
    return first_issue


def generate_analysis_layout(config: RunConfig) -> Optional[Mapping[str, Any]]:
    """Collect typed results edits from schema-derived widgets."""

    ensure_pysimplegui_tcl_compat(sg)
    defaults = results_form_values(config)
    fields = results_field_specs()
    inner_layout = []
    for stage in RESULT_STAGES:
        rows = [[sg.Checkbox(
            'launch',
            key=stage + '|launch|',
            default=defaults[stage + '|launch|'],
        )]]
        for dotted, spec in fields.items():
            owner, field = dotted.split('.', 1)
            if owner != stage:
                continue
            label = sg.Text(field, size=30, key=stage + '[' + field + ']')
            if spec.value_kind == 'bool':
                value_element = sg.Checkbox(
                    '', key=dotted, default=defaults[dotted]
                )
                rows.append([label, value_element])
            else:
                value_element = sg.Input(
                    default_text=defaults[dotted], size=50, key=dotted
                )
                if spec.value_kind == 'path':
                    rows.append([label, value_element, sg.FileBrowse()])
                else:
                    rows.append([label, value_element])
        inner_layout.append([sg.Frame(stage, rows)])

    column = sg.Column(
        inner_layout,
        key='-INPUTCOL-',
        size=(720, 500),
        scrollable=True,
        vertical_scroll_only=True,
    )
    edit_window = sg.Window(
        'Values', [[column], [sg.Button('Apply', key='-APPLY-')]]
    )
    selected = None
    while True:
        event, values = edit_window.read()
        if event == sg.WINDOW_CLOSED:
            break
        if event == '-APPLY-':
            selected = dict(values)
            break
    edit_window.close()
    return selected


def main() -> None:
    ensure_pysimplegui_tcl_compat(sg)
    layout = [
        [sg.Text('Load settings JSON', size=20),
         sg.Input(key='-JSON-', size=50),
         sg.FileBrowse(key='-LOAD-')],
        [sg.Button('Change JSON', key='-CHANGE-'),
         sg.Button('Run', key='-RUN-')],
        [sg.Output(key='-CONSOLE-', size=(25, 20),
                   expand_x=True, echo_stdout_stderr=False)],
    ]
    window = sg.Window('Analysis', layout)
    controller = GuiRunController()
    loaded_config = None
    edit_values = None

    try:
        while True:
            event, values = window.read()
            if event == sg.WINDOW_CLOSED:
                if controller.active:
                    _apply_pipeline_updates(window, (controller.request_close(),))
                    continue
                break
            if event == '-CHANGE-':
                if controller.active:
                    issue, _ = controller.begin(controller.plan, False)
                    if issue is not None:
                        _apply_pipeline_updates(window, (issue_update(issue),))
                    continue
                loaded = load_run_config(values['-JSON-'])
                _apply_pipeline_updates(
                    window, (issues_update(tuple(loaded.issues)),)
                )
                if loaded.config is None or has_errors(loaded.issues):
                    loaded_config = None
                    edit_values = None
                    continue
                loaded_config = loaded.config
                edit_values = generate_analysis_layout(loaded_config)
            if event == '-RUN-':
                if controller.active:
                    issue, _ = controller.begin(controller.plan, False)
                    if issue is not None:
                        _apply_pipeline_updates(window, (issue_update(issue),))
                    continue
                if loaded_config is None or edit_values is None:
                    _apply_pipeline_updates(window, (issue_update(gui_issue(
                        'KAM-GUI-E104',
                        'results.settings',
                        'load and apply results settings before running',
                    )),))
                    continue
                plan, issues = prepare_results_plan(loaded_config, edit_values)
                _apply_pipeline_updates(window, (issues_update(issues),))
                if plan is None or has_errors(issues):
                    continue
                issue, update = controller.begin(plan, False)
                if issue is not None or update is None:
                    if issue is not None:
                        _apply_pipeline_updates(window, (issue_update(issue),))
                    continue
                session = controller.session
                if session is None:
                    continue
                presentation_issue = _apply_pipeline_updates(window, (update,))
                if presentation_issue is not None:
                    _apply_pipeline_updates(
                        window,
                        controller.accept_completion(GuiRunCompletion(
                            session.identifier,
                            0,
                            issue=presentation_issue,
                        )),
                    )
                    continue
                try:
                    window.start_thread(
                        lambda active_session=session, active_plan=plan: run_gui_plan(
                            active_session,
                            active_plan,
                            window.write_event_value,
                        ),
                        PIPELINE_DONE_KEY,
                    )
                except Exception as error:
                    completion = GuiRunCompletion(
                        session.identifier,
                        0,
                        issue=gui_issue(
                            'KAM-GUI-E103',
                            'worker.start',
                            'pipeline worker failed ({0})'.format(
                                type(error).__name__
                            ),
                        ),
                    )
                    _apply_pipeline_updates(
                        window, controller.accept_completion(completion)
                    )
            if event == PIPELINE_EVENT_KEY:
                envelope = values[event]
                if isinstance(envelope, GuiRunEventEnvelope):
                    _apply_pipeline_updates(
                        window, controller.accept_event(envelope)
                    )
                else:
                    envelope_issue = gui_issue(
                        'KAM-GUI-E104',
                        'event',
                        'pipeline event envelope has the wrong type',
                    )
                    session = controller.session
                    state = controller.state
                    if session is not None and state is not None:
                        _apply_pipeline_updates(
                            window,
                            controller.accept_completion(GuiRunCompletion(
                                session.identifier,
                                state.last_sequence,
                                issue=envelope_issue,
                            )),
                        )
                    else:
                        _apply_pipeline_updates(
                            window, (issue_update(envelope_issue),)
                        )
            if event == PIPELINE_DONE_KEY:
                completion = values[event]
                if not isinstance(completion, GuiRunCompletion):
                    session = controller.session
                    state = controller.state
                    if session is not None and state is not None:
                        completion = GuiRunCompletion(
                            session.identifier,
                            state.last_sequence,
                            issue=gui_issue(
                                'KAM-GUI-E103',
                                'completion',
                                'pipeline completion has the wrong type',
                            ),
                        )
                if isinstance(completion, GuiRunCompletion):
                    close_requested = bool(
                        controller.state is not None
                        and controller.state.close_requested
                    )
                    _apply_pipeline_updates(
                        window, controller.accept_completion(completion)
                    )
                    if close_requested and not controller.active:
                        return
    except Exception as error:
        sg.popup_error(
            'Results GUI failed ({0})'.format(type(error).__name__)
        )
    finally:
        if not controller.active:
            window.close()


if __name__ == '__main__':
    main()
