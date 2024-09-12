# -*- coding: utf-8 -*-
"""
Created on Tue Jan 17 17:42:49 2023

@author: dgrishchuk
"""

from kammat.defaults.constants import (
    RELATIONS_COLUMNS, RELATIONS_SCHEMA
    )
from kammat.input.data.types import Relations
from kammat.input.data.utils import (
    load_table, load_only_columns, check_columns,
    normalize_probability_columnwise, get_target_spatial_precision,
    fix_spatial_precisions
    )
import logging
from typing import List


def load_relations(
        path: str,
        activities: List[str]
        ) -> Relations:
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

    Returns
    -------
    Relations

    """

    cols = load_only_columns(path)
    rcols = check_columns(cols, RELATIONS_COLUMNS)

    if rcols['missing']:
        raise RuntimeError(f"Relations table doesn't contain all"
                           f" required static columns, missing:"
                           f" {rcols['missing']}")

    target_precision = get_target_spatial_precision(cols)
    if target_precision is None:
        raise RuntimeError('Relations must have target spatial precision')
    else:
        rcols['unexpected'].remove(f'{target_precision}_target')
        rcols['found'].append(f'{target_precision}_target')

    converters = {**RELATIONS_SCHEMA, f'{target_precision}_target': str}

    table = load_table(path, extention='.csv', converters=converters)
    precision = fix_spatial_precisions(table)

    if rcols['unexpected']:
        table.drop(rcols['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from relations table: {rcols['unexpected']}")

    rset = set(table['activity'].tolist())
    fset = set(activities)
    if not rset.intersection(fset):
        logging.warning('There are no common activities in facilities '
                        'and relations file')

    for spatial_unit in table[precision].unique():
        normalize_probability_columnwise(table, ['prob'],
            rows=table[table[precision] == spatial_unit].index.tolist()
            )

    relations = Relations(table)
    relations.precision = precision
    relations.target_precision = target_precision
    relations.all_activities = list(relations['activity'].unique())

    return relations
