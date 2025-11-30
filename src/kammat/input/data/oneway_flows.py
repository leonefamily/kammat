# -*- coding: utf-8 -*-
"""
Created on Wed Jun 11 13:22:15 2025

@author: dgrishchuk
"""

import logging
import itertools
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Union, List, Dict

from kammat.input.data.types import OnewayFlows
from kammat.input.data.utils import (
    load_table, check_columns
)

from kammat.defaults.constants import (
    ONEWAY_FLOWS_COLUMNS, ONEWAY_FLOWS_SCHEMA
)


def load_oneway_flows(
        path: Union[str, Path],
        facilities: Dict[str, gpd.GeoDataFrame]
) -> OnewayFlows:
    """
    Load single trip flows data.

    Verifies that facilities mentioned in oneway flows
    exist in actual provided facilities.

    Parameters
    ----------
    path : Union[str, Path]
        Path to the .csv table
    facilities : Dict[str, gpd.GeoDataFrame]
        Facilities to check against

    Returns
    -------
    OnewayFlows

    """
    table = load_table(
        path,
        extention='.csv',
        converters=ONEWAY_FLOWS_SCHEMA
    ).replace({'': np.nan})
    ofcols = check_columns(table.columns.tolist(), ONEWAY_FLOWS_COLUMNS)

    if ofcols['missing']:
        raise RuntimeError("Oneway flows don't contain all required "
                           f"static columns, missing: {ofcols['missing']}")

    available_facilities = set(
        itertools.chain.from_iterable(
            facs['facility'].tolist() for act, facs in facilities.items()
        )
    )

    required_facilities = set(
        table['from_facility'].dropna().tolist() +
        table['to_facility'].dropna().tolist()
    )
    if not required_facilities.issubset(available_facilities):
        missing_ids = required_facilities.difference(available_facilities)
        raise RuntimeError(
            f"Oneway flows depend on these missing facilities: {missing_ids}"
        )

    if len(table) != len(table['mode'].dropna()):
        raise RuntimeError(
            "Oneway flows can only have non-null modes in `mode` column"
        )

    # check if there are unspecified facilities that can be then auto-assigned
    ftypes = ['from', 'to']
    required_combs = set()
    for ftype in ftypes:
        fempty_table = table[table[f'{ftype}_facility'].isna()]
        if len(fempty_table):
            fempty_set = set(
                fempty_table[[
                    f'{ftype}_activity',
                    f'{ftype}_spatial_level',
                    f'{ftype}_spatial_unit'
                ]].itertuples(index=False, name=None)
            )
            required_combs.update(fempty_set)
    for act, slevel, spunit in required_combs:
        if not pd.isna(act):
            facs = facilities[act]
            if pd.isna(slevel) or pd.isna(spunit):
                if len(facs) > 0:
                    continue
                raise RuntimeError(
                    f'Oneway flows reference activity {act} that '
                    'does not appear in facilities at all'
                )
            if not facs[slevel].isin([spunit]).any():
                raise RuntimeError(
                    'Oneway flows reference combination that '
                    'does not appear in facilities (or is incorrect): '
                    f'activity {act}, level {slevel} with value {spunit}'
                )
        else:
            if pd.isna(slevel) or pd.isna(spunit):
                raise RuntimeError(
                    'Oneway flows reference spatial combination that '
                    'does not appear in facilities (or is incorrect): '
                    f'level {slevel} with value {spunit}'
                )
            has_one = False
            for act, facs in facilities.items():
                if facs[slevel].isin([spunit]).any():
                    has_one = True
                    break
            if not has_one:
                raise RuntimeError(
                    'Oneway flows reference spatial combination that '
                    'does not appear in facilities: '
                    f'level {slevel} with value {spunit}'
                )

    return OnewayFlows(table)
