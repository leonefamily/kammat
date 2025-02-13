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
from typing import Union, List, Tuple, Set, Dict, Optional  # , Sequence

from kammat.output.utils import (
    get_timeline, round_timestep, read_json, read_json_gz,
    write_json, write_json_gz, DbHandler
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
        citylog_flags: Optional[Union[List[str], Tuple[str], Set[str]]] = None
):
    return any(f in vehicle for f in citylog_flags)


def get_events_counts(
        events_path: Union[str, Path],
        time_limit: int = 86400,
        aggregate_by: int = 900,
        city_logistics_flags: Optional[Union[List[str], Tuple[str], Set[str]]] = None,
        output_road_db_path: Optional[Union[str, Path]] = None,
        db_flush_interval: int = 10_000_000
) -> Dict[str, Dict[float, Dict[str, int]]]:
    """
    Parse events and extract info about counts on links, turns, PT.

    Parameters
    ----------
    events_path : Union[str, Path]
        DESCRIPTION.
    time_limit : int, optional
        What is the end of parsing. The default is 86400.
    aggregate_by : int, optional
        Only affects turns and car/truck counts. The default is 900.
    city_logistics_flags : Union[List[str], Tuple[str], Set[str]]
        DESCRIPTION.

    Returns
    -------
    Dict[str, Dict[float, Dict[str, int]]]
        DESCRIPTION.

    """
    events = matsim.event_reader(
        events_path,
        types=(
            'entered link,left link,VehicleArrivesAtFacility,'
            'VehicleDepartsAtFacility,PersonEntersVehicle,'
            'PersonLeavesVehicle,TransitDriverStarts,'
            'vehicle enters traffic,vehicle leaves traffic'
            # 'actstart,actend'  # except for `pt interaction`
        )
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
    pt_counts = defaultdict(list)

    vehicle_cache = defaultdict(
        lambda: {'link': None, 'type': None}
    )
    pt_drivers = set()
    pt_vehs = set()
    pt_veh_departures = {}
    pt_veh_lines = {}

    if output_road_db_path is not None:
        dbh = DbHandler(
            db_path=output_road_db_path,
            flush_interval=db_flush_interval
        )
    else:
        dbh = None

    for i, event in enumerate(events):
        # parse time and round it to the closest timestep
        if event['time'] >= time_limit:
            break
        if event['type'] == 'vehicle enters traffic':
            # for capturing last activity for turn data
            # e.g. if None, no link was preceding current one
            # therefore it is not a turn
            vehicle_cache[event['vehicle']] = {
                'link': None, 'type': event['type']
            }
            if dbh is not None:
                # maybe come up with something prettier...
                dbh._vehicle_trip_nums[event['vehicle']] += 1
        elif event['type'] == 'vehicle leaves traffic':
            vehicle_cache[event['vehicle']] = {
                'link': None, 'type': event['type']
            }
        elif event['type'] in ['entered link', 'left link']:
            # handle road vehicles
            timestep = round_timestep(
                current=event['time'],
                aggregate_by=aggregate_by,
                aggregate_unit='s'
            )
            mode = guess_mode(event['vehicle'])
            if event['type'] == 'entered link' and mode != 'pt':
                if dbh is not None:
                    dbh.process_entered(
                        event=event,
                        mode=mode,
                        last_visited_link=(
                            vehicle_cache[event['vehicle']]['link']
                        )
                    )
                counts[mode][timestep][event['link']] += 1

                if vehicle_cache[event['vehicle']]['type'] == 'left link':
                    connection = (
                        vehicle_cache[event['vehicle']]['link'], event['link']
                    )
                    turns[mode][timestep][connection] += 1
            elif event['type'] == 'left link' and mode != 'pt':
                if vehicle_cache[event['vehicle']]['type'] == 'vehicle enters traffic':
                    counts[mode][timestep][event['link']] += 1
                    dbh.process_entered(
                        event=event,
                        mode=mode,
                        last_visited_link=None
                    )
            vehicle_cache[event['vehicle']] = {
                'link': event['link'], 'type': event['type']
            }
        # handle pt passengers
        elif event['type'] == 'TransitDriverStarts':
            pt_drivers.add(event['driverId'])
            pt_veh_departures[event['vehicleId']] = event['departureId']
            pt_veh_lines[event['vehicleId']] = event['transitLineId']
            pt_vehs.add(event['vehicleId'])
        elif event['type'] == 'VehicleArrivesAtFacility' and event['vehicle'] in pt_vehs:
            pt_counts[
                pt_veh_departures[event['vehicle']],
                pt_veh_lines[event['vehicle']],
                event['vehicle']
            ].append({
                'stop': event['facility'],
                'arrival': event['time'],
                'entered': 0,
                'left': 0
            })
        elif event['type'] == 'VehicleDepartsAtFacility' and event['vehicle'] in pt_vehs:
            pt_counts[
                pt_veh_departures[event['vehicle']],
                pt_veh_lines[event['vehicle']],
                event['vehicle']
            ][-1]['departure'] = event['time']
        elif event['type'] == 'PersonEntersVehicle' and event['vehicle'] in pt_vehs:
            if event['person'] not in pt_drivers:
                pt_counts[
                    pt_veh_departures[event['vehicle']],
                    pt_veh_lines[event['vehicle']],
                    event['vehicle']
                ][-1]['entered'] += 1
        elif event['type'] == 'PersonLeavesVehicle' and event['vehicle'] in pt_vehs:
            if event['person'] not in pt_drivers:
                pt_counts[
                    pt_veh_departures[event['vehicle']],
                    pt_veh_lines[event['vehicle']],
                    event['vehicle']
                ][-1]['left'] += 1
        if i % 1000000 == 0:
            tm = td(seconds=event['time'])
            logging.info(f'Event {i}, time {tm}')

    if dbh is not None:
        # final flush to write remainings
        dbh.flush()

    for mode in counts:
        for timestep in counts[mode]:
            counts[mode][timestep] = dict(counts[mode][timestep])
            turns[mode][timestep] = dict(turns[mode][timestep])

    return counts, pt_counts, turns


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
        pt_counts: Dict[Tuple[str, str, str], Dict[str, Union[str, Union[str, int, float]]]],
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
    if isinstance(next(iter(pt_counts)), tuple):
        npt_counts = {' || '.join(k): v for k, v in pt_counts.items()}
    else:
        npt_counts = pt_counts
    if Path(path).suffix.endswith('.gz'):
        write_json_gz(npt_counts, path)
    else:
        write_json(npt_counts, path)


def read_pt_counts(
        path: Union[str, Path]
        ) -> Dict[Union[str, Tuple[str, str, str]], Dict[str, Union[str, Union[str, int, float]]]]:
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
    if ' || ' in next(iter(pt_counts)):
        pt_counts = {tuple(k.split(' || ')): v for k, v in pt_counts.items()}
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
