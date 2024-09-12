# -*- coding: utf-8 -*-
"""
Created on Mon Feb 27 11:03:48 2023

@author: dgrishchuk
"""
import os
import re
import sys
import json
import logging
import inspect
import textwrap
import threading
import webbrowser
from pathlib import Path
from datetime import datetime as dt
from typing import List, Dict, Union, Any, Tuple, Optional, Callable

from kammat.model.utils import get_matsim_version, get_matsim_runnable_class
from kammat import __version__ as version
from kammat.model.utils import suggest_matsim_ram_limit
from kammat.gui.utils import (
    save_settings, restore_settings, run_subprocess, control_disabled, dump_log
)
from kammat.defaults.constants import (
    LOGGER_FORMAT, CACHE_SETTINGS_PATH, PathPointer
)
from kammat.input.network.generic import prepare_generic_network
from kammat.input.network.ceda import prepare_ceda_network
from kammat.input.population.load import handle_population
from kammat.model.run import get_matsim_progress_from_config

import PySimpleGUI as sg

sg.theme('default1')

INTERPRETER = f'"{sys.executable}"'
APP_NAME = 'main'
GIT_LINK = 'https://github.com/leonefamily/kammat'
BOLD_FONT = (' '.join(str(t) for t in sg.DEFAULT_FONT) + ' bold')
SUGG_RAM_LIMIT = int(suggest_matsim_ram_limit().replace('m', ''))
MAX_RAM_LIMIT = int(
    suggest_matsim_ram_limit(max_fraction=1, min_free_ram=0).replace('m', '')
)
OPERATIONS_ORDER = ['network', 'pt', 'population', 'config',
                    'model', 'analysis', 'comparison', 'gis']
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


def serialize_helper(
        val: Any
):
    if isinstance(val, Path):
        return str(val)
    raise TypeError(
        f'Object of type {type(val)} is not JSON serializable'
    )


def dump_run_settings(
        values: Dict[str, Union[str, int, float]],
        path: Union[str, Path]
):
    with open(path, mode='w', encoding='utf-8') as f:
        json.dump(values, f, indent=4, default=serialize_helper)


def load_run_settings(
        path: Union[str, Path]
) -> Dict[str, Dict[str, Union[str, int, float]]]:
    with open(path, mode='r', encoding='utf-8') as f:
        lvalues = json.load(f)
    return lvalues


def about_popup(
        window: sg.Window
):
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
    awindow = sg.Window('About MMDMS', alayout, finalize=True)

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


