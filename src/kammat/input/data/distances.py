# -*- coding: utf-8 -*-
"""
Created on Sun Dec 18 20:05:01 2022

@author: dgrishchuk
"""

from kammat.defaults.constants import (
    DISTANCES_COLUMNS, DISTANCES_SCHEMA, DISTANCES_STATISTIC_COLUMNS,
    DISTANCES_INGORE_ACTIVITIES
    )

from kammat.input.data.types import Distances
from kammat.input.data.utils import (
    load_table, load_only_columns, fix_spatial_precisions, check_columns,
    get_missing_spatial_units, get_target_spatial_precision,
    )
import logging
import pandas as pd
from typing import Dict, List

from kammat.defaults.variables import Variables


def check_activities_statistic_columns_sets(
        table: pd.DataFrame,
        columns: List[str],
        activities: List[str]
        ) -> List[str]:
    """
    Check, if there are all statistic columns to draw value from Weibull
    distribution for every activity, that is used in diaries. Raises error,
    if something is wrong.

    Parameters
    ----------
    table : pd.DataFrame
        Distances or distances probabilities table
    columns : List[str]
        Columns, that were marked as `unexpected` by the previous step
        (``check_columns``) and don't contain obligatory static or dynamic cols
    activities : List[str]
        All lower case activities occuring in diaries

    Raises
    ------
    RuntimeError
        If some activities are missing statistic columns, or not all activities
        have defined distances

    Returns
    -------
    List[str]
        List of unexpected columns, including redundant ones

    """
    v = Variables()
    colstats = {
        'missing': [],
        'found': [],
        'redundant': []
        }
    allcols = set(columns)
    for a in activities:
        reqcols = set(f'{a}_{dsc}' for dsc in DISTANCES_STATISTIC_COLUMNS)
        if (not reqcols.issubset(allcols) and
                v.revert_abbreviation(a) not in DISTANCES_INGORE_ACTIVITIES):
            colstats["missing"].append(a)
        else:
            colstats["found"].extend(reqcols)

    double_acts = {tuple(c.split('_')[:2])
                   for c in allcols if c.count('_') == 2}
    for a1, a2 in double_acts:
        reqcols = set(f'{a1}_{a2}_{dsc}' for dsc in DISTANCES_STATISTIC_COLUMNS)
        if (not reqcols.issubset(allcols) and
                v.revert_abbreviation(a1) not in DISTANCES_INGORE_ACTIVITIES and
                v.revert_abbreviation(a2) not in DISTANCES_INGORE_ACTIVITIES and
                a1 in activities and a2 in activities):
            colstats["missing"].append((a1, a2))
        else:
            if a1 in activities and a2 in activities:
                colstats["found"].extend(reqcols)
            else:
                colstats["redundant"].extend(reqcols)
    if colstats["missing"]:
        raise RuntimeError('Distances table misses columns to create Weibull '
                           f'distribution values {DISTANCES_STATISTIC_COLUMNS}'
                           f' for activities: {colstats["missing"]}')
    unexpected = colstats["redundant"] + [a for a in allcols
                                          if a not in colstats["found"]]
    return unexpected


def load_distances(
        path: str,
        categories: List[str],
        activities: List[str],
        spatial_units: Dict[str, List[str]],
        target_spatial_units: Dict[str, List[str]] = None
        ) -> Distances:

    cols = load_only_columns(path)
    dcols = check_columns(cols, DISTANCES_COLUMNS)

    if dcols['missing']:
        raise RuntimeError(f"Distances don't contain all"
                           f" required static columns, missing:"
                           f" {dcols['missing']}")

    target_precision = get_target_spatial_precision(cols)
    if target_precision is not None:
        dcols['unexpected'].remove(f'{target_precision}_target')
        dcols['found'].append(f'{target_precision}_target')
    else:
        raise RuntimeError('Target probabilities must have *_target column')

    converters = {**DISTANCES_SCHEMA, f'{target_precision}_target': str}

    table = load_table(path, extention='.csv', converters=converters)
    precision = fix_spatial_precisions(table)

    unexpected = check_activities_statistic_columns_sets(
        table, columns=dcols['unexpected'], activities=activities)

    if unexpected:
        table.drop(unexpected, axis=1, inplace=True)
        logging.warning('Unexpected and/or redundant columns were removed '
                        f'from distances: {unexpected}')

    missing_units = get_missing_spatial_units(table, precision, spatial_units)
    if missing_units:
        raise RuntimeError(f'"{precision}" in distances misses some'
                           f' units: {missing_units}')

    distances = Distances(table)
    distances.precision = precision
    distances.target_precision = target_precision

    return distances
