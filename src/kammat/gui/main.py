# -*- coding: utf-8 -*-
"""
Created on Mon Feb 27 11:03:48 2023

@author: dgrishchuk
"""
import logging
import textwrap
import webbrowser
from pathlib import Path
from datetime import datetime as dt
from typing import List, Optional

from kammat import __version__ as version
from kammat.model.utils import suggest_matsim_ram_limit
from kammat.gui.utils import (
    save_settings, restore_settings, control_disabled,
    dump_log, format_large_number
)
from kammat.defaults.constants import (
    LOGGER_FORMAT, CACHE_SETTINGS_PATH
)
from kammat.model.run import get_matsim_progress_from_config
from kammat.main.configure import (
    has_errors,
)
from kammat.gui.run_adapter import (
    PIPELINE_DONE_KEY,
    PIPELINE_EVENT_KEY,
    gui_tool_argv,
    launch_gui_tool,
    persist_main_gui_plan,
    prepare_main_gui_plan,
    run_gui_plan,
)
from kammat.gui.run_model import (
    GuiRunCompletion,
    GuiRunController,
    GuiRunEventEnvelope,
    gui_issue,
)
from kammat.gui.run_present import (
    apply_run_update,
    issue_update,
    issues_update,
)
from kammat.gui.tk_compat import ensure_pysimplegui_tcl_compat

import PySimpleGUI as sg

sg.theme('default1')

APP_NAME = 'main'
GIT_LINK = 'https://github.com/leonefamily/kammat'
BOLD_FONT = (' '.join(str(t) for t in sg.DEFAULT_FONT) + ' bold')
SUGG_RAM_LIMIT = int(suggest_matsim_ram_limit().replace('m', ''))
MAX_RAM_LIMIT = int(
    suggest_matsim_ram_limit(max_fraction=1, min_free_ram=0).replace('m', '')
)
USENET_KEYS = ['-ENETPATH-', '-ENET-', '-ELDEFPATH-', '-ELDEF-',
               '-ESCHEDPATH-', '-ESCHED-', '-EVEHSPATH-', '-EVEHS-']
USEPOP_KEYS = ['-EPOPPATH-', '-EPOP-']

logging.basicConfig(
    format=LOGGER_FORMAT,
    level=logging.INFO
)

logger = logging.getLogger('main')  # __name__


def get_layout_keys(
        layout: List[sg.Element]
):
    keys = []
    for element in layout:
        if isinstance(element, list):
            keys.extend(get_layout_keys(element))
        else:
            if element.key is not None:
                keys.append(element.key)
    return keys


def about_popup(
        window: sg.Window
):
    ensure_pysimplegui_tcl_compat(sg)
    alayout = [
        [sg.Text('MATSim Model Data Management System')],
        [sg.Text(f'Version: {version}')],
        [sg.Text('Project on GitHub',
                 enable_events=True,
                 font=sg.DEFAULT_FONT + ('underline',),
                 key='-GIT-',
                 metadata={'link': GIT_LINK})],
    ]
    window.disappear()
    awindow = sg.Window('About kammat', alayout, finalize=True)

    while True:
        event, values = awindow.read()
        if event == sg.WINDOW_CLOSED:
            break
        elif event == '-GIT-':
            webbrowser.open(awindow[event].metadata['link'])
    awindow.close()
    window.reappear()


def wrap(
        text: str,
        width: int = 50
) -> str:
    return '\n'.join(textwrap.wrap(text, width=width))