def check_validity(
        window: sg.Window,
        values: Dict[str, Union[str, int, float]]
) -> Tuple[Dict[str, Dict[str, Union[str, int, float]]], Dict[str, List[str]]]:
    msgs = {
        'info': [],
        'warning': [],
        'error': []
    }

    vvs = {  # valid values
        'wd': {},
        'network': {},
        'pt': {},
        'population': {},
        'config': {},
        'model': {},
        'analysis': {},
        'comparison': {},
        'gis': {}
    }

    # Working directories
    wd = Path(values['-PARENTPATH-']).resolve() / window['-WDPATH-'].get()
    vvs['wd']['root'] = wd
    wd_net = wd / 'network'
    wd.mkdir(exist_ok=True)
    wd_net.mkdir(exist_ok=True)

    wd_population = wd / 'population'
    vvs['wd']['model'] = wd_population
    wd_population.mkdir(exist_ok=True)

    run_dir = wd / 'model'
    vvs['wd']['model'] = run_dir
    run_dir.mkdir(exist_ok=True)

    an_dir = wd / 'analysis'
    vvs['wd']['analysis'] = an_dir
    an_dir.mkdir(exist_ok=True)

    rd_dir = an_dir / 'nodes'  # ribbon diagrams
    vvs['wd']['nodes'] = rd_dir
    rd_dir.mkdir(exist_ok=True)

    lnk_dir = an_dir / 'links'  # link diagrams
    rl_dir = lnk_dir / 'road'
    ptl_dir = lnk_dir / 'pt'
    vvs['wd']['links'] = lnk_dir
    vvs['wd']['road_links'] = rl_dir
    vvs['wd']['pt_links'] = ptl_dir
    lnk_dir.mkdir(exist_ok=True)
    rl_dir.mkdir(exist_ok=True)
    ptl_dir.mkdir(exist_ok=True)

    comp_dir = wd / 'comparison'
    vvs['wd']['comparison'] = comp_dir
    comp_dir.mkdir(exist_ok=True)

    # Network
    net_keys = set(
        inspect.getargs(prepare_generic_network.__code__).args +
        inspect.getargs(prepare_ceda_network.__code__).args
    )
    if values['-USENET-']:
        enet = Path(values['-ENETPATH-'])
        try:
            nvvs = load_run_settings(enet.parent.parent / 'settings.json')
            # TODO: check correctness
            for key, value in nvvs['network'].items():
                vvs['network'][key] = value
            msgs['info'].append('Using existing network')
        except FileNotFoundError:
            msgs['warning'].append(
                'Using existing network, but the structure of files does not '
                'seem to correspond with this framework. Continuing anyways, '
                'but some analyses will not be possible - e.g. merging with '
                'original shapefile, intensities comparison etc.'
            )
            for key in net_keys:
                vvs['network'][key] = None
        vvs['network']['net_save_path'] = enet
        vvs['network']['lane_definitions_save_path'] = values['-ELDEFPATH-']
        vvs['network']['existing'] = True
        vvs['network']['launch'] = False
    else:
        vvs['network']['shp_path'] = Path(values['-NETPATH-'])
        vvs['network']['nettype'] = 'generic' if values['-NETGEN-'] else 'ceda'
        if vvs['network']['nettype'] == 'generic':
            vvs['network']['restrict_uturns'] = values['-UTURNS-']
        elif vvs['network']['nettype'] == 'ceda':
            vvs['network']['ncores'] = int(values['-THREADS-'])
            if values['-LCONPATH-']:
                vvs['network']['lane_connections_path'] = values['-LCONPATH-']
                vvs['network']['lane_definitions_save_path'] = wd_net / 'lane_definitions.xml'
            else:
                vvs['network']['lane_connections_path'] = None
                vvs['network']['lane_definitions_save_path'] = None
            vvs['network']['internal_maneuvers'] = values['-SIMPLEINT-']
        vvs['network']['edges_save_path'] = wd_net / 'edges.shp'
        vvs['network']['nodes_save_path'] = wd_net / 'nodes.shp'
        vvs['network']['net_save_path'] = wd_net / 'net.xml'

        vvs['network']['existing'] = False
        vvs['network']['launch'] = True

    # Public transport, schedules, vehicles
    if values['-GTFSPATH-'] and not values['-USENET-']:
        vvs['pt']['gtfs_folder'] = values['-GTFSPATH-']
        vvs['pt']['output_schedule_path'] = wd_net / 'schedule.xml'
        vvs['pt']['output_vehicles_path'] = wd_net / 'vehicles.xml'
    else:
        msgs['info'].append('Using existing schedule and vehicles')
        vvs['pt']['gtfs_folder'] = None
        if values['-USENET-']:
            vvs['pt']['output_schedule_path'] = values['-ESCHEDPATH-']
            vvs['pt']['output_vehicles_path'] = values['-EVEHSPATH-']
        else:
            vvs['pt']['output_schedule_path'] = None
            vvs['pt']['output_vehicles_path'] = None
    vvs['pt']['number_of_threads'] = int(values['-THREADS-'])
    vvs['pt']['net_path'] = vvs['network']['net_save_path']
    vvs['pt']['output_net_path'] = vvs['network']['net_save_path']

    # Population
    pop_keys = inspect.getargs(handle_population.__code__).args
    if values['-USEPOP-']:
        epop = Path(values['-EPOPPATH-'])
        try:
            pvvs = load_run_settings(epop.parent.parent / 'settings.json')
            for key, value in pvvs['population'].items():
                vvs['population'][key] = value
            msgs['info'].append('Using existing population')
        except FileNotFoundError:
            msgs['warning'].append(
                'Using existing population, but the structure of files does not '
                'seem to correspond with this framework. Continuing anyways, '
                'but some analyses will not be possible - e.g. merging with '
                'original shapefile, intensities comparison etc.'
            )
            for key in pop_keys:
                vvs['population'][key] = None
        vvs['population']['xml_path'] = epop
        vvs['population']['existing'] = True
        vvs['population']['launch'] = False
    else:
        vvs['population']['launch'] = True
        vvs['population']['existing'] = False
        vvs['population']['include_teleported'] = values['-WRITETP-']
        vvs['population']['xml_path'] = wd_population / 'population.xml.gz'
        vvs['population']['csv_path'] = None # wd_population / 'population.csv'
        vvs['population']['pickle_path'] = wd_population / 'population.zx'
        vvs['population']['facilities_path'] = values['-POPPATH-']
        vvs['population']['categories_path'] = values['-CATPATH-']
        vvs['population']['diaries_path'] = values['-DIARPATH-']
        vvs['population']['distances_path'] = values['-DISTPATH-']
        vvs['population']['clusters_path'] = values['-CLUSTPATH-']
        vvs['population']['citylog_points_path'] = values['-CLOGSPATH-']
        vvs['population']['freight_points_path'] = values['-FREPATH-']
        vvs['population']['transit_points_path'] = values['-TRANPATH-']
        vvs['population']['staying_path'] = values['-STAYPATH-']
        vvs['population']['target_probabilities_path'] = values['-TARGPATH-']
        vvs['population']['time_courses_path'] = values['-TCOURPATH-']
        vvs['population']['city_logistics_path'] = values['-CLOGPATH-']
        vvs['population']['times_path'] = values['-TIMEPATH-']
        vvs['population']['modal_split_path'] = values['-MSPATH-']
        vvs['population']['indices_path'] = values['-INDPATH-']
        vvs['population']['relations_path'] = values['-RELPATH-']
        vvs['population']['stops_path'] = values['-STOPPATH-']
        vvs['population']['sample'] = values['-POPFRAC-']
        vvs['population']['modal_split_save_path'] = wd_population / 'modal_split.csv'
        vvs['population']['facilities_counts_save_path'] = wd_population / 'facilities_counts.shp'
        vvs['population']['relational_matrices_save_directory'] = wd_population / 'relations'
    vvs['population']['ncores'] = int(values['-THREADS-'])

    # Configuration
    vvs['config']['net_path'] = vvs['network']['net_save_path']
    vvs['config']['population_path'] = vvs['population']['xml_path']
    vvs['config']['number_of_threads'] = int(values['-THREADS-'])
    vvs['config']['last_iteration'] = int(values['-ITERS-'] - 1)
    vvs['config']['output_config_path'] = wd / 'config.xml'
    vvs['config']['matsim_output_directory'] = run_dir
    vvs['config']['schedule_path'] = vvs['pt']['output_schedule_path']
    vvs['config']['vehicles_path'] = vvs['pt']['output_vehicles_path']
    vvs['config']['lane_definitions_path'] = (
        vvs['network']['lane_definitions_save_path']
        if 'lane_definitions_save_path' in vvs['network'] else None
    )
    vvs['config']['write_events_interval'] = vvs['config']['last_iteration']
    vvs['config']['disable_innovations_after_fraction'] = values['-MUTFRAC-']
    vvs['config']['mutation_range'] = values['-TIMEMUT-'] * 60
    vvs['config']['scoring_parameters_path'] = (
        values['-SCPARSPATH-'] if values['-SCPARSPATH-'].strip() != '' else
        None
    )
    vvs['config']['minibus_parameters_path'] = (
        values['-PPARSPATH-'] if values['-PPARSPATH-'].strip() != '' else
        None
    )
    vvs['config']['launch'] = True

    # Model
    vvs['model']['launch'] = values['-RUNMOD-']
    vvs['model']['executable_path'] = values['-MATSIMPATH-']
    vvs['model']['config_path'] = vvs['config']['output_config_path']
    vvs['model']['ram_limit'] = f"{int(values['-MATSIMRAM-'])}m"
    vvs['model']['custom_class'] = (
        values['-CCLASS-'] if values['-CCLASS-'].strip() != '' else
        None
    )

    # Analysis
    vvs['analysis']['launch'] = values['-ANALYZE-'] if values['-RUNMOD-'] else False
    vvs['analysis']['events_path'] = vvs['config']['matsim_output_directory'] / 'output_events.xml.gz'
    vvs['analysis']['net_path'] = vvs['config']['matsim_output_directory'] / 'output_network.xml.gz'
    vvs['analysis']['legs_path'] = vvs['config']['matsim_output_directory'] / 'output_legs.csv.gz'
    vvs['analysis']['output_transfers_path'] = an_dir / 'transfers.csv.gz'
    vvs['analysis']['output_counts_path'] = an_dir / 'counts.json.gz'
    vvs['analysis']['output_turns_path'] = an_dir / 'turns.json.gz'
    vvs['analysis']['output_net_counts_path'] = an_dir / 'counts.shp'
    vvs['analysis']['schedule_path'] = run_dir / 'output_transitSchedule.xml.gz'
    vvs['analysis']['output_pt_counts_path'] = an_dir / 'pt.json.gz'
    vvs['analysis']['output_pt_net_counts_path'] = an_dir / 'pt.shp'
    vvs['analysis']['output_pt_stops_counts_path'] = an_dir / 'pt_stops.shp'
    vvs['analysis']['links_nodes_groups'] = values['-LINKGROUPS-'] if values['-LINKGROUPS-'] else None
    vvs['analysis']['output_ribbon_diagrams_directory'] = rd_dir
    vvs['analysis']['road_links_ids'] = values['-LINKINTENS-'] if values['-LINKINTENS-'] else None
    vvs['analysis']['output_road_links_intensities_directory'] = rl_dir
    vvs['analysis']['pt_links_ids'] = values['-PTLINKINTENS-'] if values['-PTLINKINTENS-'] else None
    vvs['analysis']['output_pt_links_intensities_directory'] = ptl_dir
    vvs['analysis']['output_pt_lines_intensities_directory'] = ptl_dir
    vvs['analysis']['pt_lines_ids'] = values['-PTLINEINTENS-'] if values['-LINKGROUPS-'] else None
    vvs['analysis']['cordon_poly_path'] = values['-CORDPOLYPATH-'] if values['-CORDPOLYPATH-'] else None
    vvs['analysis']['output_cordon_stats_path'] = an_dir / 'cordons_stats.shp'
    vvs['analysis']['volume_poly_path'] = values['-VOLPOLYPATH-'] if values['-VOLPOLYPATH-'] else None
    vvs['analysis']['output_volume_stats_path'] = an_dir / 'volume_stats.shp'

    # Comparison
    vvs['comparison']['launch'] = values['-COMPARE-'] if values['-ANALYZE-'] else False
    vvs['comparison']['orig_net_path'] = vvs['network']['shp_path']
    vvs['comparison']['edge_net_path'] = vvs['network']['edges_save_path']
    vvs['comparison']['net_counts_path'] = vvs['analysis']['output_net_counts_path']
    vvs['comparison']['network_intensities_path'] = values['-NINTPATH-'] if values['-NINTPATH-'] else None
    vvs['comparison']['network_differences_save_path'] = comp_dir / 'network_differences.shp'
    vvs['comparison']['network_differences_stats_save_path'] = comp_dir / 'network_differences.csv'
    vvs['comparison']['intersection_intensities_path'] = values['-IINTPATH-'] if values['-IINTPATH-'] else None
    vvs['comparison']['intersection_differences_save_path'] = comp_dir / 'intersection_differences.shp'
    vvs['comparison']['intersection_differences_stats_save_path'] = comp_dir / 'intersection_differences.csv'
    vvs['comparison']['difference_thresh'] = 0.25
    vvs['comparison']['diff_net_counts_save_path'] = comp_dir / 'prev_model_network_differences.shp'
    vvs['comparison']['diff_pt_net_counts_save_path'] = comp_dir / 'prev_model_pt_network_differences.shp'
    vvs['comparison']['diff_pt_stops_counts_save_path'] = comp_dir / 'prev_model_pt_stops_differences.shp'
    pmod = Path(values['-PMODPATH-'])
    try:
        cvvs = load_run_settings(pmod / 'settings.json')
        vvs['comparison']['prev_net_counts_path'] = cvvs['analysis']['output_net_counts_path']
        vvs['comparison']['prev_pt_net_counts_path'] = cvvs['analysis']['output_pt_net_counts_path']
        vvs['comparison']['prev_pt_stops_counts_path'] = cvvs['analysis']['output_pt_stops_counts_path']
        vvs['comparison']['pt_net_counts_path'] = vvs['analysis']['output_pt_net_counts_path']
        vvs['comparison']['pt_stops_counts_path'] = vvs['analysis']['output_pt_stops_counts_path']
    except FileNotFoundError:
        msgs['warning'].append(
            'Using existing population, but the structure of files does not '
            'seem to correspond with this framework. Continuing anyways, '
            'but some analyses will not be possible - e.g. merging with '
            'original shapefile, intensities comparison etc.'
        )
        vvs['comparison']['prev_net_counts_path'] = None
        vvs['comparison']['prev_pt_net_counts_path'] = None
        vvs['comparison']['prev_pt_stops_counts_path'] = None
    vvs['comparison']['pt_net_counts_path'] = vvs['analysis']['output_pt_net_counts_path']
    vvs['comparison']['pt_stops_counts_path'] = vvs['analysis']['output_pt_stops_counts_path']

    # GIS project
    vvs['gis']['launch'] = values['-QGIS-']
    vvs['gis']['qgis_path'] = values['-QGISPATH-']
    vvs['gis']['project_path'] = wd / 'view.qgs'
    vvs['gis']['input_facilities'] = vvs['population']['facilities_counts_save_path']
    vvs['gis']['input_edges'] = vvs['network']['edges_save_path']
    vvs['gis']['input_nodes'] = vvs['network']['nodes_save_path']
    vvs['gis']['output_road_counts'] = vvs['analysis']['output_net_counts_path']
    vvs['gis']['output_pt_counts'] = vvs['analysis']['output_pt_net_counts_path']
    vvs['gis']['output_pt_stops'] = vvs['analysis']['output_pt_stops_counts_path']
    vvs['gis']['output_cordons_stats'] = vvs['analysis']['output_cordon_stats_path']
    vvs['gis']['output_volumes_stats'] = vvs['analysis']['output_volume_stats_path']
    vvs['gis']['comparison_rw_road_diffs'] = vvs['comparison']['network_differences_save_path']
    vvs['gis']['comparison_rw_road_intersection_diffs'] = vvs['comparison']['intersection_differences_save_path']

    return vvs, msgs


