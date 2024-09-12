# -*- coding: utf-8 -*-
"""
Created on Tue Dec 13 18:06:02 2022

@author: dgrishchuk
"""

from typing import (
    Union, Dict, List, Set, Tuple, Callable, Optional, Any, Literal
    )

from pathlib import Path
import geopandas as gpd
import pandas as pd
import itertools
import re

from kammat.defaults.constants import (
    CSV_STYLE, SPATIAL_LEVELS, CATEGORIES
)

GEOMETRY_TYPES = [
    'Point',
    'PolyLine',
    'Polygon',
    'MultiPoint',
    'PointZ',
    'PolyLineZ',
    'PolygonZ',
    'MultiPointZ',
    'PointM',
    'PolyLineM',
    'PolygonM',
    'MultiPointM',
    'MultiPatch'
]

SHAPEFILE_ESSENTIALS = {'.shp': 'shapefile',
                        '.dbf': 'database file',
                        '.shx': 'index file',
                        '.prj': 'projection file'}


def corresponds_extension(
        path: Union[str, Path],
        req_extention: str = '.csv'
        ) -> bool:
    """
    Check if required extention matches the actual one

    Parameters
    ----------
    path : Union[str, Path]
        File path to check
    req_extention : str, optional
        Expected extension. The default is '.csv'.

    Returns
    -------
    bool
        Whether extention corresponds with the required

    """
    p = Path(path)
    return p.suffix == req_extention


def check_columns(
        columns: Union[Set[str], List[str], Tuple[str]],
        required: List[str]
        ) -> Dict[str, List[str]]:
    """
    Get dictionary with lists of column names that are unexpected or missing
    compared to passed strings

    Parameters
    ----------
    columns : TYPE
        DESCRIPTION.
    required: List[str]
        All column names, that are required to be in the table

    Returns
    -------
    Dict[str, List[str]]
        A dictionary with keys `unexpected`, `missing` and `found` and lists
        of columns that fall into each of those categories. Lists may be empty

    """
    colstats = {
        'unexpected': [],
        'missing': [c for c in required if c not in columns],
        'found': []
        }
    for c in columns:
        if c in required:
            colstats['found'].append(c)
        else:
            colstats['unexpected'].append(c)
    return colstats


def match_categories_columns(
        unexpected: List[str],
        categories: List[str]
        ) -> Dict[str, List[str]]:
    """
    Match categories column out of those that were flagged as `unexpected` in
    the previous step (``check_columns``)

    Parameters
    ----------
    unexpected : List[str]
        Columns flagged as `unexpected` in the results of ``check_columns``
    categories : List[str]
        Agents' categories, that diaries **must** contain

    Returns
    -------
    Dict[str, List[str]]
        Dictionary with lists in keys `difference`, `unexpected` and
        `reversed_difference`. `difference` means columns, that have to be
        in the table, but they are not. `reversed_difference` is the opposite -
        those are redundant, though valid categories columns. `unexpected` are
        the remaining columns, that don't fall in any of the described classes

    """
    matching = [c for c in unexpected if c in CATEGORIES]
    diff = list(set(categories).difference(set(matching)))
    rev_diff = list(set(matching).difference(set(categories)))
    unexp = [c for c in unexpected if c in rev_diff or c not in CATEGORIES]
    return {'difference': diff,
            'unexpected': unexp,
            'reversed_difference': rev_diff}


def get_missing_spatial_units(
        table: pd.DataFrame,
        precision: str,
        spatial_units: Dict[str, List[str]]
        ) -> List[str]:
    """
    Get spatial units, that the table does miss compared to the available ones

    Parameters
    ----------
    table : pd.DataFrame
        Helpers table
    precision: str
        Level of spatial precision
    spatial_units: Dict[str, List[str]]
        Spatial units of all home facilities for every precision

    Returns
    -------
    List[str]
        List of missing spatial units

    """
    suset = set(spatial_units[precision])
    tpset = set(table[precision].tolist())
    return list(suset.difference(tpset))


def get_missing_target_spatial_units(
        table: pd.DataFrame,
        target_precision: str,
        spatial_units: Dict[str, List[str]]
        ) -> List[str]:
    # !!!
    # check every combination of precision-target precision to be equal
    pass


