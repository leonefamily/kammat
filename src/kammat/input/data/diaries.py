# -*- coding: utf-8 -*-
"""
Created on Tue Dec 13 17:49:41 2022

@author: dgrishchuk
"""

import re
import logging
import itertools
import pandas as pd
from pathlib import Path
from typing import Dict, Union, List, Tuple

from kammat.input.data.types import Diaries
from kammat.input.data.utils import (
    load_table, check_columns, normalize_spatial_unit_probabilities_columnwise,
    check_spatial_units_categories_combs, timecols_to_timedelta,
    filter_dynamic_columns, dynamic_columns_valid, fix_spatial_precisions,
    match_categories_columns, get_missing_spatial_units, group_pairs,
    filter_optional_columns
    )
from kammat.defaults.constants import (
    DIARIES_COLS,
    STRICT_DIARIES_STATIC_COLS,
    STRICT_DIARIES_DYNAMIC_COLS,
    STRICT_DIARIES_OPTIONAL_COLS,
    STRICT_DIARIES_TIME_COLS,
    STRICT_DIARIES_INGORE_CATEGORIES,
    SPATIAL_LEVELS_SCHEMA
    )


def get_diaries_type(
        columns: List[str]
        ) -> str:
    """
    Define, whether diaries are `strict` or `non-strict` based on columns.
    If columns don't match any format, `wrong` is returned

    Parameters
    ----------
    columns : List[str]
        Diaries table columns

    Returns
    -------
    str
        Diaries type

    """
    if set(c for c in columns if c in STRICT_DIARIES_STATIC_COLS) == set(STRICT_DIARIES_STATIC_COLS):
        return 'strict'
    elif set(c for c in columns if c in DIARIES_COLS) == set(DIARIES_COLS):
        return 'non-strict'
    return 'wrong'


def get_maximum_diaries_length(
        table: pd.DataFrame
        ) -> int:
    """
    Get maximum length of activities chain in a table of diaries. `activities`
    column must contain lists in the cells

    Parameters
    ----------
    table : pd.DataFrame
        Diaries table

    Returns
    -------
    int
        Maximum length of diaries

    """
    return table['activities'].apply(lambda x: len(x)).max()


def get_unmatching_lastings_counts(
        table: pd.DataFrame
        ) -> List[int]:
    """
    Make sure, that all activities (except for first and last activity),
    have their lasting

    Parameters
    ----------
    table : pd.DataFrame
        Diaries table, `activities` column must contain lists

    Returns
    -------
    List[int]
        List with row numbers, where there are unmatching lengths

    """
    cols = [c for c in table.columns if re.match(r'lasting\d+', c)]
    lastings = table[cols].apply(lambda r: r[~r.isna()].shape[0], axis=1)
    lens = table['activities'].apply(lambda r: len(r) - 2)
    return lastings.compare(lens).index.tolist()


def has_activity_separators(
        table: pd.DataFrame
        ) -> bool:
    """
    Figure out if all activities have separators (e.g. length is at least two)

    Parameters
    ----------
    table : pd.DataFrame
        Diaries table with string `activities` column

    Returns
    -------
    bool
        True if has activity separators

    """
    return table['activities'].str.contains('_').all()


def get_undescribed_activities(
        table: pd.DataFrame,
        activities: List[str]
        ) -> Dict[str, List[str]]:
    """
    Get activities, that are in diaries, but are not in facilities or aren't
    described anywhere else

    Parameters
    ----------
    table : pd.DataFrame
        Diaries table
    activities : List[str]
        Activities from facilities / descriptions, that either imply direct
        facility visit or divert to other existing facilities. Lower case only

    Returns
    -------
    Tuple[List[str]]
        A tuple with undescribed and described activities

    """
    try:
        all_acts = set(itertools.chain.from_iterable(table['activities'].tolist()))
    except TypeError:
        raise RuntimeError(
            'NaN is probably encountered in strict diaries activities column. '
            'Check if all of them are in place'
        )
    acts_set = {c.lower() for c in all_acts}
    described = set(a.lower() for a in activities if isinstance(a, str))
    return {
        'undescribed': list(acts_set.difference(described)),
        'described': list(described),
        'described_mixed': list(all_acts)
        }