def run_network(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle network preparation.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    vvs_n = {k: v for k, v in vvs['network'].items() if k not in ['existing', 'nettype']}
    if vvs['network']['nettype'] == 'ceda':
        script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/network/ceda.py'
    elif vvs['network']['nettype'] == 'generic':
        script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/network/generic.py'
    command = prepare_command(vvs_n, script_path)
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command),
        '-NETWORK_THREAD-'
    )
    return t


def run_pt(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle pt preparation.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/network/pt.py'
    command = prepare_command(vvs['pt'], script_path)
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(lambda: run_subprocess(command), '-PT_THREAD-')
    return t


def prepare_command(
        vvs_x: Dict[str, Union[str, int, float]],
        script_path: Union[str, Path],
        interpreter_path: str = INTERPRETER
) -> str:
    commands_list = []
    for k, v in vvs_x.items():
        if k == 'launch':
            continue
        if v is None:
            continue
        elif isinstance(v, bool):
            if v:
                commands_list.append(f'--{k.replace("_", "-")}')
        elif isinstance(v, (int, float)):
            commands_list.append(f'--{k.replace("_", "-")} {v}')
        else:
            commands_list.append(f'--{k.replace("_", "-")} "{v}"')
    command = f'{interpreter_path} "{script_path}" ' + ' '.join(commands_list)
    return command


def run_population(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle population preparation.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    vvs_p = {
        k: v for k, v in vvs['population'].items()
        if k not in ['existing'] and v is not None and
        (True if isinstance(v, bool) and not v else True)
    }
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/population/load.py'
    command = prepare_command(vvs_p, script_path)
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command), '-POPULATION_THREAD-'
    )
    return t


