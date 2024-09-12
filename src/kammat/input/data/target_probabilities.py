# -*- coding: utf-8 -*-
"""
Created on Mon Dec 19 15:39:02 2022

@author: dgrishchuk
"""

from kammat.defaults.constants import (
    DISTANCES_COLUMNS, DISTANCES_SCHEMA, DISTANCES_INGORE_ACTIVITIES
    )

from kammat.input.data.types import TargetProbabilities
from kammat.input.data.utils import (
    load_table, load_only_columns, fix_spatial_precisions, check_columns,
    get_missing_spatial_units, get_target_spatial_precision,
    normalize_spatial_unit_probabilities_columnwise
    )
import logging
import pandas as pd
from typing import Dict, List

from kammat.defaults.variables import Variables


def check_activities_columns_sets(
        table: pd.DataFrame,
        columns: List[str],
        activities: List[str],
        ) -> List[str]:
    """
    Check, if there are all columns for every activity, that is used in diaries
    Raises error, if something is wrong.

    Parameters
    ----------
    table : pd.DataFrame
        Target probabilities table
    columns : List[str]
        Columns, that were marked as `unexpected` by the previous step
        (``check_columns``) and don't contain obligatory static or dynamic cols
    activities : List[str]
        All lower case activities occuring in diaries

    Raises
    ------
    RuntimeError
        If some activities or pairs of activities are missing in columns

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
        if a not in allcols and v.revert_abbreviation(a) not in DISTANCES_INGORE_ACTIVITIES:
            colstats["missing"].append(a)
        else:
            colstats["found"].append(a)

    double_acts = {c for c in allcols if c.count('_') == 1}
    for a12 in double_acts:
        a1, a2 = a12.split('_')
        is_redundant = any(v.revert_abbreviation(a) in
                           DISTANCES_INGORE_ACTIVITIES for a in [a1, a2])
        if not is_redundant and a1 in activities and a2 in activities:
            colstats["found"].append(a12)
        else:
            if a1 in activities and a2 in activities:
                colstats["found"].append(a12)
            else:
                colstats["redundant"].append(a12)
    if colstats["missing"]:
        raise RuntimeError('Target probabilities table misses columns'
                           f' for activities: {colstats["missing"]}')
    unexpected = colstats["redundant"] + [a for a in allcols
                                          if a not in colstats["found"]]
    return unexpected


def load_target_probabilities(
        path: str,
        activities: List[str],
        spatial_units: Dict[str, List[str]],
        ) -> TargetProbabilities:
    """
    # !!!

    Parameters
    ----------
    path : str
        DESCRIPTION.
    activities : List[str]
        DESCRIPTION.
    spatial_units : Dict[str, List[str]]
        DESCRIPTION.
     : TYPE
        DESCRIPTION.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    TargetProbabilities
        DESCRIPTION.

    """

    cols = load_only_columns(path)
    dcols = check_columns(cols, DISTANCES_COLUMNS)

    if dcols['missing']:
        raise RuntimeError(f"Target probabilities don't contain all"
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

    unexpected = check_activities_columns_sets(
        table, columns=dcols['unexpected'], activities=activities)

    if unexpected:
        table.drop(unexpected, axis=1, inplace=True)
        logging.warning('Unexpected and/or redundant columns were removed '
                        f'from target probabilities: {unexpected}')

    missing_units = get_missing_spatial_units(table, precision, spatial_units)
    if missing_units:
        raise RuntimeError(f'"{precision}" in distances misses some'
                           f' units: {missing_units}')

    prob_cols = [c for c in table.columns if c not in dcols['found']]
    normalize_spatial_unit_probabilities_columnwise(table,
                                                    precision,
                                                    prob_cols)

    target_probabilities = TargetProbabilities(table)
    target_probabilities.precision = precision
    target_probabilities.target_precision = target_precision
    return target_probabilities