def get_full_layout(
) -> List[sg.Element]:
    layout_wd = [
        [sg.Text('Parent folder', size=15),
         sg.Input('', key='-PARENTPATH-', expand_x=True, enable_events=True),
         sg.FolderBrowse(key='-PARENT-', size=15)],
        [sg.Text('Model directory', size=15),
         sg.Input('', key='-WDPATH-', expand_x=True, enable_events=True),
         sg.Button('Include timestamp', key='-TS-', size=15)],
        [sg.Text('Working directory: ', size=15, text_color='grey'),
         sg.Text('', key='-WDPREV-', expand_x=True,
                 text_color='grey', justification='left')]
    ]

    layout_network_input = [
        [sg.Checkbox('Use existing', default=False, key='-USENET-', size=12,
                     enable_events=True)],
        [sg.Text('Network file', size=15),
         sg.Input('', key='-ENETPATH-', expand_x=True),
         sg.FileBrowse(key='-ENET-', size=6)],
        [sg.Text('Lane definitions', size=15),
         sg.Input('', key='-ELDEFPATH-', expand_x=True),
         sg.FileBrowse(key='-ELDEF-', size=6)],
        [sg.Text('Schedule', size=15),
         sg.Input('', key='-ESCHEDPATH-', expand_x=True),
         sg.FileBrowse(key='-ESCHED-', size=6)],
        [sg.Text('Vehicles', size=15),
         sg.Input('', key='-EVEHSPATH-', expand_x=True),
         sg.FileBrowse(key='-EVEHS-', size=6)],
        [sg.HorizontalSeparator(color='grey')],
        [sg.Text('Network shape*', size=15),
         sg.Input('', key='-NETPATH-', expand_x=True),
         sg.FileBrowse(key='-NET-', size=6)],
        [sg.Text('Lane connections', size=15),
         sg.Input('', key='-LCONPATH-', expand_x=True),
         sg.FileBrowse(key='-LCON-', size=6)],
        [sg.Text('Network settings', size=15),
         sg.Radio('CEDA', key='-NETCEDA-', group_id=0, enable_events=True, default=True),
         sg.Radio('Generic', key='-NETGEN-', group_id=0, enable_events=True),
         sg.Checkbox('Prevent u-turns', default=True, key='-UTURNS-', size=12),
         sg.Checkbox('Simplify intersections', default=True, key='-SIMPLEINT-', size=12)],
        [sg.Text('GTFS folder', size=15),
         sg.Input('', key='-GTFSPATH-', expand_x=True),
         sg.FolderBrowse(key='-GTFS-', size=6)]
    ]

    layout_population_input = [
        [sg.Checkbox('Use existing', default=False, key='-USEPOP-', size=12,
                     enable_events=True)],
        [sg.Text('Population file', size=15),
         sg.Input('', key='-EPOPPATH-', expand_x=True),
         sg.FileBrowse(key='-EPOP-', size=6)],
        [sg.HorizontalSeparator(color='grey')],
        [sg.Checkbox('Write teleported modes', default=False, key='-WRITETP-')],
        [sg.Text('Population fraction', size=15),
         sg.Slider(range=(0.01, 1), orientation='h', resolution=0.01,
                   default_value=1, key='-POPFRAC-', expand_x=True)],
        [sg.Text('Incremental capacity allocation', size=15),
         sg.Slider(range=(1, 10), orientation='h', resolution=1,
                   default_value=1, key='-INCRCAP-', expand_x=True)],
        [sg.Text('Facilities shape*', size=15),
         sg.Input('', key='-POPPATH-', expand_x=True),
         sg.FileBrowse(key='-POP-', size=6)],
        [sg.Text('Clusters shape', size=15),
         sg.Input('', key='-CLUSTPATH-', expand_x=True),
         sg.FileBrowse(key='-CLUST-', size=6)],
        [sg.Text('Spatial units shape', size=15),
         sg.Input('', key='-SUPATH-', expand_x=True),
         sg.FileBrowse(key='-SU-', size=6)],
        [sg.Text('Categories*', size=15),
         sg.Input('', key='-CATPATH-', expand_x=True),
         sg.FileBrowse(key='-CAT-', size=6)],
        [sg.Text('Diaries*', size=15),
         sg.Input('', key='-DIARPATH-', expand_x=True),
         sg.FileBrowse(key='-DIAR-', size=6)],
        [sg.Text('Distances*', size=15),
         sg.Input('', key='-DISTPATH-', expand_x=True),
         sg.FileBrowse(key='-DIST-', size=6)],
        [sg.Text('Staying', size=15),
         sg.Input('', key='-STAYPATH-', expand_x=True),
         sg.FileBrowse(key='-STAY-', size=6)],
        [sg.Text('Target probabilities', size=15),
         sg.Input('', key='-TARGPATH-', expand_x=True),
         sg.FileBrowse(key='-TARG-', size=6)],
        [sg.Text('Times', size=15),
         sg.Input('', key='-TIMEPATH-', expand_x=True),
         sg.FileBrowse(key='-TIME-', size=6)],
        [sg.Text('Modal split*', size=15),
         sg.Input('', key='-MSPATH-', expand_x=True),
         sg.FileBrowse(key='-MS-', size=6)],
        [sg.Text('Indices', size=15),
         sg.Input('', key='-INDPATH-', expand_x=True),
         sg.FileBrowse(key='-IND-', size=6)],
        [sg.Text('Relations', size=15),
         sg.Input('', key='-RELPATH-', expand_x=True),
         sg.FileBrowse(key='-REL-', size=6)],
        [sg.Text('Stops*', size=15),
         sg.Input('', key='-STOPPATH-', expand_x=True),
         sg.FileBrowse(key='-STOP-', size=6)],
        [sg.Text('Citylog data', size=15),
         sg.Input('', key='-CLOGPATH-', expand_x=True),
         sg.FileBrowse(key='-CLOG-', size=6)],
        [sg.Text('Citylog points shape', size=15),
         sg.Input('', key='-CLOGSPATH-', expand_x=True),
         sg.FileBrowse(key='-CLOGS-', size=6)],
        [sg.Text('Freight points shape', size=15),
         sg.Input('', key='-FREPATH-', expand_x=True),
         sg.FileBrowse(key='-FRE-', size=6)],
        [sg.Text('Transit points shape', size=15),
         sg.Input('', key='-TRANPATH-', expand_x=True),
         sg.FileBrowse(key='-TRAN-', size=6)],
        [sg.Text('One-way flows', size=15),
         sg.Input('', key='-OFLOWPATH-', expand_x=True),
         sg.FileBrowse(key='-TARG-', size=6)],
        [sg.Text('Time courses path', size=15),
         sg.Input('', key='-TCOURPATH-', expand_x=True),
         sg.FileBrowse(key='-TCOUR-', size=6)]
    ]

    sim_settings_input = [
        [sg.Checkbox('Run model', default=True, key='-RUNMOD-')],
        [sg.Text('MATSim executable path', size=15),
         sg.Input('', key='-MATSIMPATH-', expand_x=True),
         sg.FileBrowse(key='-MATSIM-', size=6)],
        [sg.Text('Custom scoring params', size=15),
         sg.Input('', key='-SCPARSPATH-', expand_x=True),
         sg.FileBrowse(key='-SCPARS-', size=6)],
        [sg.Text('Minibus params', size=15),
         sg.Input('', key='-PPARSPATH-', expand_x=True),
         sg.FileBrowse(key='-PPARS-', size=6)],
        [sg.Text('Runnable class', size=15),
         sg.Input('', key='-CCLASS-', expand_x=True)],
        [sg.Text('MATSim RAM limit', size=15),
         sg.Slider(range=(1000, MAX_RAM_LIMIT), orientation='h',
                   resolution=100, default_value=SUGG_RAM_LIMIT,
                   key='-MATSIMRAM-', expand_x=True)],
        [sg.Text('Threads count', size=15),
         sg.Slider(range=(1, os.cpu_count()), orientation='h',
                   default_value=os.cpu_count() - 2,
                   key='-THREADS-', expand_x=True)],
        [sg.Text('Time mutation', size=15),
         sg.Slider(range=(0, 30), orientation='h',
                   default_value=30, key='-TIMEMUT-', expand_x=True)],
        [sg.Text('Iterations count', size=15),
         sg.Slider(range=(1, 1000), orientation='h',
                   default_value=300, key='-ITERS-', expand_x=True)],
        [sg.Text('Mutations fraction', size=15),
         sg.Slider(range=(0, 1), orientation='h', resolution=0.01,
                   default_value=0.9, key='-MUTFRAC-', expand_x=True)],
        [sg.Text('Simulation step', size=15),
         sg.Slider(range=(1, 30), orientation='h',
                   default_value=1, key='-STEP-', expand_x=True)],
    ]

    ribbon_tt = (
        'Get ribbon diagrams from common nodes for link groups: '
        'link11, link12... link1n; link21, link22... link2n'
    )
    analysis_input = [
        [sg.Checkbox('Analyze outputs', default=True, key='-ANALYZE-')],
        [sg.Checkbox('Create events DB', default=True, key='-EVENTSDB-'),
         sg.Slider(range=(100000, 10000000), orientation='h', key='-DBFLUSH-',
                   resolution=100000, default_value=1000000,  expand_x=True,
                   enable_events=True, disable_number_display=True),
         sg.Text('Flush every', size=8),
         sg.Text('', size=8, key='-DBFLUSHLAB-')],
        [sg.Text('Ribbon diagrams', size=15, tooltip=ribbon_tt),
         sg.Input('', key='-LINKGROUPS-', tooltip=ribbon_tt, expand_x=True)],
        [sg.Text('Links intensities', size=15),
         sg.Input('', key='-LINKINTENS-', expand_x=True)],
        [sg.Text('PT links intensities', size=15),
         sg.Input('', key='-PTLINKINTENS-', expand_x=True)],
        [sg.Text('PT lines intensities', size=15),
         sg.Input('', key='-PTLINEINTENS-', expand_x=True)],
        [sg.Text('Cordon polygons', size=15),
         sg.Input('', key='-CORDPOLYPATH-', expand_x=True),
         sg.FileBrowse(key='-CORDPOLY-', size=6)],
        [sg.Text('Volume polygons', size=15),
         sg.Input('', key='-VOLPOLYPATH-', expand_x=True),
         sg.FileBrowse(key='-VOLPOLY-', size=6)],
    ]

    comparison_input = [
        [sg.Checkbox('Compare outputs', default=True, key='-COMPARE-')],
        [sg.Text('Network intensities', size=15),
         sg.Input('', key='-NINTPATH-', expand_x=True),
         sg.FileBrowse(key='-NINT-', size=6)],
        [sg.Text('Intersection intensities', size=15),
         sg.Input('', key='-IINTPATH-', expand_x=True),
         sg.FileBrowse(key='-IINT-', size=6)],
        [sg.Text('Previous model run', size=15),
         sg.Input('', key='-PMODPATH-', expand_x=True),
         sg.FolderBrowse(key='-PMOD-', size=6)]
    ]

    vis_input = [
        [sg.Checkbox('Create QGIS project', default=True, key='-QGIS-')],
        [sg.Text("QGIS's Python", size=15),
         sg.Input('', key='-QGISPATH-', expand_x=True),
         sg.FolderBrowse(key='-FQGIS-', size=6)]
    ]

    layout_run_input = [
        # sg.one_line_progress_meter('Network', 0, 100, key='-NETPROGR-')
        [sg.Text('Network', size=15, key='-NETPROGRTEXT-'),
         sg.ProgressBar(max_value=100, orientation='h', expand_x=True, size=(35, 5), key='-NETPROGR-'),
         sg.Text('', size=25, key='-NETWORKPROGRTS-')],
        [sg.Text('Public transport', size=15, key='-PTPROGRTEXT-'),
         sg.ProgressBar(max_value=100, orientation='h', expand_x=True, size=(35, 5), key='-PTPROGR-'),
         sg.Text('', size=25, key='-PTPROGRTS-')],
        [sg.Text('Population', size=15, key='-POPPROGRTEXT-'),
         sg.ProgressBar(max_value=100, orientation='h', expand_x=True, size=(35, 5), key='-POPPROGR-'),
         sg.Text('', size=25, key='-POPPROGRTS-')],
        [sg.Text('Simulation', size=15, key='-MODELPROGRTEXT-'),
         sg.ProgressBar(max_value=100, orientation='h', expand_x=True, size=(35, 5), key='-MODELPROGR-'),
         sg.Text('', size=25, key='-MODELPROGRTS-')],
        [sg.Text('Analysis', size=15, key='-ANALYSISPROGRTEXT-'),
         sg.ProgressBar(max_value=100, orientation='h', expand_x=True, size=(35, 5), key='-ANALYSISPROGR-'),
         sg.Text('', size=25, key='-ANALYSISPROGRTS-')],
    ]

    settings_opts = [
        ['&GUI', ['&Layout ', ['&Save...::-SAVES-',
                               '&Load...::-LOADS-',
                               '&Reset::-RESTS-'],
                  '&Save console output...::-SAVEL-']
         ],
        ['&Help', ['&About...::-ABOUT-']]
    ]

    layout_input = [
        [sg.Menu(settings_opts, key='-MENU-')],
        [sg.Frame('Working directory', layout_wd, font=BOLD_FONT, expand_x=True)],
        [sg.Frame('Network', layout_network_input, font=BOLD_FONT, expand_x=True)],
        [sg.Frame('Population', layout_population_input, font=BOLD_FONT, expand_x=True)],
        [sg.Frame('Simulation', sim_settings_input, font=BOLD_FONT, expand_x=True)],
        [sg.Frame('Analysis', analysis_input, font=BOLD_FONT, expand_x=True)],
        [sg.Frame('Comparison', comparison_input, font=BOLD_FONT, expand_x=True)],
        [sg.Frame('Visualization', vis_input, font=BOLD_FONT, expand_x=True)]
    ]

    rcm_console = ['Copy selection::-CSEL-',
                   'Copy all::-CALL-',
                   'Save selection::-SSEL-',
                   'Save all::-SALL-']

    layout_run = [
        [sg.Output(key='-CONSOLE-', size=(25, 20), expand_x=True,
                   echo_stdout_stderr=True,
                   right_click_menu=['&Right', rcm_console])],
        # autoscroll_only_at_bottom=True
        [sg.Frame('Progress', layout_run_input, font=BOLD_FONT, expand_x=True)]
    ]

    layout_done = [
        [sg.Text(wrap('Reproject and/or simplify GTFS timetables'),
                 expand_x=True),
         sg.Text('', size=5, font='_ 25', justification='center'),
         sg.Button('GTFS operations', key='-GTFSOPS-', size=20)],
        [sg.HorizontalSeparator()],
        [sg.Text(wrap('Car and truck intensities on links during one simulation day'),
                 expand_x=True),
         sg.Text('', size=5, font='_ 25', justification='center'),
         sg.Button('Vehicle counts', key='-VEHCOUNTS-', size=20)],
        [sg.HorizontalSeparator()],
        [sg.Text(wrap('PT passenger intensities on links or routes during one simulation day'),
                 expand_x=True),
         sg.Text('', size=5, font='_ 25', justification='center'),
         sg.Button('PT passenger counts', key='-PTCOUNTS-', size=20)],
        [sg.HorizontalSeparator()],
        [sg.Text(wrap('Car or truck intensities in a node or between specified links during one simulation day'),
                 expand_x=True),
         # sg.Text('⮲⮱', size=5, font='_ 25', justification='center'),
         sg.Button('Ribbon diagrams', key='-RIBDIAGS-', size=20)],
        [sg.HorizontalSeparator()],
        [sg.Text(wrap('Decay diagrams showing where from and where to agents do go through certain links'),
                 expand_x=True),
         sg.Text('', size=5, font='_ 25', justification='center'),
         sg.Button('Decay diagrams', key='-DECAYDIAGS-', size=20)],
        [sg.HorizontalSeparator()],
        [sg.Text(wrap('Process results of model from events'),
                 expand_x=True),
         # sg.Text('⮲⮱', size=5, font='_ 25', justification='center'),
         sg.Button('Results analysis', key='-RESANAL-', size=20)]
    ]

    layout = [[sg.TabGroup(
        [
            [
             sg.Tab('Input',
                    [[sg.Column(
                       layout_input, key='-INPUTCOL-',
                       size=(720, 500), expand_x=True,
                       scrollable=True, vertical_scroll_only=True)],
                     [sg.Button('Run', key='-RUN-', tooltip='Run', size=10),
                      sg.Checkbox('Hide GUI during run', key='-NOGUI-')]],
                    key='-INPUTTAB-'
                    ),
             sg.Tab('Run',
                    [[sg.Column(
                       layout_run, key='-RUNCOL-',
                       size=(720, 500), expand_x=True)],
                     [sg.Button('Pause', key='-PAUSE-', size=10, disabled=True),
                      sg.Button('Resume', key='-RESUME-', size=10, disabled=True)]],
                    key='-RUNTAB-'
                    ),
             sg.Tab('Tools',
                    [[sg.Column(
                       layout_done, key='-DONECOL-',
                       size=(720, 500), expand_x=True,
                       element_justification='center',
                       scrollable=True, vertical_scroll_only=True)]],
                    element_justification='center',
                    key='-TOOLSTAB-'
                    ),
            ],
            [
                sg.Frame(
                    'Message',
                    [[sg.Text('', key='-INFO-', font=f'Courier {sg.DEFAULT_FONT[1]}', size=80)]],
                    expand_x=True,
                    font=f'_ {round(sg.DEFAULT_FONT[1] * 0.7)}'
                )
            ]
        ],
        key='-MAINGROUP-'
        )
    ]]
    return layout


