# -*- coding: utf-8 -*-
"""
Created on Tue Jan 24 18:07:06 2023

@author: dgrishchuk
"""

import logging
import pandas as pd
from pathlib import Path
from typing import Union

from kammat.input.data.utils import (
    load_table, check_columns
    )
from kammat.defaults.constants import (
    STOPS_COLUMNS, STOPS_SCHEMA
    )


def crs_check(
        crs: str,
        table: pd.DataFrame
        ):
    # !!! TODO
    pass


def load_stops(
        path: Union[str, Path],
        crs: str = None
        ) -> pd.DataFrame:
    """
    # !!!

    Parameters
    ----------
    path : Union[str, Path]
        DESCRIPTION.
    crs : str, optional
        DESCRIPTION. The default is None.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    table : TYPE
        DESCRIPTION.

    """

    table = load_table(path,
                       extention='.txt',
                       converters=STOPS_SCHEMA,
                       excel_csv_style=False)

    scols = check_columns(table.columns.tolist(), STOPS_COLUMNS)

    if scols['missing']:
        raise RuntimeError(f"Stops table doesn't contain all"
                           f" required static columns, missing:"
                           f" {scols['missing']}")

    if scols['unexpected']:
        table.drop(scols['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from stops table: {scols['unexpected']}")

    table.rename({'stop_lon': 'x', 'stop_lat': 'y'}, axis=1, inplace=True)

    return table