def load_only_columns(
        path: Union[str, Path],
        excel_csv_style: bool = True
        ) -> List[str]:
    """
    Get only table columns names

    Parameters
    ----------
    path : Union[str, Path]
        Table path
    excel_csv_style : bool, optional
        Use excel separators and decimal points instead of pandas native ones.
        The default is True.

    Returns
    -------
    List[str]

    """
    if not excel_csv_style:
        return pd.read_csv(path, index_col=False, header=0, nrows=0).columns.tolist()
    return pd.read_csv(path, index_col=False, header=0, nrows=0, **CSV_STYLE).columns.tolist()


def load_table(
        path: Union[str, Path],
        extention: str = '.csv',
        converters: Dict[str, Callable] = None,
        excel_csv_style: bool = True
        ) -> pd.DataFrame:
    """
    Read table if extention matches expectations

    Parameters
    ----------
    path : Union[str, Path]
        Table path
    extention : str, optional
        Expected extension of the table file. The default is '.csv'
    converters: Dict[str, Callable], optional
        Converter functions for pandas.DataFrame `converters` argument
    excel_csv_style : bool, optional
        Use excel separators and decimal points instead of pandas native ones.
        The default is True.

    Raises
    ------
    RuntimeError
        If extension is unexpected

    Returns
    -------
    table : pd.DataFrame
        Helper table

    """
    if not corresponds_extension(path, extention):
        raise RuntimeError(f'File {path} must have {extention} extention')
    if excel_csv_style:
        table = pd.read_csv(path, **CSV_STYLE, converters=converters)
    else:
        table = pd.read_csv(path, converters=converters)
    # !!! add checking of empty rows
    return table


def normalize_probability_rowwise(
        table: pd.DataFrame,
        prob_cols: List[str],
        rows: List[Any] = None
        ) -> None:
    """
    Normalize all or selected rows of specified columns to 1. NaNs appeared
    after division by zero are replaced by zeros

    Parameters
    ----------
    table : pd.DataFrame
        Any DataFrame
    prob_cols : List[str]
        List of column names, whose rows should be normalized
    rows : List[Any], optional
        Rows to select. The default is None - all rows are considered

    """
    if rows is not None:
        s = table.loc[rows, prob_cols].sum(axis=1)
        repl = table.loc[rows, prob_cols].div(s, axis=0).fillna(0)
        table.loc[rows, prob_cols] = repl
    else:
        s = table.loc[:, prob_cols].sum(axis=1)
        table.loc[:, prob_cols] = table.loc[:, prob_cols].div(s, axis=0).fillna(0)


def normalize_probability_columnwise(
        table: pd.DataFrame,
        prob_cols: List[str],
        rows: List[Any] = None
        ) -> None:
    """
    Normalize selected columns to 1, optionally only by specified rows.
    NaNs appeared after division by zero are replaced by zeros

    Parameters
    ----------
    table : pd.DataFrame
        Any DataFrame
    prob_cols : List[str]
        List of column names, whose rows should be normalized
    rows : List[Any], optional
        Rows to select. The default is None - all rows are considered

    """
    for col in prob_cols:
        if rows is not None:
            s = table.loc[rows, col].sum()
            table.loc[rows, col] = table.loc[rows, col].div(s).fillna(0)
        else:
            s = table.loc[:, col].sum()
            table.loc[:, col] = table.loc[:, col].div(s).fillna(0)


def normalize_spatial_unit_probabilities_columnwise(
        table: pd.DataFrame,
        precision: str,
        prob_cols: List[str]
        ) -> None:
    """
    Normalize spatial unit probabilities in specified columns, based on
    spatial precision level. Changes are made in place.

    Parameters
    ----------
    table : pd.DataFrame
        Helpers table, that requires columnwise normalization for every level
        of spatial precision
    precision : str
        Spatial precision level
    prob_cols : List[str]
        Columns containig probabilities

    """
    for unit in table[precision].unique():
        normalize_probability_columnwise(
            table, prob_cols,
            rows=table[table[precision] == unit].index.tolist()
            )


def filter_dynamic_columns(
        columns: List[str],
        req_patterns: List[str]
        ) -> List[str]:
    """
    Filter ``columns`` according to ``req_patterns``, assuming that they end
    with digit

    Parameters
    ----------
    columns : List[str]
        Columns that should be filtered, typically the `unexpected` ones
    req_patterns : List[str]
        Pattern to match at the beginning of the string

    Returns
    -------
    List[str]
        Filtered columns

    """
    req_columns = []
    for req_pattern in req_patterns:
        for c in columns:
            if re.match(rf'{req_pattern}\d+', c):
                req_columns.append(c)
    return req_columns