def run_config(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle config preparation.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'model/config.py'
    command = prepare_command(vvs['config'], script_path)
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command), '-CONFIG_THREAD-'
    )
    return t


def run_model(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle model run.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    if 'custom_class' in vvs['model'] and vvs['model']['custom_class']:
        cl = vvs['model']['custom_class']
    else:
        ver = get_matsim_version(
            matsim_executable=vvs["model"]["executable_path"]
        )
        cl = get_matsim_runnable_class(matsim_version=ver)  # class to run
    command = (
        f'java -cp "{vvs["model"]["executable_path"]}" '
        f'-Xmx{vvs["model"]["ram_limit"]} '
        f'{cl} "{vvs["model"]["config_path"]}"'
    )
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command), '-MODEL_THREAD-'
    )
    return t


def run_analysis(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle analyses.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    vvs_a = {
        k: v for k, v in vvs['analysis'].items() if k not in ['launch']
    }
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'output/analysis.py'
    command = prepare_command(vvs_a, script_path)
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command), '-ANALYSIS_THREAD-'
    )
    return t


def run_comparison(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle comparison.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'output/comparison.py'
    vvs_c = {
        k: v for k, v in vvs['comparison'].items() if k not in ['launch']
    }
    command = prepare_command(vvs_c, script_path)
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command), '-COMPARISON_THREAD-'
    )
    return t


