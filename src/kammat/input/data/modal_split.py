# -*- coding: utf-8 -*-
"""
Created on Mon Dec 19 17:30:22 2022

@author: dgrishchuk
"""


from kammat.defaults.constants import (
    MODAL_SPLIT_COLUMNS, MODAL_SPLIT_SCHEMA, MODES
    )
from kammat.input.data.types import ModalSplit
from kammat.input.data.utils import (
    load_table, load_only_columns, check_columns, fix_spatial_precisions,
    get_target_spatial_precision, get_missing_spatial_units
)
import logging
from typing import Dict, List


def load_modal_split(
        path: str,
        categories: List[str],
        activities: List[str],
        spatial_units: Dict[str, List[str]],
        target_spatial_units: Dict[str, List[str]] = None
        ) -> ModalSplit:
    """
    # !!!

    Parameters
    ----------
    path : str
        DESCRIPTION.
    categories : List[str]
        DESCRIPTION.
    activities : List[str]
        DESCRIPTION.
    spatial_units : Dict[str, List[str]]
        DESCRIPTION.
    target_spatial_units : Dict[str, List[str]], optional
        DESCRIPTION. The default is None.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    ModalSplit
        DESCRIPTION.

    """

    cols = load_only_columns(path)
    dcols = check_columns(cols, MODAL_SPLIT_COLUMNS)

    if dcols['missing']:
        raise RuntimeError(f"Distances don't contain all"
                           f" required static columns, missing:"
                           f" {dcols['missing']}")

    target_precision = get_target_spatial_precision(cols)
    if target_precision is not None:
        dcols['unexpected'].remove(f'{target_precision}_target')
        dcols['found'].append(f'{target_precision}_target')

    converters = {**MODAL_SPLIT_SCHEMA, f'{target_precision}_target': str}

    table = load_table(path, extention='.csv', converters=converters)
    precision = fix_spatial_precisions(table)
    modes = [m for m in dcols['unexpected'] if m in MODES]
    unexpected = [c for c in dcols['unexpected'] if c not in modes]

    if unexpected:
        table.drop(unexpected, axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f'from modal split table: {unexpected}')

    missing_units = get_missing_spatial_units(table, precision, spatial_units)
    if missing_units:
        raise RuntimeError(f'"{precision}" in distances misses some'
                           f' units: {missing_units}')

    if target_precision is not None:
        missing_target = get_missing_spatial_units(table,
                                                   target_precision,
                                                   spatial_units)
        if missing_target:
            raise RuntimeError('Target "{target_precision}" in modal split table'
                               'misses units: {missing_target}')

    modal_split = ModalSplit(table)
    modal_split.precision = precision
    modal_split.target_precision = target_precision

    return modal_split
