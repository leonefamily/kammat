# -*- coding: utf-8 -*-
"""
Created on Fri Dec 16 16:31:11 2022

@author: dgrishchuk
"""

from kammat.defaults.constants import STAYING_COLS, STAYING_SCHEMA

from kammat.input.data.types import Staying
from kammat.input.data.utils import (
    load_table, fix_spatial_precisions, probabilities_are_valid, check_columns,
    match_categories_columns, get_missing_spatial_units
    )
import logging
import numpy as np
from typing import Dict, List


def get_staying_category_spatial_unit_combinations(
        staying: Staying
        ) -> Dict[str, List[str]]:
    """
    Get combinations of category and spatial unit that are ALL staying home
    and so the affected spatial precision level doesn't have to have a strict
    diary

    Parameters
    ----------
    staying : Staying
        Staying table with `precision` attribute defined

    Returns
    -------
    Dict[str, List[str]]

    """
    idx, cols = np.where(staying == 1)
    if staying.precision is None:
        raise RuntimeError('Precision has to be set in staying table')
    return {
        staying.precision: staying[staying.precision].loc[idx].tolist(),
        'category': staying.columns[cols].tolist()
        }


def load_staying(
        path: str,
        categories: List[str],
        spatial_units: Dict[str, List[str]]
        ) -> Staying:
    """
    Load, check and prepare info about what percentage of people stays at home
    depending on the level of spatial precision they are from.
    Table of `staying` is used with strict diaries

    Parameters
    ----------
    path : str
        Path to the table of staying
    categories : List[str]
        Agents' categories, that diaries **must** contain
    spatial_units: Dict[str, List[str]]
        Spatial units of all home facilities for every precision

    Returns
    -------
    Staying

    """
    table = load_table(path, extention='.csv', converters=STAYING_SCHEMA)
    columns = table.columns.tolist()
    stcols = check_columns(columns, STAYING_COLS)

    if stcols['missing']:
        raise RuntimeError("Staying table doesn't contain all required "
                           f" static columns, missing: {stcols['missing']}")

    matching = match_categories_columns(stcols['unexpected'], categories)
    if matching['difference']:
        raise RuntimeError("Staying table doesn't contain all required "
                           f"categories columns: {matching['difference']}")
    if matching['unexpected']:  # final unexpected
        table.drop(matching['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from staying table: {matching['unexpected']}")

    valid_probs = probabilities_are_valid(table, prob_cols=categories)
    if not valid_probs:
        raise RuntimeError('Some probabilities are not in the interval'
                           'in staying table [0;1]')

    precision = fix_spatial_precisions(table)

    missing_units = get_missing_spatial_units(table, precision, spatial_units)
    if missing_units:
        raise RuntimeError('There are missing combinations in staying '
                           f'table: {missing_units}')

    staying = Staying(data=table)
    staying.precision = precision
    return staying
