# -*- coding: utf-8 -*-
"""
Created on Mon Dec 19 17:28:55 2022

@author: dgrishchuk
"""

from kammat.defaults.constants import (
    TIMES_COLUMNS, TIMES_SCHEMA
)
from kammat.input.data.types import Times
from kammat.input.data.utils import (
    load_table, check_columns, fix_spatial_precisions,
    get_missing_spatial_units, check_equal_precision
)
import logging
from typing import Dict, List


def load_times(
        path: str,
        activities: List[str],
        spatial_units: Dict[str, List[str]]
        ) -> Times:

    table = load_table(path, extention='.csv',
                       converters=TIMES_SCHEMA)
    tcols = check_columns(table.columns.tolist(), TIMES_COLUMNS)

    if tcols['missing']:
        raise RuntimeError(f"Times table doesn't contain all"
                           f" required static columns, missing:"
                           f" {tcols['missing']}")

    if tcols['unexpected']:
        table.drop(tcols['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from times table: {tcols['unexpected']}")

    precision = fix_spatial_precisions(table)

    check_equal_precision(table)

    missing_units = get_missing_spatial_units(table, precision, spatial_units)
    if missing_units:
        raise RuntimeError('There are missing combinations in times'
                           f'table: {missing_units}')

    times = Times(table)
    times.precision = precision
    return times