def filter_optional_columns(
        columns: List[str],
        req_names: List[str]
        ) -> List[str]:
    """
    Determine, what columns are optional and not unknown.

    Parameters
    ----------
    columns : List[str]
        Columns that should be filtered, typically the `unexpected` ones
    req_names : List[str]
        Names to exactly match the string.

    Returns
    -------
    List[str]
        DESCRIPTION.

    """
    req_columns = [c for c in columns if c in req_names]
    return req_columns


def dynamic_columns_valid(
        columns: List[str],
        dyncolumns: List[str],
        min_count: int = None
        ) -> bool:
    """
    Figure out, if every dynamic column has occured at least once

    Parameters
    ----------
    columns : List[str]
        Filtered columns, that follow dynamic pattern
    dyncolumns : List[str]
        Dynamic columns patterns
    min_count : int, optional
        Minimal number of occurencies. The default is None

    Returns
    -------
    bool
        True if every dynamic column has at least one occurence

    """

    if min_count is None:
        return all(bool(c for c in columns if re.match(rf'{dc}\d+', c)) for dc in dyncolumns)

    occ = {}
    for dc in dyncolumns:
        occ[dc] = 0
        for c in columns:
            if re.match(rf'{dc}\d+', c):
                occ[dc] += 1
    return all(v >= min_count for v in occ.values())


def check_spatial_units_categories_combs(
        table: pd.DataFrame,
        precision: str,
        categories: List[str],
        spatial_units: Dict[str, List[str]],
        ignore_category_spatial_units_combs: Dict[str, List[str]] = None
        ) -> List[Tuple[str]]:
    """
    Check whether all combinations of spatial units and categoriest occure
    at least once

    Parameters
    ----------
    table : pd.DataFrame
        Helper table
    precision: str
        Spatial precision level of diaries
    categories : List[str]
        Agents' categories, that diaries **must** contain
    spatial_units : List[str]
        Spatial units of all home facilities for specified precision
    ignore_category_spatial_units_combs : Dict[str, List[str]], optional
        Categories and spatial units to be ignored when defining, if there are
        any missing ones

    Returns
    -------
    List[Tuple[str]]
        List of combinations, that aren't present in strict diaries table

    """
    combs = []
    exist = set(zip(table['category'].tolist(),
                    table[precision].tolist()))

    if ignore_category_spatial_units_combs is not None:
        staying_precision = [k for k in
                             ignore_category_spatial_units_combs.keys()
                             if k != 'category'][0]
        prec_list = ignore_category_spatial_units_combs[staying_precision]
        prec_cats = ignore_category_spatial_units_combs['category']
        units_map = dict(zip(table[precision].tolist(),
                             table[staying_precision].tolist()))
        allowed = list(zip(prec_cats, prec_list))
        for comb in itertools.product(categories,
                                      spatial_units[precision]):
            if comb not in exist and (comb[0], units_map[comb[1]]) not in allowed:
                combs.append(comb)
    else:

        for comb in itertools.product(categories, spatial_units[precision]):
            if comb not in exist:
                combs.append(comb)
    return combs


def timecols_to_timedelta(
        table: pd.DataFrame,
        timecols: List[str]
        ) -> None:
    """
    Translate string times in HH:MM:SS format to datetime.timedelta, changes
    are made in place

    Parameters
    ----------
    table : pd.DataFrame
        Any helper table
    timecols : List[str]
        List of columns, that should be translated

    Raises
    ------
    RuntimeError
        If some of columns don't have HH:MM:SS format


    """
    for timecol in timecols:
        try:
            table[timecol] = pd.to_timedelta(table[timecol])
        except ValueError:
            raise RuntimeError(f'Column {timecol} is not in HH:MM:SS format')


def group_pairs(itrbl: Union[List[Any], Tuple[Any]]) -> List[Tuple[Any]]:
    """
    Stack values pairs. Every next tuple inside the resulting list starts with
    the last value in a previous tuple. Minimum length of input iterable is 2

    Parameters
    ----------
    itrbl : Union[list, tuple]
        Any single-dimensional iterable

    Returns
    -------
    groupped : List[tuple]
        Resulting list with values paired in tuples

    """
    groupped = []
    last = None
    for el in itrbl:
        if last is not None:
            groupped.append((last, el))
        last = el
    return groupped


def get_spatial_precision(
        columns: List[str]
        ) -> Optional[str]:
    """
    Get smallest available spatial precision level. Table must be cleaned up
    from unused precisions

    Parameters
    ----------
    columns : Optional[str]
        Columns of table to be checked

    Returns
    -------
    Optional[str]
        Smallest spatial precision level string, if found. None, if not found

    """
    for sl in SPATIAL_LEVELS:
        if sl in columns:
            return sl