def set_strict_diaries_timedelta(
        table: pd.DataFrame
        ):
    """
    Translate string times of strict diaries in HH:MM:SS format to
    datetime.timedelta, changes are made in place

    Parameters
    ----------
    table : pd.DataFrame
        Strict diaries table

    """
    timecols = [c for c in table.columns if
                any(re.match(rf'{d}\d+', c) for d in STRICT_DIARIES_TIME_COLS)]
    timecols_to_timedelta(table, timecols)


def get_activities_pairs(
        activities_chains: List[List[str]]
        ) -> List[Tuple[str]]:
    """
    Get all possible activities pairs from diaries in lowercase

    Parameters
    ----------
    activities_chains : List[List[str]]
        List of full activities chains

    Returns
    -------
    List[Tuple[str]]

    """
    pairs = set()
    for chain in set(tuple(chain) for chain in activities_chains):
        pairs.update(group_pairs([el.lower() for el in chain]))
    return list(pairs)


def handle_strict_diaries(
        table: pd.DataFrame,
        activities: List[str],
        categories: List[str],
        spatial_units: Dict[str, List[str]],
        ignore_category_spatial_units_combs: Dict[str, List[str]] = None
        ) -> Dict[str, str]:
    """
    Change diaries according to strict pattern and throw ``RuntimeErrors``,
    if there are issues.

    Strict diaries are used for explicit time definitions. They must have
    certain spatial precision and agent's category. There must be at least one
    diary for every spatial unit and agent's category combination.
    Strict diaries contain information about second activity start time and
    lastings of every next, except for the last one.
    If a diary has only two activities (minimum length for strict diaries),
    only time of arrival to second activity is obligatory.

    Parameters
    ----------
    table : pd.DataFrame
        Strict diaries table
    activities : List[str]
        Activities from facilities / descriptions, that either imply direct
        facility visit or divert to other existing facilities. Lower case only
    categories : List[str], optional
        Agents' categories, that diaries **must** contain
    spatial_units: Dict[str, List[str]]
        Spatial units of all home facilities for every precision
    ignore_category_spatial_units_combs : Dict[str, List[str]], optional
        Categories and spatial units to be ignored when defining, if there are
        any missing ones

    Raises
    ------
    RuntimeError
        - If diaries dont't have mandatory columns
        - If activities aren't separated with underscores (or single activity)
        - If lastings count are not matches with activities count
        - If has activities, that weren't defined anywhere else
        - If time columns are in bad format
        - If diaries are not listed for some spatial unit/category combination

    Returns
    -------
    Dict[str, str]
        Metadata about strict diaries (type, level of precision)

    """
    columns = table.columns.tolist()
    scols = check_columns(columns, STRICT_DIARIES_STATIC_COLS)

    if scols['missing']:
        raise RuntimeError("Strict diaries don't contain all required static"
                           f" columns, missing: {scols['missing']}")

    matching = filter_dynamic_columns(scols['unexpected'],
                                      STRICT_DIARIES_DYNAMIC_COLS)

    if not dynamic_columns_valid(matching, STRICT_DIARIES_DYNAMIC_COLS):
        example = [f'{c}*' for c in STRICT_DIARIES_DYNAMIC_COLS]
        raise RuntimeError("Strict diaries don't contain all required dynamic"
                           f" columns, e.g.: {example}")

    optional = filter_optional_columns(columns, STRICT_DIARIES_OPTIONAL_COLS)
    unexpected = [c for c in scols['unexpected'] if c not in matching and c not in optional]
    if unexpected:
        table.drop(unexpected, axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f'from strict diaries: {unexpected}')

    if not has_activity_separators(table):
        raise RuntimeError("Separators weren't found in some strict"
                           " diaries' activities. Probably forgot to separate"
                           " activities with underscores?")

    table['activities'] = table['activities'].str.split('_')

    # undescribed activities
    acts = get_undescribed_activities(table, activities)

    # compare lengths of activities and their lastings
    unmatching_lens = get_unmatching_lastings_counts(table)
    if unmatching_lens:
        raise RuntimeError("Lastings count doesn't match activities count in"
                           f" strict diaries, rows: {unmatching_lens}")

    precision: str = fix_spatial_precisions(table)  # drops empty columns

    # insufficient combinations
    not_ignored = [cat for cat in categories
                   if cat not in STRICT_DIARIES_INGORE_CATEGORIES]
    unmatching_combs = check_spatial_units_categories_combs(
        table, precision, not_ignored, spatial_units,
        ignore_category_spatial_units_combs
        )
    if unmatching_combs:
        raise RuntimeError(f'There are missing category-{precision} '
                           'combinations in strict '
                           f'diaries: {unmatching_combs}')

    set_strict_diaries_timedelta(table)

    return {
        'type': 'strict',
        'precision': precision,
        'all_activities': acts['described_mixed'],
        }


