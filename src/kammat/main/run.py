#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May  7 18:18:04 2024

@author: leonefamily
"""

import sys
import inspect
import argparse
import threading
from pathlib import Path
import subprocess
import logging
from typing import List, Dict, Union, Any, Optional, IO

from kammat.defaults.constants import (
    LOGGER_FORMAT, CACHE_SETTINGS_PATH, PathPointer
)
from kammat.main.configure import (
    load_config, validate_config, Config,
    default_run_config, default_run_directories,
    populate_default_config, validate_path,
    save_config
)
from kammat.model.utils import (
    get_matsim_version, get_matsim_runnable_class
)

logging.basicConfig(
    format=LOGGER_FORMAT,
    level=logging.INFO
)

logger = logging.getLogger('run')


def create_directory(
        p: Union[str, Path]
) -> bool:
    try:
        Path(p).mkdir(parents=True, exist_ok=True)
        return True
    except Exception:
        return False


def report(
        filepath: Union[str, Path],
        content: Any,
        mode: str = 'a'
) -> bool:
    pp = Path(filepath)
    success = create_directory(pp.parent)
    if not success:
        logging.warning(f"Parent directory couldn't be created for [{pp}]")
        return False
    with pp.open(mode=mode, encoding='utf-8') as f:
        try:
            f.write(content)
            return True
        except Exception:
            return False


def read_stream(
        stream: IO[Any],
        save_log: bool = False):
    try:
        while True:
            line = stream.readline()
            if not line:
                break
            print(line.rstrip())
            if save_log:
                with open(CACHE_SETTINGS_PATH + '/log.txt', 'a') as f:
                    f.write(str(line) + '\n')
    finally:
        stream.close()


def run_command(
        command: str,
        stage: str,
        save_log: str = None
):
    report(CACHE_SETTINGS_PATH + '/current_stage', content=stage, mode='w')
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        shell=True,
        text=True
    )
    logging.info(command)
    threads = []
    if proc.stdout:
        t_out = threading.Thread(target=read_stream, args=(proc.stdout, save_log))
        t_out.daemon = True
        threads.append(t_out)
        t_out.start()
    if proc.stderr:
        t_err = threading.Thread(target=read_stream, args=(proc.stderr, save_log))
        t_err.daemon = True
        threads.append(t_err)
        t_err.start()
    return_code = proc.wait()
    report(CACHE_SETTINGS_PATH + '/last_stage', content=stage, mode='w')
    if return_code != 0:
        report(CACHE_SETTINGS_PATH + '/current_stage', content='failed', mode='w')
        raise RuntimeError(f"{stage} stage returned error code {return_code}")
    else:
        report(CACHE_SETTINGS_PATH + '/current_stage', content='', mode='w')


def run_network(
        config: Config
):
    config_n = {
        k: v for k, v in config['network'].items()
        if k not in ['existing', 'nettype']
    }
    if config['network']['nettype'] == 'ceda':
        script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/network/ceda.py'
    elif config['network']['nettype'] == 'generic':
        script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/network/generic.py'
    command = prepare_command(config_n, script_path)
    run_command(command=command, stage='network')


def run_pt(
        config: Config
):
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/network/pt.py'
    command = prepare_command(config['pt'], script_path)
    run_command(command=command, stage='pt')


def prepare_command(
        config: Config,
        script_path: Union[str, Path],
        interpreter_path: str = sys.executable
) -> str:
    commands_list = []
    for k, v in config.items():
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
        config: Dict[str, Dict[str, Union[str, int, float]]]
):
    config_p = {
        k: v for k, v in config['population'].items()
        if k not in ['existing'] and v is not None and
        (True if isinstance(v, bool) and not v else True)
    }
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'input/population/load.py'
    command = prepare_command(config_p, script_path)
    run_command(command=command, stage='population')


def run_config(
        config: Dict[str, Dict[str, Union[str, int, float]]]
):
    """
    Send command to handle config preparation.
    """
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'model/config.py'
    command = prepare_command(config['config'], script_path)
    run_command(command=command, stage='config')


def run_model(
        config: Dict[str, Dict[str, Union[str, int, float]]]
):
    """
    Send command to handle model run.
    """
    if 'custom_class' in config['model'] and config['model']['custom_class']:
        cl = config['model']['custom_class']
    else:
        ver = get_matsim_version(
            matsim_executable=config["model"]["executable_path"]
        )
        cl = get_matsim_runnable_class(matsim_version=ver)  # class to run
    command = (
        f'java -cp "{config["model"]["executable_path"]}" '
        f'-Xmx{config["model"]["ram_limit"]} '
        f'{cl} "{config["model"]["config_path"]}"'
    )
    run_command(command=command, stage='model')


def run_analysis(
        config: Dict[str, Dict[str, Union[str, int, float]]]
):
    """
    Send command to handle analyses.
    """
    config_a = {
        k: v for k, v in config['analysis'].items() if k not in ['launch']
    }
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'output/analysis.py'
    command = prepare_command(config_a, script_path)
    run_command(command=command, stage='analysis')


def run_comparison(
        config: Dict[str, Dict[str, Union[str, int, float]]]
):
    """
    Send command to handle comparison.
    """
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'output/comparison.py'
    config_c = {
        k: v for k, v in config['comparison'].items() if k not in ['launch']
    }
    command = prepare_command(config_c, script_path)
    run_command(command=command, stage='comparison')


def run_gis(
        config: Dict[str, Dict[str, Union[str, int, float]]]
):
    """
    Send command to handle GIS visualization.

    If `gui` is True, returns Thread object.
    Otherwise, runs prepared command in a
    subprocess and returns its exit code.
    """
    script_path = Path(inspect.getfile(PathPointer)).parent.parent / 'output/gis/qgis_project.py'
    params = ' '.join([
        f'--{k.replace("_", "-")} "{v}"'
        for k, v in config['gis'].items()
        if k not in ['launch', 'qgis_path']
    ])
    if sys.platform.lower() == 'linux':
        command = (
            'export PYTHONPATH="$PYTHONPATH:/usr/share/qgis/python/plugins:/usr/share/qgis/python"; '
            f'python3 "{script_path}" ' + params
        )
    else:
        command = f'"{config["gis"]["qgis_path"]}" "{script_path}" ' + params
    run_command(command=command, stage='gis')


def main(
        config_path: Optional[Union[str, Path]] = None,
        default_config_save_path: Optional[Union[str, Path]] = None,
        default_config_parent: Optional[Union[str, Path]] = None
):
    if default_config_save_path is not None:
        validate_path(p=Path(default_config_save_path).parent)
        if default_config_parent is not None:
            config = default_run_config(parent=default_config_parent)
        else:
            config = default_run_config()
        save_config(config=config, p=default_config_save_path)

    if config_path is not None:
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
        config = load_config(p=config_path)
        stages = validate_config(config=config)
        default_run_directories(parent=config['wd']['root'], create=True, exist_ok=True)
        logging.info(f"Stages to run: {stages}")
        for stage in stages:
            functions[stage](config)  # run corresponding function


def parse_args(
        args_list: Optional[List[str]] = None
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-c', '--config-path',
        help='JSON configuration file for the framework. Launches the run'
    )
    parser.add_argument(
        '-d', '--default-config-save-path',
        help='Save default JSON configuration file for the framework'
    )
    parser.add_argument(
        '-p', '--default-config-parent',
        help='Parent for default config creation - prepends any parent-dependent path'
    )
    if args_list is None:
        return parser.parse_args(sys.argv[1:])
    return parser.parse_args(args_list)


if __name__ == '__main__':
    create_directory(CACHE_SETTINGS_PATH)
    logging.basicConfig(
        format=LOGGER_FORMAT,
        level=logging.INFO,
        filename=CACHE_SETTINGS_PATH + '/log_main.txt',
        filemode='w'
    )
    args = parse_args()
    main(
        config_path=args.config_path,
        default_config_save_path=args.default_config_path,
        default_config_parent=args.default_config_parent
    )
