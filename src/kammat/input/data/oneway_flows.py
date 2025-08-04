# -*- coding: utf-8 -*-
"""
Created on Wed Jun 11 13:22:15 2025

@author: dgrishchuk
"""

import logging
import itertools
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
    table = load_table(path,
                       extention='.csv',
                       converters=ONEWAY_FLOWS_SCHEMA)
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
        table['from_facility'].tolist() + table['to_facility'].tolist()
    )
    if not required_facilities.issubset(available_facilities):
        missing_ids = required_facilities.difference(available_facilities)
        raise RuntimeError(
            f"Oneway flows depend on these missing facilities: {missing_ids}"
        )

    if len(table) != len(table['modes'].dropna()):
        raise RuntimeError(
            f"Oneway flows can only have non-null modes in `modes` column"
        )

    return OnewayFlows(table)