def get_target_spatial_precision(
        columns: List[str]
        ) -> Optional[str]:
    """
    Get smallest spatial precision level of target spatial unit

    Parameters
    ----------
    columns : Optional[str]
        Columns of table to be checked

    Returns
    -------
    Optional[str]
        Smallest target unit spatial precision level string, if found.
        None, if not found

    """
    for sl in SPATIAL_LEVELS:
        if f'{sl}_target' in columns:
            return sl


def fix_spatial_precisions(
        table: pd.DataFrame
        ) -> str:
    """
    Define and drop empty spatial columns, and get precision level

    Parameters
    ----------
    table : pd.DataFrame
        Helper table, that supports spatial context

    Raises
    ------
    RuntimeError
        - If columns has partially filled column (must be either empty or full)
        - If all spatial level columns are empty

    Returns
    -------
    str

    """
    drop, keep = [], []
    for col in SPATIAL_LEVELS:
        if table[col].isna().all() or (table[col].str.strip() == '').all():
            drop.append(col)
        elif table[col].isna().any() or (table[col].str.strip() == '').any():
            raise RuntimeError(f'Column {col} has empty values')
        else:
            keep.append(col)
    if not keep:
        raise RuntimeError('At least one spatial level has to be fully filled')
    if drop:
        table.drop(drop, axis=1, inplace=True)
    return get_spatial_precision(keep)


def probabilities_are_valid(
        table: pd.DataFrame,
        prob_cols: List[str],
        rows: List[Any] = None
        ) -> bool:
    """
    Check whether there are values, that are less than 0 or greater than 1

    Parameters
    ----------
    table : pd.DataFrame
        Any helper table, that has probabilities in columns
    prob_cols : List[str]
        Probabilities columns
    rows : List[Any], optional
        Rows to consider. The default is None

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    bool
        True, if all probabilities are valid

    """
    if rows is not None:
        vals = table.loc[rows, prob_cols].values
    else:
        vals = table[prob_cols].values

    return not ((vals > 1).any() or (vals < 0).any())


def ensure_shapefile_essentials(
        p: Path
        ) -> None:
    """
    Ensure all necessary files presence; throw an exception, if some is missing

    Parameters
    ----------
    p : Path
        Shapefile location

    Raises
    ------
    RuntimeError
        If any of the essential files doesn't exist

    """
    for suffix, description in SHAPEFILE_ESSENTIALS.items():
        essential = p.parent / (p.stem + suffix)
        if not essential.exists():
            raise RuntimeError(f"{description.capitalize()} is missing, but "
                               f"is essential for the framework: {essential}")


def get_geometry_type(
        p: Path
        ) -> str:
    """
    Get geometry type of ESRI shapefile by reading first row and checking its
    geometry type

    Parameters
    ----------
    p : Path
        Shapefile location

    Returns
    -------
    str

    """
    return gpd.read_file(p, rows=1).geometry.geom_type[0]


def load_shapefile(
        path: str,
        geometry_type: Literal[GEOMETRY_TYPES],
        **kwargs
        ) -> gpd.GeoDataFrame:
    """
    Load shapefile with control over geometry type and projection file presence

    Parameters
    ----------
    path : str
        Shapefile location
    geometry_type : Literal[GEOMETRY_TYPES]
        String of expected geometry type
    **kwargs
        Any keyword arguments ``geopandas.read_file`` accepts

    Raises
    ------
    ValueError
        If wrong expected geometry type is passed
    RuntimeError
        If expected geometry doesn't match actual

    Returns
    -------
    gpd.GeoDataFrame

    """
    if geometry_type not in GEOMETRY_TYPES:
        raise ValueError(f"'{geometry_type}' geometry type was passed, "
                         f'allowed are: {GEOMETRY_TYPES}')
    p = Path(path)
    ensure_shapefile_essentials(p)
    gtype = get_geometry_type(p)
    if gtype != geometry_type:
        raise RuntimeError(f"Expected geometry type is '{geometry_type}', "
                           f"got '{gtype}'")

    gdf = gpd.read_file(p, **kwargs)
    return gdf


