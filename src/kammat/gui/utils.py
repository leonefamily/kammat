# -*- coding: utf-8 -*-
"""
Created on Tue Feb  7 16:03:38 2023

@author: dgrishchuk
"""

import io
import shlex
import platform
import subprocess
import traceback
from pathlib import Path
import PySimpleGUI as sg
from typing import List, Union, Callable, Any, Optional, Dict
from PIL import ImageTk, Image
from matplotlib.figure import Figure
import sys
from multiprocessing import Process

from kammat.defaults.constants import (
    CACHE_SETTINGS_PATH
)
from kammat.main.configure import load_config

SETTINGS_FOLDER: Path = Path(CACHE_SETTINGS_PATH) / 'gui'
LOG_FILE: Path = Path(CACHE_SETTINGS_PATH) / 'log.txt'
INTERPRETER = f'"{sys.executable}"'


def run_process(
        function: Callable,
        kwargs: Dict[str, Any]
        ) -> Optional[Any]:
    p = Process(target=function, kwargs=kwargs)
    p.start()
    p.join()


def run_subprocess(
        command: str,
        cwd: str = None
        ):
    """
    Run subprocess, fail if any error encountered.

    Parameters
    ----------
    command : str
        Command to pass to shell
    cwd : str, optional
        Working directory for script to execute

    """
    print(command)
    p = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        shell=True
    )

    for line in p.stdout:
        try:
            string = line.decode().rstrip()
            print(string)
        except:
            print('*Problem decoding string*')
    outs = p.wait()
    return outs


def dump_log(
        window: sg.Window,
        console_key: str = '-CONSOLE-',
        selection: bool = False,
        clipboard: bool = False,
        path: Union[str, Path] = None
) -> Optional[str]:
    if path is None:
        path = LOG_FILE
    else:
        path = Path(path)
    try:
        if selection:
            log = window[console_key].Widget.selection_get()
        else:
            log = window[console_key].get()
        if clipboard:
            window.TKroot.clipboard_clear()
            window.TKroot.clipboard_append(log)
        if not path.parent.exists():
            path.parent.mkdir()
        with path.open(mode='w') as lf:
            lf.write(log)
    except Exception as e:
        print(e)


def save_settings(
        window: sg.Window,
        name: str = None,
        path: Union[str, Path] = None
):
    if path is None:
        if not SETTINGS_FOLDER.exists():
            try:
                SETTINGS_FOLDER.mkdir(parents=True)
            except Exception:
                return
        path = SETTINGS_FOLDER / (name + '.sg')
    else:
        path = Path(path)
    try:
        window.save_to_disk(path)
    except Exception as e:
        print(e)


def restore_settings(
        window: sg.Window,
        name: str = None,
        path: Union[str, Path] = None
):
    if path is None:
        path = SETTINGS_FOLDER / (name + '.sg')
    else:
        path = Path(path)
    if path.exists():
        if path.suffix == '.sg':
            try:
                window.load_from_disk(path)
            except Exception as e:
                print(e)
        elif path.suffix == '.json':
            config = load_config(p=path)
            wd = Path(config['wd']['root']).resolve()
            window_dict = {
                '-PARENTPATH-': str(wd.parent),
                '-WDPATH-': wd.name,
                '-NETPATH-': config['network']['shp_path'],
                '-ENETPATH-': config['network']['net_save_path'],
                '-ELDEFPATH-': config['network']['lane_definitions_save_path'],
                '-LCONPATH-': config['network']['lane_connections_path'],
                '-NETGEN-': config['network']['nettype'] == 'generic',
                '-UTURNS-': config['network']['restrict_uturns'],
                '-SIMPLEINT-': config['network']['internal_maneuvers'],
                '-GTFSPATH-': config['pt']['gtfs_folder'],
                '-ESCHEDPATH-': config['pt']['output_schedule_path'],
                '-EVEHSPATH-': config['pt']['output_vehicles_path'],
                '-THREADS-': config['pt']['number_of_threads'],
                '-USENET-': config['network']['existing'],
                '-USEPOP-': config['population']['existing'],
                '-EPOPPATH-': config['population']['xml_path'],
                '-VARSPATH-': config['population']['variables_path'],
                '-WRITETP-': config['population']['include_teleported'],
                '-POPPATH-': config['population']['facilities_path'],
                '-CATPATH-': config['population']['categories_path'],
                '-DIARPATH-': config['population']['diaries_path'],
                '-DISTPATH-': config['population']['distances_path'],
                '-CLUSTPATH-': config['population']['clusters_path'],
                '-CLOGSPATH-': config['population']['citylog_points_path'],
                '-FREPATH-': config['population']['freight_points_path'],
                '-TRANPATH-': config['population']['transit_points_path'],
                '-STAYPATH-': config['population']['staying_path'],
                '-TARGPATH-': config['population']['target_probabilities_path'],
                '-TCOURPATH-': config['population']['time_courses_path'],
                '-CLOGPATH-': config['population']['city_logistics_path'],
                '-TIMEPATH-': config['population']['times_path'],
                '-MSPATH-': config['population']['modal_split_path'],
                '-INDPATH-': config['population']['indices_path'],
                '-RELPATH-': config['population']['relations_path'],
                '-STOPPATH-': config['population']['stops_path'],
                '-OFLOWPATH-': config['population']['oneway_flows_path'],
                '-POPFRAC-': config['population']['sample'],
                '-INCRCAP-': config['population']['incremental_capacity_allocation_parts'],
                '-ITERS-': config['config']['last_iteration'] + 1,
                '-MUTFRAC-': config['config']['disable_innovations_after_fraction'],
                '-TIMEMUT-': int(config['config']['mutation_range']) / 60,
                '-SCPARSPATH-': config['config']['scoring_parameters_path'],
                '-PPARSPATH-': config['config']['minibus_parameters_path'],
                '-RUNMOD-': config['model']['launch'],
                '-MATSIMPATH-': config['model']['executable_path'],
                '-MATSIMRAM-': config['model']['ram_limit'].rstrip('m'),
                '-CCLASS-': config['model']['custom_class'],
                '-ANALYZE-': config['analysis']['launch'],
                '-LINKGROUPS-': config['analysis']['links_nodes_groups'],
                '-LINKINTENS-': config['analysis']['road_links_ids'],
                '-PTLINKINTENS-': config['analysis']['pt_links_ids'],
                '-PTLINEINTENS-': config['analysis']['pt_lines_ids'],
                '-CORDPOLYPATH-': config['analysis']['cordon_poly_path'],
                '-VOLPOLYPATH-': config['analysis']['volume_poly_path'],
                '-EVENTSDB-': config['analysis']['output_road_db_path'] is not None,
                '-DBFLUSH-': config['analysis']['output_road_db_flush_interval'],
                '-COMPARE-': config['comparison']['launch'],
                '-NINTPATH-': config['comparison']['network_intensities_path'],
                '-IINTPATH-': config['comparison']['intersection_intensities_path'],
                '-PMODPATH-': (
                    Path(config['comparison']['prev_net_counts_path']).parent.parent
                    if config['comparison']['prev_net_counts_path']
                    else None
                ),
                '-QGIS-': config['gis']['launch'],
                '-QGISPATH-': config['gis']['qgis_path']
            }
            for key, value in window_dict.items():
                try:
                    if isinstance(window[key], sg.Input):
                        # ensure that value actually updates with empty string
                        window[key].update(value if value is not None else '')
                    else:
                        window[key].update(value)
                except:
                    traceback.print_exc()


