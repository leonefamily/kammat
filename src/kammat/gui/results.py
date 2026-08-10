# -*- coding: utf-8 -*-
"""
Created on Mon Mar  6 16:58:57 2023

@author: dgrishchuk
"""

import re
import json
import inspect
import threading
from pathlib import Path
import PySimpleGUI as sg
from typing import Union, Dict, Any
from kammat.gui.utils import (
    control_disabled, prepare_command, run_subprocess
    )
from kammat.defaults.constants import PathPointer

sg.theme('default1')


def filter_keys(
        values: Dict[str, Any]
        ):
    ret_keys = [
        k.split('|')[0] for k, v in values.items() if '|launch|' in k and v        
        ]
    vvs = {
        k: {} for k in ret_keys
        }

    for ret_key in ret_keys:
        for key, val in values.items():
            if key.startswith(ret_key):
                matches = re.search(r'\((.*?)\)', key)
                if matches:
                    key_name = re.sub(r'\(|\)', '', matches.group(0))
                    if len(val.strip()) > 0:
                        vvs[ret_key][key_name] = val
    return vvs


def generate_analysis_layout(
        settings_json: Dict[str, Union[int, float, str, bool]]
        ):
    inner_layout = []
    for key, content in settings_json.items():
        if key not in ['gis', 'analysis', 'comparison']:
            continue
        layout_row = []
        for content_key, value in content.items():
            if content_key == 'launch':
                continue
            layout_row.append(
                [sg.Text(content_key, size=30, key=f'{key}[{content_key}]'),
                 sg.Input(
                     default_text=value,
                     size=50,
                     key=f'{key}({content_key})',
                     # metadata=type(value) if value is not None else None
                     ),
                 sg.FileBrowse()
                 ]
                )
        layout_row.insert(
            0,
            [sg.Checkbox(
                 'launch',
                 key=f'{key}|launch|',
                 default=content['launch'] if 'launch' in content else False
                 )
             ]
            )
        inner_layout.append(
            [sg.Frame(key, layout_row)]
            )

    col = sg.Column(
        inner_layout,
        key='-INPUTCOL-',
        size=(720, 500),
        scrollable=True,
        vertical_scroll_only=True
        )
    sub_window = sg.Window('Values', [[col], [sg.Button('Run', key='-RUN-')]])
    vvs = {}
    while True:
        event, values = sub_window.read()
        if event == sg.WINDOW_CLOSED:
            break
        elif event == '-RUN-':
            vvs = filter_keys(values)
            break
    sub_window.close()
    return vvs


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
    command = f'"{vvs["gis"]["qgis_path"]}" "{script_path}" ' + ' '.join([
        f'--{k.replace("_", "-")} "{v}"'
        for k, v in vvs['gis'].items()
        if k not in ['launch', 'qgis_path']
    ])
    if not gui:
        return run_subprocess(command)
    t = window.start_thread(
        lambda: run_subprocess(command), '-GIS_THREAD-'
    )
    return t


def main():

    functions = {
        "analysis": run_analysis,
        "comparison": run_comparison,
        "gis": run_gis
    }

    layout = [
        [sg.Text('Load settings JSON', size=20),
         sg.Input(key='-JSON-', size=50),
         sg.FileBrowse(key='-LOAD-')],
        [sg.Button('Change JSON', key='-CHANGE-'),
         sg.Button('Run', key='-RUN-')],
        [sg.Output(key='-CONSOLE-', size=(25, 20),
                    expand_x=True,
                    echo_stdout_stderr=True)]
        ]
    window = sg.Window('Analysis', layout)
    sg.cprint_set_output_destination(window, '-CONSOLE-')

    results = {}
    vvs = {}
    operation = None
    is_running = False

    while True:
        event, values = window.read()
        if event == '-CHANGE-':
            with open(values['-JSON-']) as f:
                settings_json = json.load(f)
            vvs = generate_analysis_layout(settings_json)
        elif event == '-RUN-' or re.search('-\S+_THREAD-', event):
            if event == '-RUN-' and not is_running:
                stages = list(vvs.keys())
                control_disabled(window, keys_list=['-RUN-'], disabled=True)
            else:
                sg.cprint(f'{operation.capitalize()} finished', text_color='green')
                results[operation] = values[event]
                if values[event] != 0:
                    stages = []
                    sg.cprint(f'Process {operation} returned error code {values[event]}',
                              text_color='firebrick1')
                # operation = re.sub('(-|_THREAD-)', '', event).lower()
            if stages:
                operation = stages.pop(0)
                sg.cprint(f'{operation.capitalize()} started', text_color='green')
                t = functions[operation](window, vvs)
                is_running = True
            else:
                is_running = False
                sg.cprint('All finished', text_color='green')
                control_disabled(window, keys_list=['-RUN-'], disabled=False)
    window.close()


if __name__ == '__main__':
    main()
