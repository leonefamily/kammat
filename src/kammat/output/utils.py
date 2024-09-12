# -*- coding: utf-8 -*-
"""
Created on Thu Feb  9 12:02:03 2023

@author: dgrishchuk
"""

import gzip
import json
from pathlib import Path
from collections import Counter
from datetime import timedelta as td
from typing import Union, List, Dict, Literal, Any, Union

UNITS_IN_SECONDS = {
    's': 1,
    'm': 60,
    'h': 3600
    }

EVENTS_MODES = ('car', 'truck')
LINK_STATS_FIGURE_SIZE = (12, 6)
LINK_STATS_DF_COLS = ('timestep', *EVENTS_MODES, 'total')
RIBBON_DIAGRAMS_DF_COLS = ('from_link', 'to_link', 'from_group', 'to_group', 'count')
RIBBON_DIAGRAMS_GROUP_DF_COLS = ('group', 'left', 'entered', 'total')
PT_STATS_DF_COLS = ('link_id', 'from_stop', 'to_stop', 'count')
PT_LINK_STATS_DF_COLS = ('timestep', 'line', 'passengers')
PT_STOPS_STATS_DF_COLS = ('',)

MODES_COLORS = {
    'pt': 'C0',
    'car': 'C3',
    'truck': 'C5',
    'citylog': 'C6',
    'total': 'C7'
    }


def get_timeline(
        start: int = 0,
        stop: int = 86400,  # 24 hours
        aggregate_by: int = 3600,  # 1 hour
        aggregate_unit: Literal['s', 'm', 'h'] = 'h'
        ) -> List[Union[int, float]]:
    """
    Prepare timeline.

    Parameters
    ----------
    start : int, optional
        Period start time IN SECONDS. The default is 0.
    stop : int, optional
        Period end time IN SECONDS. The default is 86400.
    aggregate_by : int, optional
        Split timeline by this value IN SECONDS. The default is 3600.
    aggregate_unit : Literal['s', 'm', 'h'], optional
        By values of what unit should be list populated. The default is 'h'.

    Returns
    -------
    List[Union[int, float]]

    """
    timeline = set()
    current = start
    while current < stop:
        timeline.add(
            round_timestep(current, aggregate_by, aggregate_unit)
            )
        current += aggregate_by
    return sorted(timeline)


def round_timestep(
        current: int,
        aggregate_by: int = 3600,
        aggregate_unit: Literal['s', 'm', 'h'] = 'h'
        ) -> int:
    raw = int(current / aggregate_by) * aggregate_by
    return raw / UNITS_IN_SECONDS[aggregate_unit]


def get_timestep_precision(
        link_stats: Dict[str, List[float]],
        timesteps_are_keys: bool = False
        ) -> float:
    gaps = []
    timesteps = list(link_stats.keys()) if timesteps_are_keys else link_stats['timestep'] 
    for i, timestep in enumerate(timesteps):
        if i != 0:
            gaps.append(timestep - timesteps[i - 1])
    maxgap = Counter(gaps).most_common()[0][0]
    return maxgap


def defaultdict2dict(d):
    for k, v in d.items():
        if isinstance(v, dict):
            d[k] = defaultdict2dict(v)
    return dict(d)


def read_json(
        p: Union[str, Path]
        ) -> Dict[Any, Any]:
    """
    Read any JSON.

    Parameters
    ----------
    p : Union[str, Path]
        Path

    Returns
    -------
    Dict[Any, Any]
        Any JSON.

    """
    with open(p, mode='r', encoding='utf-8') as f:
        return json.load(f)


def write_json(
        o: Any,
        p: Union[str, Path]
        ):
    """
    Write any JSON with 4 indent spaces.

    Parameters
    ----------
    p : Union[str, Path]
        Path

    """
    with open(p, mode='w', encoding='utf-8') as f:
        return json.dump(o, f, indent=4)


def write_json_gz(
        json_like: Any,
        path: Union[str, Path]
):
    """
    Write a gzipped JSON, which takes less space on disk.

    Parameters
    ----------
    json_like : Any
        Any object that can be converted to JSON.
    path : Union[str, Path]
        Path to dump object.

    """
    with gzip.open(path, 'wt', encoding="utf-8") as zipfile:
        json.dump(json_like, zipfile)


def read_json_gz(
        path: Union[str, Path]
) -> Any:
    """
    Read a gzipped JSON.

    Parameters
    ----------
    path : Union[str, Path]
        Path to json-like object.

    Returns
    -------
    Any
        Whatever was stored in the json.gz.

    """
    with gzip.open(path, 'r') as fin:
        json_like = json.loads(fin.read().decode('utf-8'))
    return json_like


def td2str(
        tdo: td
) -> str:
    """
    Convert timedelta object to a string in HH:MM:SS format.

    Parameters
    ----------
    tdo : td
        Timedelta object.

    Returns
    -------
    str

    """
    rmins, secs = divmod(tdo.total_seconds(), 60)
    hrs, mins = divmod(rmins, 60)
    h = f'{int(hrs)}'.zfill(2)
    m = f'{int(mins)}'.zfill(2)
    s = f'{round(secs)}'.zfill(2)
    return f'{h}:{m}:{s}'