def _start_gui_tool(window: sg.Window, filename: str):
    argv = gui_tool_argv(Path(__file__).resolve().parent / filename)
    return window.start_thread(lambda: launch_gui_tool(argv), '-EXTERNAL-')


def run_ribbon_diagrams(window: sg.Window):
    return _start_gui_tool(window, 'ribbon_diagrams.py')


def run_vehicle_counts(window: sg.Window):
    return _start_gui_tool(window, 'vehicle_counts.py')


def run_pt_counts(window: sg.Window):
    return _start_gui_tool(window, 'pt_counts.py')


def run_decay_diagrams(window: sg.Window):
    return _start_gui_tool(window, 'decay_diagrams.py')


def run_results(window: sg.Window):
    return _start_gui_tool(window, 'results.py')


def update_progress(
        window: sg.Window,
        config=None,
        operation: Optional[str] = None
):
    if config is None or operation is None:
        return

    if operation == 'population':
        try:
            with open(
                    Path(CACHE_SETTINGS_PATH) / 'population/agents.progress',
                    mode='r'
            ) as ap:
                ccount = max(float(dig.strip()) for dig in ap.readlines())
        except (OSError, ValueError):
            window['-POPPROGR-'].update(current_count=0)
            return
        window['-POPPROGR-'].update(current_count=ccount)
        window['-POPPROGRTS-'].update(dt.now())
    elif operation == 'model':
        config_path = config.stages['model']['config_path']
        try:
            ccount = get_matsim_progress_from_config(
                config_path=config_path
            )
        except Exception:
            return
        window['-MODELPROGR-'].update(current_count=ccount)
        window['-MODELPROGRTS-'].update(dt.now())


