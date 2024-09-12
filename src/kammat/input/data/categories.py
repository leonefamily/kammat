# -*- coding: utf-8 -*-
"""
Created on Sun Dec 18 15:54:06 2022

@author: dgrishchuk
"""

import logging
from pathlib import Path
from typing import Dict, Union, List

from kammat.input.data.types import Categories
from kammat.input.data.utils import (
    load_table, check_columns, fix_spatial_precisions,
    match_categories_columns, get_missing_spatial_units,
    normalize_probability_rowwise
    )
from kammat.defaults.constants import (
    CATEGORIES, CATEGORIES_COLUMNS, CATEGORIES_SCHEMA
    )


def load_categories(
        path: Union[str, Path],
        spatial_units: Dict[str, List[str]]
        ) -> Categories:
    """
    # !!!

    Parameters
    ----------
    path : Union[str, Path]
        DESCRIPTION.
    spatial_units : Dict[str, List[str]]
        DESCRIPTION.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    Categories
        DESCRIPTION.

    """
    table = load_table(path,
                       extention='.csv',
                       converters=CATEGORIES_SCHEMA)

    ccols = check_columns(table.columns.tolist(), CATEGORIES_COLUMNS)

    if ccols['missing']:
        raise RuntimeError("Categories don't contain all required "
                           f"static columns, missing: {ccols['missing']}")

    matching = match_categories_columns(ccols['unexpected'], CATEGORIES)
    if matching['difference']:
        raise RuntimeError("Categiries don't contain all required "
                           f"categories columns: {matching['difference']}")
    categories_list = ccols['unexpected']
    if matching['unexpected']:  # final unexpected
        table.drop(matching['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from categories: {matching['unexpected']}")

    precision = fix_spatial_precisions(table)
    normalize_probability_rowwise(table, categories_list)

    # insufficient spatial units
    missing_units = get_missing_spatial_units(table, precision, spatial_units)
    if missing_units:
        raise RuntimeError('There are missing spatial units in categories: '
                           f'{missing_units}')

    categories = Categories(table)
    categories.precision = precision
    categories.categories = categories_list

    return categories
