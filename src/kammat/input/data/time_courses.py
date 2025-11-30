# -*- coding: utf-8 -*-
"""
Created on Mon Dec 19 17:30:01 2022

@author: dgrishchuk
"""

import logging
from pathlib import Path
from typing import Union, List

from kammat.input.data.types import TimeCourses
from kammat.input.data.utils import (
    load_table, check_columns, normalize_probability_columnwise
    )

from kammat.defaults.constants import (
    TIME_COURSES_COLUMNS, TIME_COURSES_SCHEMA, TIME_COURSES_MODES
    )


def load_time_courses(
        path: Union[str, Path],
        req_modes: List[str] = TIME_COURSES_MODES
        ) -> TimeCourses:
    """
    # !!!

    Parameters
    ----------
    path : Union[str, Path]
        DESCRIPTION.
    req_modes : List[str], optional
        DESCRIPTION. The default is TIME_COURSES_MODES.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    TimeCourses
        DESCRIPTION.

    """
    table = load_table(path,
                       extention='.csv',
                       converters=TIME_COURSES_SCHEMA)
    tccols = check_columns(table.columns.tolist(), TIME_COURSES_COLUMNS)

    if tccols['missing']:
        raise RuntimeError("Time courses don't contain all required "
                           f"static columns, missing: {tccols['missing']}")

    if set(table['hour'].tolist()) != set(range(24)):
        raise RuntimeError("Time courses must have hours range from 0 to 23")

    modes = [c for c in tccols['unexpected'] if c in TIME_COURSES_MODES]
    unexpected = [c for c in tccols['unexpected']
                  if c not in modes and c not in TIME_COURSES_MODES]
    if unexpected:
        table.drop(unexpected, axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from time courses: {unexpected}")

    if req_modes:
        if set(modes).difference(set(req_modes)):
            raise RuntimeError(f"Time courses must have modes: {req_modes}")

    normalize_probability_columnwise(table, modes)

    return TimeCourses(table)
