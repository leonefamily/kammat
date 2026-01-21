# -*- coding: utf-8 -*-
"""
Created on Wed Jan 18 17:03:34 2023

@author: dgrishchuk
"""

import lzma
import pickle
import itertools
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Union, List, Tuple, Any, Set
from datetime import timedelta as td, datetime as dt


def best_intersection(
        sets: List[Set[Any]]
) -> Set[Any]:
    """
    Return biggest intersection of sets starting with combining all.

    Tries the intersection of all sets first, then every combination that
    omits one set, two sets, etc. until each set is on its own.

    If several combinations yield intersections of the same maximal size,
    the first one encountered is returned.

    Parameters
    ----------
    sets : List[Set[Any]]
        List containing sets, populated or empty.

    Returns
    -------
    Set[Any]
        Biggest possible intersection of all or part of sets.

    """
    if not sets:
        return set()

    best = set()
    best_size = -1

    for r in range(len(sets), 0, -1):
        for combo in itertools.combinations(sets, r):
            inter = combo[0].copy()
            for s in combo[1:]:
                inter &= s
                if not inter:
                    # stop iterating if no intersection already
                    break
            cur_size = len(inter)
            if cur_size > best_size:
                best, best_size = inter, cur_size
            # skip the rest if max already found
            if best_size == min(len(s) for s in combo):
                continue
        if best_size > 0:
            break
    return best


def scale_to_percent(
        arr: List[int],
        perc: float = 0.9
) -> List[int]:
    """
    Scale array so that its sum is equal `perc` fraction of the original sum.

    Parameters
    ----------
    arr : List[int]
        An integer array.
    perc : float, optional
        Fraction to calculate target sum for the output array.
        The default is 0.9.

    Returns
    -------
    List[int]
        List of integers, even if input is mistakenly float.

    """
    original_sum = sum(arr)
    target_sum = round(original_sum * perc)

    scaled = [x * perc for x in arr]
    ints = [int(v) for v in scaled]
    fracs = [v - i for v, i in zip(scaled, ints)]

    current_sum = sum(ints)
    delta = target_sum - current_sum

    if delta > 0:
        # add 1 delta times if bigger than 0
        idx = sorted(
            range(len(fracs)),
            key=lambda i: fracs[i],
            reverse=True
        )[:delta]
        for i in idx:
            ints[i] += 1
    elif delta < 0:
        # subtract if less than 0
        idx = sorted(
            range(len(fracs)),
            key=lambda i: fracs[i]
        )[:-delta]
        for i in idx:
            ints[i] -= 1

    return ints


def proj_distance_df(df: Union[pd.DataFrame, gpd.GeoDataFrame],
                     xy: Union[Tuple[float], List[float]]) -> pd.Series:
    """
    Calculate beeline distance to every point in DataFrame with the assumption,
    that coordinate reference system is projected (not geographic).

    Parameters
    ----------
    df : Union[pd.DataFrame, gpd.GeoDataFrame]
        DataFrame containing 'x' and 'y' columns
    xy : Union[Tuple[float], List[float]]
        Ordered iterable with float values of longitude and latitude of a point

    Returns
    -------
    pd.Series
        Series of distances to the specified point in meters (has df's indices)

    """
    return np.sqrt(np.square(df['x'] - xy[0]) + np.square(df['y'] - xy[1]))


def proj_distance(xy1: Union[Tuple[float], List[float]],
                  xy2: Union[Tuple[float], List[float]]) -> float:
    """
    Calculate beeline distance between two points with the assumption,
    that their coordinate reference system is projected (not geographic).

    Parameters
    ----------
    xy1 : Union[Tuple[float], List[float]]
        Ordered iterable with float values of lon and lat of 1st point
    xy2 : Union[Tuple[float], List[float]]
        Ordered iterable with float values of lon and lat of 2nd point

    Returns
    -------
    float
        Distance in meters

    """
    return ((xy2[0] - xy1[0])**2 + (xy2[1] - xy1[1])**2)**0.5


def str_to_td(
        string: str
        ) -> td:
    """
    Turn string of format HH:MM or HH:MM:SS into timedelta.

    Parameters
    ----------
    string : str
        String in format HH:MM or HH:MM:SS

    Returns
    -------
    td

    """
    if isinstance(string, td):
        return string
    splitted = string.split(':')
    if len(splitted) == 2:
        return td(hours=int(splitted[0]),
                  minutes=int(splitted[1]))
    elif len(splitted) == 3:
        return td(hours=int(splitted[0]),
                  minutes=int(splitted[1]),
                  seconds=int(splitted[2]))