def get_main_window(
        populated: bool = True
) -> sg.Window:
    ensure_pysimplegui_tcl_compat(sg)
    layout = get_full_layout()
    window = sg.Window(f'kammat {version}', layout, finalize=True)
    if populated:
        restore_settings(window, APP_NAME)
    control_disabled(window, keys_list=USEPOP_KEYS,
                     disabled=not window['-USEPOP-'].get())
    control_disabled(window, keys_list=USENET_KEYS,
                     disabled=not window['-USENET-'].get())
    control_disabled(window, keys_list=['-UTURNS-'],
                     disabled=window['-NETCEDA-'].get())
    control_disabled(window, keys_list=['-SIMPLEINT-'],
                     disabled=not window['-NETCEDA-'].get())
    sg.cprint_set_output_destination(window, '-CONSOLE-')
    return window


def _apply_pipeline_updates(window, updates):
    first_issue = None
    for update in updates:
        issue = apply_run_update(window, update)
        if issue is not None:
            if first_issue is None:
                first_issue = issue
            fallback = issue_update(issue)
            try:
                for record in fallback.console_records:
                    window['-CONSOLE-'].print(record.text, text_color='firebrick1')
            except Exception:
                pass
    return first_issue


def main():
    """
    Info.
    """
    window = get_main_window(populated=True)

    newnum = format_large_number(window['-DBFLUSH-'].widget.get())
    window['-DBFLUSHLAB-'].update(newnum + ' rows')

    controller = GuiRunController()
    active_config = None

    try:
        while True:
            event, values = window.read(timeout=60000)  # update every minute
            if event == sg.WINDOW_CLOSED:
                if controller.active:
                    _apply_pipeline_updates(window, (controller.request_close(),))
                    continue
                break
            window['-INFO-'].update(value='', text_color='black')
            save_settings(window, APP_NAME)
            if event == '-TS-':
                ts = str(dt.now().replace(microsecond=0))
                ts_str = ts.replace('-', '_').replace(':', '-').replace(' ', '_')
                window['-WDPATH-'].update(ts_str + '_' + values['-WDPATH-'])
            if event in ['-PARENTPATH-', '-WDPATH-', '-TS-']:
                wd = Path(values['-PARENTPATH-']).resolve() / window['-WDPATH-'].get()
                wd_str = str(wd)
                window['-WDPREV-'].update(
                    wd_str if len(wd_str) <= 60 else '...' + wd_str[-57:]
                )
                window['-WDPREV-'].set_tooltip(wd_str)
                window.refresh()
            if event == '-RUN-':
                if controller.active:
                    issue, _ = controller.begin(controller.plan, False)
                    if issue is not None:
                        _apply_pipeline_updates(window, (issue_update(issue),))
                    continue
                config, plan, issues = prepare_main_gui_plan(values)
                _apply_pipeline_updates(window, (issues_update(issues),))
                if config is None or plan is None or has_errors(issues):
                    continue
                persistence_issue = persist_main_gui_plan(
                    config,
                    plan,
                    lambda path: save_settings(
                        window, APP_NAME, path=path
                    ),
                )
                if persistence_issue is not None:
                    _apply_pipeline_updates(
                        window, (issue_update(persistence_issue),)
                    )
                    continue
                issue, update = controller.begin(plan, bool(values['-NOGUI-']))
                if issue is not None or update is None:
                    if issue is not None:
                        _apply_pipeline_updates(window, (issue_update(issue),))
                    continue
                session = controller.session
                if session is None:
                    continue
                active_config = config
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
                    active_config = None
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
                if not isinstance(envelope, GuiRunEventEnvelope):
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
                        active_config = None
                    else:
                        _apply_pipeline_updates(
                            window, (issue_update(envelope_issue),)
                        )
                else:
                    _apply_pipeline_updates(
                        window, controller.accept_event(envelope)
                    )
            if event == PIPELINE_DONE_KEY:
                completion = values[event]
                close_requested = bool(
                    controller.state is not None
                    and controller.state.close_requested
                )
                if not isinstance(completion, GuiRunCompletion):
                    session = controller.session
                    if session is not None:
                        completion = GuiRunCompletion(
                            session.identifier,
                            controller.state.last_sequence,
                            issue=gui_issue(
                                'KAM-GUI-E103',
                                'completion',
                                'pipeline completion has the wrong type',
                            ),
                        )
                if isinstance(completion, GuiRunCompletion):
                    _apply_pipeline_updates(
                        window, controller.accept_completion(completion)
                    )
                    if not controller.active:
                        active_config = None
                    if close_requested and not controller.active:
                        return
            if '-LOADS-' in event:
                filename = sg.popup_get_file(
                    message='Save window settings',
                    no_window=True,
                    default_path=f'{APP_NAME}_settings',
                    keep_on_top=True,
                    file_types=(("PySimpleGUI settings", "*.sg"),)
                )
                if filename:
                    p = Path(filename)
                    if p.exists() and p.is_file() and p.suffix == '.sg':
                        restore_settings(window, path=filename)
                    else:
                        window['-INFO-'].update(
                            value='Wrong settings path', text_color='firebrick1'
                        )
            if '-SAVES-' in event:
                filename = sg.popup_get_file(
                    message='Save window settings', save_as=True,
                    no_window=True,
                    default_path=f'{APP_NAME}_settings',
                    keep_on_top=True,
                    file_types=(("PySimpleGUI settings", "*.sg"),)
                )
                if filename:
                    p = Path(filename)
                    if p.parent.exists() and p.suffix == '.sg':
                        save_settings(window, path=filename)
                    else:
                        window['-INFO-'].update(
                            value='Wrong settings path', text_color='firebrick1'
                        )
            if '-RESTS-' in event:
                if controller.active:
                    _apply_pipeline_updates(window, (issue_update(gui_issue(
                        'KAM-GUI-E100',
                        'window.reset',
                        'window reset is unavailable while a run is active',
                    )),))
                    continue
                resp = sg.popup_yes_no('Reset all settings?')
                if resp == 'Yes':
                    window.close()
                    window = get_main_window(populated=False)
                    controller = GuiRunController()
                    active_config = None
            if '-ABOUT-' in event:
                about_popup(window)
            if event == '-USEPOP-':
                control_disabled(window, keys_list=USEPOP_KEYS,
                                 disabled=not values['-USEPOP-'])
            if event == '-USENET-':
                control_disabled(window, keys_list=USENET_KEYS,
                                 disabled=not values['-USENET-'])
            if event in ['-NETCEDA-', '-NETGEN-']:
                control_disabled(window, keys_list=['-UTURNS-'],
                                 disabled=values['-NETCEDA-'])
                control_disabled(window, keys_list=['-SIMPLEINT-'],
                                 disabled=not values['-NETCEDA-'])
            if event == '-RIBDIAGS-':
                run_ribbon_diagrams(window)
            if event == '-VEHCOUNTS-':
                run_vehicle_counts(window)
            if event == '-PTCOUNTS-':
                run_pt_counts(window)
            if event == '-DECAYDIAGS-':
                run_decay_diagrams(window)
            if event == '-RESANAL-':
                run_results(window)
            if '-SAVEL-' in event:
                filename = sg.popup_get_file(
                    message='Save console output (log)',
                    save_as=True,
                    no_window=True,
                    default_path=f'log',
                    keep_on_top=True,
                    file_types=(("Log file", "*.txt"),)
                )
                if filename:
                    p = Path(filename)
                    if p.parent.exists():
                        dump_log(window, path=filename)
                    else:
                        window['-INFO-'].update(
                            value='Wrong log save path', text_color='firebrick1'
                        )
            if '-CSEL-' in event:
                dump_log(window, clipboard=True, selection=True)
            if '-CALL-' in event:
                dump_log(window, clipboard=True, selection=False)
            if controller.active and controller.state is not None:
                update_progress(
                    window=window,
                    config=active_config,
                    operation=controller.state.current_stage
                )
            if '-DBFLUSH-' in event:
                newnum = format_large_number(values['-DBFLUSH-'])
                window['-DBFLUSHLAB-'].update(newnum + ' rows')
        window.close()
    except Exception as error:
        sg.popup_error(
            "kammat's GUI has crashed ({0})".format(type(error).__name__)
        )
        dump_log(window)


if __name__ == '__main__':
    main()
