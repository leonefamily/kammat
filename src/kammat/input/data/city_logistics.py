# -*- coding: utf-8 -*-
"""
Created on Mon Dec 19 17:29:24 2022

@author: dgrishchuk
"""

from kammat.defaults.constants import (
    CITY_LOGISTICS_COLUMNS, CITY_LOGISTICS_SCHEMA
    )
from kammat.input.data.types import CityLogistics
from kammat.input.data.utils import load_table, check_columns

import logging


def load_city_logistics(
        path: str,
        ) -> CityLogistics:
    """
    # !!!

    Parameters
    ----------
    path : str
        DESCRIPTION.
     : TYPE
        DESCRIPTION.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    CityLogistics
        DESCRIPTION.

    """

    table = load_table(path, extention='.csv',
                       converters=CITY_LOGISTICS_SCHEMA)
    clcols = check_columns(table.columns.tolist(), CITY_LOGISTICS_COLUMNS)

    if clcols['missing']:
        raise RuntimeError(f"City logistics info don't contain all"
                           f" required static columns, missing:"
                           f" {clcols['missing']}")
    clcols['unexpected']
    if clcols['unexpected']:
        table.drop(clcols['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed from '
                        f'city logistics info: {clcols["unexpected"]}')

    have_base = table['service_type'][table['has_base']].tolist()
    all_types = table['service_type'].tolist()

    city_logistics = CityLogistics(table)
    city_logistics.all_types = all_types
    city_logistics.base_types = have_base
    return city_logistics
