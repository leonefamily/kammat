# -*- coding: utf-8 -*-
"""
Created on Tue Dec 20 15:04:25 2022

@author: dgrishchuk
"""

import logging
from typing import List
from kammat.defaults.constants import (
    INDICES_COLUMNS, INDICES_SCHEMA
    )
from kammat.input.data.types import Indices
from kammat.input.data.utils import (
    load_table, check_columns
)


def load_indices(
        path: str,
        activities: List[str]
        ) -> Indices:
    """
    # !!!

    Parameters
    ----------
    path : str
        DESCRIPTION.
    activities : List[str]
        DESCRIPTION.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    Indices
        DESCRIPTION.

    """

    table = load_table(path, extention='.csv', converters=INDICES_SCHEMA)
    icols = check_columns(table.columns.tolist(), INDICES_COLUMNS)

    if icols['missing']:
        raise RuntimeError(f"Times table doesn't contain all"
                           f" required static columns, missing:"
                           f" {icols['missing']}")

    if icols['unexpected']:
        table.drop(icols['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from modal split table: {icols['unexpected']}")

    iset = set(table['activity'].tolist())
    fset = set(activities)
    if not iset.intersection(fset):
        logging.warning('There are no common activities in facilities '
                        'and indices file')
    # for act in iset:
    #     normalize_probability_columnwise(
    #         table,
    #         prob_cols=['prob'],
    #         rows=table[table['activity'] == act].index.tolist()
    #     )
    return Indices(table)