def check_equal_precision(
        table: pd.DataFrame
        ):
    """
    # !!!

    Parameters
    ----------
    table : pd.DataFrame
        DESCRIPTION.

    Raises
    ------
    RuntimeError
        DESCRIPTION.

    Returns
    -------
    None.

    """
    cols = [c for c in table.columns if c in SPATIAL_LEVELS]
    combs = set(table.groupby(cols).size().to_frame()[0])
    if len(combs) != 1:
        raise RuntimeError('Data presented for different spatial precisions '
                           'are not equal: length of data for every '
                           f'combination of columns {cols} must all have same '
                           'rows count')


# def load_table_common_part(
#         path_or_table: Union[str, Path, pd.DataFrame],
#         static_columns: List[str],
#         dynamic_columns: List[str] = None,
#         schema: Dict[str, Callable] = None,
#         dynamic_cols_num: int = None,
#         name_hint: str = 'helper'
#         ) -> pd.DataFrame:
#     if isinstance(path_or_table, (str, Path)):
#         table = load_table(path_or_table,
#                            extention='.csv',
#                            converters=schema if schema is not None else None)
#     else:
#         table = path_or_table.copy()

#     columns = table.columns.tolist()
#     scols = check_columns(columns, static_columns)

#     if scols['missing']:
#         raise RuntimeError(f"{name_hint.capitalize()} don't contain all"
#                            f" required static columns, missing:"
#                            f" {scols['missing']}")

#     if dynamic_columns is not None:
#         matching = filter_dynamic_columns(scols['unexpected'], dynamic_columns)

#         if not dynamic_columns_valid(matching,
#                                      dynamic_columns,
#                                      dynamic_cols_num):
#             example = [f'{c}*' for c in dynamic_columns]
#             raise RuntimeError(f"{name_hint.capitalize()} don't contain all "
#                                f"required dynamic columns, e.g.: {example}")

#         unexpected = [c for c in scols['unexpected'] if c not in matching]
#     else:
#         unexpected = scols['unexpected']
#     if unexpected:
#         table.drop(unexpected, axis=1, inplace=True)
#         logging.warning('Unexpected columns were removed '
#                         f'from {name_hint}: {unexpected}')
#     return table

# def update_precisions(h: Dict[str, Union[pd.DataFrame, gpd.GeoDataFrame]],
#                       precisions: Dict[str, str],
#                       priority: List[str]) -> None:
#     """
#     Update spatial references precisions of every supported table accodring
#     to the data, that they contain (mostly based on columns).
#     Changes are made directly in ``precisions``.

#     Parameters
#     ----------
#     h : Dict[str, Union[pd.DataFrame, gpd.GeoDataFrame]]
#         Dictionary with helper tables, loaded from `input_data` module.
#     precisions : Dict[str, str]
#         Spatial precision levels for certain helper files

#     Raises
#     ------
#     ValueError
#         In case there are no valid spatial reference name in helper columns

#     Returns
#     -------
#     None

#     """

#     for table_name in precisions:
#         if table_name not in h:
#             continue
#         cols = h[table_name].columns
#         if table_name == 'dist_probabilities':
#             precisions[table_name] = [col.split('_')[0] for col in cols
#                                       if '_target' in col][0]            
#         else:
#             found = False
#             for pr in priority:
#                 if pr in cols:
#                     precisions[table_name] = pr
#                     found = True
#                     break
#             if not found:
#                 raise ValueError(f'"{table_name}" has no specified priority')
#             if table_name == 'modal_split':
#                 targetcol = [col.split('_')[0] for col
#                              in cols if '_target' in col]
#                 # constants['modal_target'] = False  # !!! move modal target to another function
#                 if targetcol:
#                     precisions['modal_split_target'] = targetcol[0]
#                     logging.info(f'Precision of modal_split_target is set to {targetcol[0]}')
#                     # constants['modal_target'] = True  # !!! move modal target to another function
#         logging.info(f'Precision of {table_name} is set to {precisions[table_name]}')


# def get_additional_constants(
#         facilities: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]],
#         h: Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]) -> Dict[str, str]:
#     """
#     Find out all constant patterns, that are used in the simulation

#     Parameters
#     ----------
#     facilities : Dict[str, Union[gpd.GeoDataFrame, pd.DataFrame]]
#         Dictionary with (Geo)DataFrames, containing info about
#         facilities for every available activity.
#     h : Dict[str, Union[pd.DataFrame, gpd.GeoDataFrame]]
#         Dictionary with helper tables, loaded from `input_data` module.

#     Returns
#     -------
#     Dict[str, str]
#         DESCRIPTION.

#     """

#     constants = {}

#     constants['modal_target'] = any('_target' in col for col
#                                     in h['modal_split'].columns)
#     return constants