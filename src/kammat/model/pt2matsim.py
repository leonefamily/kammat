# -*- coding: utf-8 -*-
"""
Created on Tue Jan 31 12:05:52 2023

@author: dgrishchuk
"""

import os
import lxml
import inspect
import tempfile
from pathlib import Path
from typing import Union

from kammat.model.utils import run_subprocess, modify_config
from kammat.defaults.constants import (
    PT2MATSIM_EXECUTABLE_PATH, PathPointer
    )

ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH = str(
    (Path(inspect.getfile(PathPointer)).parent / PT2MATSIM_EXECUTABLE_PATH).resolve()
    )


def run_pt2matsim(
        net_path: Union[str, Path],
        gtfs_folder: Union[str, Path],
        output_net_path: Union[str, Path],
        output_schedule_path: Union[str, Path],
        output_vehicles_path: Union[str, Path],
        number_of_threads: int = os.cpu_count() - 2,
        executable_path: Union[str, Path] = ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH,
        map_to_network: bool = False
        ):
    """
    Run java to get internal pt2matsim config, modify it and run again.

    Parameters
    ----------
    net_path : Union[str, Path]
        MATSim network.
    gtfs_folder : Union[str, Path]
        Folder where GTFS .txt files are
    output_net_path : Union[str, Path]
        Where combined net will be located
    output_schedule_path : Union[str, Path]
        Where pt net will be located
    output_vehicles_path : Union[str, Path]
        Where pt vehicles will be located
    number_of_threads : int, optional
        The default is os.cpu_count() - 2.
    executable_path : Union[str, Path], optional
        The default is ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH.
    map_to_network : bool, optional
        Whether to map schedules on existing links. The default in False.

    """
    # generate schedule and vehicles XML
    run_subprocess((
        'java',
        '-cp',
        str(executable_path),
        'org.matsim.pt2matsim.run.Gtfs2TransitSchedule',
        str(gtfs_folder),
        'dayWithMostTrips',
        'WGS84',
        str(output_schedule_path),
        str(output_vehicles_path),
    ))

    temp_config = tempfile.NamedTemporaryFile(delete=False, suffix='.xml')
    temp_config.close()
    try:
        # generate config to unify car and PT network
        run_subprocess((
            'java',
            '-cp',
            str(executable_path),
            'org.matsim.pt2matsim.run.CreateDefaultPTMapperConfig',
            str(temp_config.name),
        ))

        parser = lxml.etree.XMLParser(remove_comments=False)
        tree = lxml.etree.parse(temp_config.name, parser=parser)

        replacements = {
            'inputNetworkFile': net_path,
            'inputScheduleFile': output_schedule_path,
            'outputNetworkFile': output_net_path,
            'outputScheduleFile': output_schedule_path,
            'numOfThreads': number_of_threads,
            'modesToKeepOnCleanUp': 'car,truck,para,tram,rail,bus,drt',
        }

        if map_to_network:
            replacements['networkModes'] = 'pt,bus,tram,rail'
        else:
            replacements['scheduleMode'] = 'pt,bus,tram,rail'

        modify_config(replacements, tree)
        tree.write(temp_config.name)

        run_subprocess((
            'java',
            '-cp',
            str(executable_path),
            'org.matsim.pt2matsim.run.PublicTransitMapper',
            str(temp_config.name),
        ))
    finally:
        try:
            os.remove(temp_config.name)
        except FileNotFoundError:
            pass