def update_visibility(
        window: sg.Window,
        keys_list: List[str],
        visible: bool = True
        ):
    for key in keys_list:
        window[key].update(visible=visible)


def control_disabled(
        window: sg.Window,
        keys_list: List[str],
        disabled: bool = True
        ):
    for key in keys_list:
        window[key].update(disabled=disabled)


def put_plot_to_image(
        window: sg.Window,
        img_key: str,
        plot: Figure
        ):
    img_buffer = io.BytesIO()
    plot.savefig(img_buffer)
    img = ImageTk.PhotoImage(
        Image.open(img_buffer).resize((800, 400))
        )
    window[img_key].update(data=img)


def prepare_command(
        vvs_x: Dict[str, Union[str, int, float]],
        script_path: Union[str, Path],
        interpreter_path: str = INTERPRETER
) -> str:
    commands_list = []
    for k, v in vvs_x.items():
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


def sec2str(
        sec: int
) -> str:
    rmins, secs = divmod(sec, 60)
    hrs, mins = divmod(rmins, 60)
    h = f'{int(hrs)}'.zfill(2)
    m = f'{int(mins)}'.zfill(2)
    s = f'{round(secs)}'.zfill(2)
    return f'{h}:{m}:{s}'


def handle_time_change(
        window: sg.Window,
        event: Optional[str] = None,
        values: Optional[Dict[str, Any]] = None,
        start_time_el: str = '-START-',
        start_time_hms_el: str = '-STARTHMS-',
        end_time_el: str = '-END-',
        end_time_hms_el: str = '-ENDHMS-',
        info_el: str = '-INFO-'
):
    if values and event:
        if values[start_time_el] + 900 > values[end_time_el]:
            window['-INFO-'].update(
                'Start time must be less than end time by at least 15 minutes',
                text_color='firebrick1'
            )
            if event == start_time_el:
                if values[start_time_el] < 86400:
                    window[end_time_el].update(min(values[start_time_el] + 900, 86400))
                else:
                    window[start_time_el].update(85500)
                    window[end_time_el].update(86400)
            elif event == end_time_el:
                if 0 < values[end_time_el] < 86400:
                    window[start_time_el].update(max(values[end_time_el] - 900, 0))
                else:
                    window[start_time_el].update(0)
                    window[end_time_el].update(900)
    window[start_time_hms_el].update(sec2str(window[start_time_el].widget.get()))
    window[end_time_hms_el].update(sec2str(window[end_time_el].widget.get()))


def format_large_number(
        n: Union[int, float]
) -> str:
    suffixes = ['', 'k', 'm', 'b', 't']
    i = 0
    while n >= 1000 and i < len(suffixes) - 1:
        n /= 1000.0
        i += 1
    out = '{}{}'.format(
        int(n) if n.is_integer() else '{:.1f}'.format(n), suffixes[i]
    )
    return out
