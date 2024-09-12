# -*- coding: utf-8 -*-
"""
Created on Thu Feb  9 12:00:37 2023

@author: dgrishchuk
"""

import matsim
import logging
import pandas as pd
from pathlib import Path
from datetime import timedelta as td
from collections import defaultdict
from typing import Union, List, Tuple, Set, Dict  # , Sequence

from kammat.output.utils import (
    get_timeline, round_timestep, read_json, read_json_gz, write_json, write_json_gz
)

UNITS_IN_SECONDS = {
    's': 1,
    'm': 60,
    'h': 3600
    }

EVENTS_MODES = ('car', 'truck')
LINK_STATS_FIGURE_SIZE = (12, 6)
LINK_STATS_DF_COLS = ('timestep', *EVENTS_MODES, 'total')

MODES_COLORS = {
    'pt': 'C0',
    'car': 'C3',
    'truck': 'C5',
    'citylog': 'C6',
    'total': 'C7'
    }

logging.basicConfig(
    format='%(asctime)s %(levelname)s %(message)s',
    level=logging.INFO
)


def guess_mode(
        vehicle: str
        ) -> str:
    if 'veh_' in vehicle:
        return 'pt'
    elif 'truck' in vehicle:
        return 'truck'
    return 'car'


def is_citylog(
        vehicle: str = None,
        citylog_flags: Union[List[str], Tuple[str], Set[str]] = None
        ):
    return any(f in vehicle for f in citylog_flags)


def get_events_counts(
        events_path: Union[str, Path],
        time_limit: int = 86400,
        aggregate_by: int = 900,
        city_logistics_flags: Union[List[str], Tuple[str], Set[str]] = None,
        # process_agents_links: bool = True
        ) -> Dict[str, Dict[float, Dict[str, int]]]:
    """
    Parse events and.

    Parameters
    ----------
    events_path : Union[str, Path]
        DESCRIPTION.
    time_limit : int, optional
        DESCRIPTION. The default is 24.
    aggregate_by : int, optional
        DESCRIPTION. The default is 1.
    city_logistics_flags : Union[List[str], Tuple[str], Set[str]]
        DESCRIPTION.

    Returns
    -------
    Dict[str, Dict[float, Dict[str, int]]]
        DESCRIPTION.

    """
    events = matsim.event_reader(
        events_path,
        types=('entered link,left link,VehicleArrivesAtFacility,'
               'VehicleDepartsAtFacility,PersonEntersVehicle,'
               'PersonLeavesVehicle,TransitDriverStarts')
        )
    timeline = get_timeline(
        stop=time_limit,
        aggregate_by=aggregate_by,
        aggregate_unit='s'
        )

    counts = {
        mode: {timestep: defaultdict(int) for timestep in timeline}
        for mode in EVENTS_MODES
        }
    turns = {
        mode: {timestep: defaultdict(int) for timestep in timeline}
        for mode in EVENTS_MODES
        }
    pt_counts = defaultdict(list)  # vehicle_id

    # agents_links = defaultdict(list)
    # links_agents = {
    #     mode: {timestep: defaultdict(list) for timestep in timeline}
    #     for mode in EVENTS_MODES
    #     }
    vehicle_cache = defaultdict(
        lambda: {'link': None, 'type': None}
        )
    pt_drivers = set()

    for i, event in enumerate(events):
        # parse time and round it to the closest timestep
        if event['time'] >= time_limit:
            break

        if event['type'] in ['entered link', 'left link']:
            # handle vehicles
            timestep = round_timestep(
                current=event['time'],
                aggregate_by=aggregate_by,
                aggregate_unit='s'
                )

            mode = guess_mode(event['vehicle'])
            if event['type'] == 'entered link' and mode != 'pt':
                counts[mode][timestep][event['link']] += 1
                # if process_agents_links:
                #     agents_links[mode][event['vehicle']].append(
                #         (event['link'], event['time'])
                #         )
                if vehicle_cache[event['vehicle']]['type'] == 'left link':
                    connection = (
                        vehicle_cache[event['vehicle']]['link'], event['link']
                        )
                    turns[mode][timestep][connection] += 1

            vehicle_cache[event['vehicle']] = {
                'link': event['link'], 'type': event['type']
                }
        # handle pt passengers
        elif event['type'] == 'TransitDriverStarts':
            pt_drivers.add(event['driverId'])
        elif event['type'] == 'VehicleArrivesAtFacility':
            pt_counts[event['vehicle']].append(
                {'stop': event['facility'],
                 'arrival': event['time'],
                 'entered': 0, 'left': 0}
                )
        elif event['type'] == 'VehicleDepartsAtFacility':
            pt_counts[event['vehicle']][-1]['departure'] = event['time']
        elif event['type'] == 'PersonEntersVehicle' and event['vehicle'] in pt_counts:
            if event['person'] not in pt_drivers:
                pt_counts[event['vehicle']][-1]['entered'] += 1
        elif event['type'] == 'PersonLeavesVehicle' and event['vehicle'] in pt_counts:
            if event['person'] not in pt_drivers:
                pt_counts[event['vehicle']][-1]['left'] += 1

        if i % 1000000 == 0:
            tm = td(seconds=event['time'])
            logging.info(f'Event {i}, time {tm}')

    for mode in counts:
        for timestep in counts[mode]:
            counts[mode][timestep] = dict(counts[mode][timestep])
            turns[mode][timestep] = dict(turns[mode][timestep])
    # for mode in agents_links:
    #     agents_links[mode] = dict(agents_links[mode])

    return counts, pt_counts, turns  #, agents_links