def run_gis(
        window: sg.Window = None,
        vvs: Dict[str, Dict[str, Union[str, int, float]]] = None,
        gui: bool = True
) -> Union[threading.Thread, int]:
    """
    Send command to handle GIS visualization.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'output/gis/qgis_project.py'
    params = ' '.join([
        f'--{k.replace("_", "-")} "{v}"'
        for k, v in vvs['gis'].items()
        if k not in ['launch', 'qgis_path']
    ])
    if sys.platform.lower() == 'linux':
        command = (
            'export PYTHONPATH="$PYTHONPATH:/usr/share/qgis/python/plugins:/usr/share/qgis/python"; '
            f'python3 "{script_path}" ' + params
        )
    else:
        command = f'"{vvs["gis"]["qgis_path"]}" "{script_path}" ' + params
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command), '-GIS_THREAD-'
    )
    return t


def run_ribbon_diagrams(
        window: sg.Window
) -> threading.Thread:
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'gui/ribbon_diagrams.py'
    command = prepare_command({}, script_path)
    t = window.start_thread(
        lambda: run_subprocess(command), '-EXTERNAL-'
    )
    return t


def run_vehicle_counts(
        window: sg.Window
) -> threading.Thread:
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'gui/vehicle_counts.py'
    command = prepare_command({}, script_path)
    t = window.start_thread(
        lambda: run_subprocess(command), '-EXTERNAL-'
    )
    return t


def run_pt_counts(
        window: sg.Window
) -> threading.Thread:
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'gui/pt_counts.py'
    command = prepare_command({}, script_path)
    t = window.start_thread(
        lambda: run_subprocess(command), '-EXTERNAL-'
    )
    return t


def run_results(
        window: sg.Window
) -> threading.Thread:
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'gui/results.py'
    command = prepare_command({}, script_path)
    t = window.start_thread(
        lambda: run_subprocess(command), '-EXTERNAL-'
    )
    return t


def update_progress(
        window: sg.Window,
        vvs: Optional[Dict[str, Dict[str, Union[str, int, float]]]] = None,
        operation: Optional[str] = None
):
    if vvs is None or operation is None:
        return
    if operation == 'population':
        try:
            with open(
                    Path(CACHE_SETTINGS_PATH) / 'population/agents.progress',
                    mode='r'
            ) as ap:
                ccount = max(float(dig.strip()) for dig in ap.readlines())
                window['-POPPROGR-'].update(current_count=ccount)
                window['-POPPROGRTS-'].update(dt.now())
        except Exception:
            window['-POPPROGR-'].update(current_count=0)
    elif operation == 'model':
        ccount = get_matsim_progress_from_config(
            config_path=vvs['model']['config_path']
        )
        window['-MODELPROGR-'].update(current_count=ccount)
        window['-MODELPROGRTS-'].update(dt.now())


def get_stages(
        vvs: Dict[str, Dict[str, Union[str, int, float]]]
) -> List[str]:
    stages = OPERATIONS_ORDER[:]
    if vvs['network']['existing']:
        stages.remove('network')
    if vvs['pt']['gtfs_folder'] is None:
        stages.remove('pt')
    if vvs['population']['existing']:
        stages.remove('population')
    if not vvs['model']['launch']:
        stages.remove('model')
        stages.remove('analysis')
        stages.remove('comparison')
    if not vvs['analysis']['launch']:
        try:
            stages.remove('analysis')
        except ValueError:
            pass
    if not vvs['comparison']['launch']:
        try:
            stages.remove('comparison')
        except ValueError:
            pass
    if not vvs['gis']['launch']:
        stages.remove('gis')
    return stages


def get_stages_order(
        stages: List[str]
) -> List[int]:
    return [OPERATIONS_ORDER.index(n) for s, n in enumerate(stages)]


def handle_nogui(
        window: sg.Window,
        vvs: Dict[str, Dict[str, Union[str, int, float]]],
        stages: List[str],
        functions: Dict[str, Callable]
):
    window['-CONSOLE-'].restore_stderr()
    window['-CONSOLE-'].restore_stdout()
    window.close()
    to_print = []
    for stage in stages:
        result = functions[stage](vvs=vvs, gui=False)
        if result != 0:
            to_print.append(
                f'{stage} failed with code {result} at {dt.now()}'
            )
            break
        else:
            to_print.append(
                f'{stage} succeeded at {dt.now()}'
            )
    window = get_main_window(populated=True)
    window['-MAINGROUP-'].Widget.select(1)
    for msg in to_print:
        sg.cprint(
            msg,
            text_color='green' if 'failed' not in msg else 'firebrick1'
        )
    return window


def get_main_window(
        populated: bool = True
) -> sg.Window:
    layout = get_full_layout()
    window = sg.Window(f'MMDMS {version}', layout, finalize=True)
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


def main():
    """
    Info.
    """
    window = get_main_window(populated=True)

    functions = {
        "network": run_network,
        "pt": run_pt,
        "population": run_population,
        "config": run_config,
        "model": run_model,
        "analysis": run_analysis,
        "comparison": run_comparison,
        "gis": run_gis
    }

    results = {}
    is_running = False
    operation = None
    vvs = None
    t = None
    fnums = []

    try:
        while True:
            event, values = window.read(timeout=60000)  # update every minute
            if event == sg.WIN_CLOSED:
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
            if event == '-RUN-' or re.search('-\S+_THREAD-', event):
                if event == '-RUN-' and not is_running:
                    vvs, msgs = check_validity(window, values)
                    save_settings(window, APP_NAME, path=vvs['wd']['root'] / 'settings.sg')
                    dump_run_settings(vvs, path=vvs['wd']['root'] / 'settings.json')
                    for info in msgs['info']:
                        sg.cprint(info, text_color='black')
                    for err in msgs['error']:
                        sg.cprint(err, text_color='firebrick1')
                    if msgs['error']:
                        continue
                    stages = get_stages(vvs)
                    if values['-NOGUI-']:
                        window.close()
                        window = handle_nogui(window, vvs, stages, functions)
                        continue
                    fnums = get_stages_order(stages)
                    control_disabled(window, keys_list=['-RUN-', '-RESUME-'], disabled=True)
                    window['-MAINGROUP-'].Widget.select(1)
                else:
                    sg.cprint(f'{operation.capitalize()} finished', text_color='green')
                    results[operation] = values[event]
                    if values[event] != 0:
                        fnums = []
                        sg.cprint(f'Process {operation} returned error code {values[event]}',
                                  text_color='firebrick1')
                    # operation = re.sub('(-|_THREAD-)', '', event).lower()
                if fnums:
                    fnum = fnums.pop(0)
                    operation = OPERATIONS_ORDER[fnum]
                    sg.cprint(f'{operation.capitalize()} started', text_color='green')
                    t = functions[operation](window, vvs)
                    is_running = True
                else:
                    is_running = False
                    sg.cprint('All finished', text_color='green')
                    control_disabled(window, keys_list=['-RUN-'], disabled=False)
                    control_disabled(window, keys_list=['-PAUSE-', '-RESUME-'], disabled=True)
                    dump_log(window, path=vvs['wd']['root'] / 'log.txt')
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
                resp = sg.popup_yes_no('Reset all settings?')
                if resp == 'Yes':
                    window.close()
                    window = get_main_window(populated=False)
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
            if is_running:
                update_progress(
                    window=window,
                    vvs=vvs,
                    operation=operation
                )
        window.close()
    except Exception:
        import traceback
        sg.popup_error_with_traceback(
            "MMDMS's GUI has crashed", traceback.format_exc()
        )
        dump_log(window)


if __name__ == '__main__':
    main()