def handle_non_strict_diaries(
        table: pd.DataFrame,
        activities: List[str],
        categories: List[str],
        spatial_units: Dict[str, List[str]]
        ) -> Dict[str, str]:
    """
    Change diaries according to non-strict pattern and throw ``RuntimeErrors``,
    if there are issues.

    Non-strict diaries are used, when there are only probabilities for agents
    from particular spatial units, with which they will pick certain diary.
    Probabilities don't have to be in relative numbers, they are normalized

    Parameters
    ----------
    table : pd.DataFrame
        Non-strict diaries table
    activities : List[str]
        Activities from facilities / descriptions, that either imply direct
        facility visit or divert to other existing facilities. Lower case only
    categories : List[str]
        Agents' categories, that diaries **must** contain
    spatial_units: Dict[str, List[str]]
        Spatial units of all home facilities for every precision

    Raises
    ------
    RuntimeError
        - If diaries dont't have mandatory columns
        - If has activities, that weren't defined anywhere else
        - If diaries are not listed for some spatial unit/category combination

    """
    nscols = check_columns(table.columns.tolist(), DIARIES_COLS)

    if nscols['missing']:
        raise RuntimeError("Non-strict diaries don't contain all required "
                           f"static columns, missing: {nscols['missing']}")

    matching = match_categories_columns(nscols['unexpected'], categories)
    if matching['difference']:
        raise RuntimeError("Non-strict diaries don't contain all required "
                           f"categories columns: {matching['difference']}")
    if matching['unexpected']:  # final unexpected
        table.drop(matching['unexpected'], axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f"from non-strict diaries: {matching['unexpected']}")

    table['activities'] = table['activities'].str.split('_')

    acts = get_undescribed_activities(table, activities)

    precision = fix_spatial_precisions(table)  # drops empty columns
    normalize_spatial_unit_probabilities_columnwise(table,
                                                    precision,
                                                    categories)

    # insufficient spatial units
    missing_units = get_missing_spatial_units(table, precision, spatial_units)
    if missing_units:
        raise RuntimeError('There are missing combinations in non-strict '
                           f'diaries: {missing_units}')
    return {
        'type': 'non-strict',
        'precision': precision,
        'all_activities': acts['described_mixed']
        }


def load_diaries(
        path: Union[str, Path],
        activities: List[str],
        categories: List[str],
        spatial_units: Dict[str, List[str]],
        ignore_category_spatial_units_combs: Dict[str, List[str]] = None
        ) -> Diaries:
    """
    Load, check and prepare diaries

    Parameters
    ----------
    path : Union[str, Path]
        Path to the diaries table
    activities : List[str]
        List of all available activities, if there are no unexpected in diaries
    categories : List[str]
        Agents' categories, that diaries **must** contain
    spatial_units: Dict[str, List[str]]
        Spatial units of all home facilities for every precision
    ignore_category_spatial_units_combs : Dict[str, List[str]], optional
        Categories and spatial units to be ignored when defining, if there are
        any missing ones. The default is None, nut has to be defined, if
        diaries are strict

    Raises
    ------
    RuntimeError
        If diaries format is not recognized, data are wrong or diaries contain
        activities, that are not in list

    Returns
    -------
    Diaries

    """
    table = load_table(path,
                       extention='.csv',
                       converters=SPATIAL_LEVELS_SCHEMA)
    diaries_type = get_diaries_type(table.columns.tolist())

    if diaries_type == 'non-strict':
        metadata = handle_non_strict_diaries(table, activities,
                                             categories, spatial_units)
    elif diaries_type == 'strict':
        metadata = handle_strict_diaries(table, activities,
                                         categories, spatial_units,
                                         ignore_category_spatial_units_combs)
    else:
        raise RuntimeError("Diaries format doesn't match "
                           "strict or non-strict pattern")

    diaries = Diaries(data=table)
    diaries.set_metadata(metadata)
    return diaries