def td_to_str(tdobj: td) -> str:
    """
    Make timedelta a HH:MM:SS string, without microseconds.

    Parameters
    ----------
    tdobj : td
        Any timedelta object (even from pandas)

    Returns
    -------
    str

    """
    return (dt(1970, 1, 1) + tdobj).replace(microsecond=0).time()


def intify(
        itrbl: Union[List[float], Tuple[float]]
        ) -> List[int]:
    """
    Turn all values of the passed iterable into list of integers.

    Parameters
    ----------
    itrbl : Union[List[float], Tuple[float]]
        Any single-dimensional iterable containing numeric values

    Returns
    -------
    List[int]
        List of integers

    """
    return [int(i) for i in itrbl]


def group_pairs(
        itrbl: Union[list, tuple]
        ) -> List[tuple]:
    """
    Stack values pairs. Every next tuple inside the resulting list starts with
    the last value in a previous tuple. Minimum length of input iterable is 2

    Parameters
    ----------
    itrbl : Union[list, tuple]
        Any single-dimensional iterable

    Returns
    -------
    groupped : List[tuple]
        Resulting list with values paired in tuples

    """
    groupped = []
    last = None
    for el in itrbl:
        if last is not None:
            groupped.append((last, el))
        last = el
    return groupped


def list_to_chunks(
        inp: Union[List[Any], Tuple[Any]],
        nchunks: int
        ) -> List[List[Any]]:
    """
    Split a sequence into equal (if possible) parts.

    Parameters
    ----------
    inp : Union[List[Any], Tuple[Any]]
        List or tuple with elements of any type
    nchunks : int
        Positive integer of parts number

    Returns
    -------
    List[List[Any]]
        List of lists with original elements

    """
    reslist = []
    k, m = divmod(len(inp), nchunks)

    for i in range(nchunks):
        reslist.append(
            inp[i * k + min(i, m):(i + 1) * k + min(i + 1, m)]
            )

    return reslist


def start_population_file(
        pop_file: Union[str, Path]
        ):
    """
    Start (with replacement) an xml file for MATSim.

    Parameters
    ----------
    pop_file : Union[str, Path]
        Path to the xml file

    """
    with open(pop_file, 'w') as f_write:
        f_write.write('<?xml version="1.0" ?>\n')
        f_write.write('<!DOCTYPE population SYSTEM '
                      '"http://www.matsim.org/files/dtd/population_v6.dtd">\n')
        f_write.write('<population>\n')


def end_population_file(
        pop_file: Union[str, Path]
        ):
    """
    Write last row.

    Parameters
    ----------
    pop_file : Union[str, Path]
        Path to the xml file

    """
    with open(pop_file, 'a+') as f_write:
        f_write.write('</population>')


def write_csv_header(
        csv_path: Union[str, Path],
        maxlen: int
        ):
    """
    Write (with replacement) a csv file for analysis containing only header.

    Parameters
    ----------
    file : Union[str, Path], optional
        Path to the csv.
    maxlen : int, optional
        Maximum number of activities, so the function knows, how many times it
        should repeat the columns.

    """
    header = 'pers_id;category;activities;init_mode;region;area;district;zone;'
    for i in range(maxlen):
        header += (f'facility{i};x{i};y{i};gendist{i};trip{i};pt_stop_walk{i};'
                    f'mode{i};starttime{i};endtime{i};')
    header = header[:-1] + '\n'
    with open(csv_path, 'w') as f:
        f.write(header)


def save_pickle(
        obj: Any,
        pickle_path: Union[str, Path]
        ):
    """
    Dump agents to xzip format.

    Use .xz suffix

    Parameters
    ----------
    obj : Any
        Object.
    pickle_path : Union[str, Path]
        Path to compressed pickle

    """
    with lzma.open(pickle_path, "wb") as f:
        pickle.dump(obj, f)


def read_pickle(
        pickle_path: Union[str, Path]
        ) -> Any:
    """
    Read any from .xz pickle.

    Parameters
    ----------
    pickle_path : Union[str, Path]
        Path to compressed pickle

    """
    with lzma.open(pickle_path, "rb") as f:
        return pickle.load(f)