def pt_counts_to_df(
        pt_counts
        ) -> pd.DataFrame:
    """
    

    Parameters
    ----------
    pt_counts : TYPE
        DESCRIPTION.

    Returns
    -------
    pd.DataFrame

    """
    vehdfs = []
    for veh, vehdict in pt_counts.items():
        vehdf = pd.DataFrame(vehdict)
        vehdf['vehicle'] = veh
        vehdfs.append(vehdf)

    vehsdf = pd.concat(vehdfs)
    return vehsdf





def write_link_counts(
        counts: Dict[str, Dict[float, Dict[str, int]]],
        path: Union[str, Path]
):
    """
    Dump counts dictionary as JSON.

    Parameters
    ----------
    counts : Dict[str, Dict[float, Dict[str, int]]]
        Counts object
    path : Union[str, Path]
        Path to dump counts

    """
    if Path(path).suffix.endswith('.gz'):
        write_json_gz(counts, path)
    else:
        write_json(counts, path)


def write_link_turns(
        turns: Dict[str, Dict[float, Dict[Tuple[str], int]]],
        path: Union[str, Path]
        ):
    """
    Dump turns dictionary as JSON.

    Parameters
    ----------
    turns : Dict[str, Dict[float, Dict[Tuple[str], int]]]
        Turns object
    path : Union[str, Path]
        Path to dump counts

    """
    nturns = {}
    for mode in turns:
        for timestep in turns[mode]:
            for turn in turns[mode][timestep]:

                if mode not in nturns:
                    nturns[mode] = {}
                if timestep not in nturns[mode]:
                    nturns[mode][timestep] = {}

                newturn = ' || '.join([str(part) for part in turn])
                nturns[mode][timestep][newturn] = (
                    turns[mode][timestep][turn]
                )
    if Path(path).suffix.endswith('.gz'):
        write_json_gz(nturns, path)
    else:
        write_json(nturns, path)


def write_pt_counts(
        pt_counts: Dict[str, Dict[str, Union[str, Union[str, int, float]]]],
        path: Union[str, Path]
        ):
    """
    

    Parameters
    ----------
    pt_counts : Dict[str, Dict[str, Union[str, Union[str, int, float]]]]
        DESCRIPTION.
    path : Union[str, Path]
        DESCRIPTION.

    """
    if Path(path).suffix.endswith('.gz'):
        write_json_gz(pt_counts, path)
    else:
        write_json(pt_counts, path)


def read_pt_counts(
        path: Union[str, Path]
        ) -> Dict[str, Dict[str, Union[str, Union[str, int, float]]]]:
    """
    

    Parameters
    ----------
    path : Union[str, Path]
        DESCRIPTION.

    Returns
    -------
    Dict[str, Dict[str, Union[str, Union[str, int, float]]]]
        DESCRIPTION.

    """
    if Path(path).suffix.endswith('.gz'):
        pt_counts = read_json_gz(path)
    else:
        pt_counts = read_json(path)
    return pt_counts


def read_link_counts(
        path: Union[str, Path]
        ) -> Dict[str, Dict[float, Dict[str, int]]]:
    """
    Read counts from JSON.

    Parameters
    ----------
    path : Union[str, Path]
        Path to read counts

    Returns
    -------
    Dict[str, Dict[float, Dict[str, int]]]
        Counts object

    """
    if Path(path).suffix.endswith('.gz'):
        counts = read_json_gz(path)
    else:
        counts = read_json(path)
    for mode in counts:
        if mode in EVENTS_MODES:
            counts[mode] = {float(k): v for k, v in counts[mode].items()}
    return counts


def read_link_turns(
        path: Union[str, Path]
        ) -> Dict[str, Dict[float, Dict[Tuple[str], int]]]:
    """
    Read turns from JSON.

    Parameters
    ----------
    path : Union[str, Path]
        Path to read counts.

    Returns
    -------
    Dict[str, Dict[float, Dict[Tuple[str], int]]]
        Turns object.

    """
    if Path(path).suffix.endswith('.gz'):
        turns = read_json_gz(path)
    else:
        turns = read_json(path)
    for mode in turns:
        turns[mode] = {float(k): v for k, v in turns[mode].items()}
        for timestep in turns[mode]:
            turns[mode][timestep] = {tuple(k.split(' || ')): v for k, v
                                      in turns[mode][timestep].items()}
    return turns
