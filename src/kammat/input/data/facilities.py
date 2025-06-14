# -*- coding: utf-8 -*-
"""
Created on Thu Dec 15 18:43:12 2022

@author: dgrishchuk
"""

import re
import logging
import numpy as np
import pandas as pd
import geopandas as gpd
from scipy import stats
from shapely.geometry import Point
from typing import List, Tuple, Dict, Union, Callable
from kammat.defaults.constants import (
    SPATIAL_LEVELS, TRANSIT_MODES, MODES,
    FACILITIES_COLUMNS, FACILITIES_SCHEMA,
    CLUSTERS_COLUMNS, CLUSTERS_SCHEMA,
    TRANSIT_POINTS_STATIC_COLUMNS, TRANSIT_POINTS_SCHEMA,
    FREIGHT_POINTS_STATIC_COLUMNS, FREIGHT_POINTS_SCHEMA,
    CITYLOG_POINTS_COLUMNS, CITYLOG_POINTS_SCHEMA
    )
from kammat.input.data.utils import (
    load_shapefile, check_columns, fix_spatial_precisions,
    filter_dynamic_columns, dynamic_columns_valid
    # !!! get_missing_spatial_units?
    )

from kammat.defaults.variables import Variables

v = Variables()


def assign_facilities_clusters(
        facilities_gdf: gpd.GeoDataFrame,
        clusters: gpd.GeoDataFrame
        ):
    """
    Define which facilities lie on clusters and thus have to be preferred
    during agents processing. Assignment is done in place

    Parameters
    ----------
    facilities_gdf : gpd.GeoDataFrame
        All facilities table
    clusters : gpd.GeoDataFrame
        CLusters table

    """
    for fid, row in clusters.iterrows():
        act_cond = facilities_gdf['activity'] == row['activity']
        geo_cond = facilities_gdf.within(row.geometry)
        facilities_gdf.loc[act_cond & geo_cond, 'cluster_id'] = fid + 1


def load_clusters(
        clusters_path: str,
        activities: List[str] = None
        ) -> gpd.GeoDataFrame:
    """
    Load and check clusters file

    Parameters
    ----------
    clusters_path : str
        Clusters file location
    activities : List[str], optional
        DESCRIPTION. The default is None.

    Raises
    ------
    RuntimeError
        If there is not every required static column

    Returns
    -------
    gpd.GeoDataFrame

    """
    clusters = load_shapefile(clusters_path, 'Polygon')

    ccols = check_columns(clusters.columns.tolist(), CLUSTERS_COLUMNS)
    if ccols['missing']:
        raise RuntimeError("Clusters don't contain all required "
                           f"static columns, missing: {ccols['missing']}")

    clusters = clusters.astype(CLUSTERS_SCHEMA)

    if activities is not None:
        cset = set(clusters['activity'].tolist())
        fset = set(activities)
        if not cset.intersection(fset):
            logging.warning('There are no common activities in facilities '
                            'and clusters file')

    return clusters


def unpack_regular_facilities(
        facilities_gdf: gpd.GeoDataFrame
        ) -> Dict[str, gpd.GeoDataFrame]:
    """
    Turn GeoDataFrame of every activity into dictionary. Only regular
    (with standard columns layout) activities are supported.

    Parameters
    ----------
    facilities_gdf : gpd.GeoDataFrame
        GeoDataFrame with ALL facilities (as it was loaded)

    Returns
    -------
    Dict[str, gpd.GeoDataFrame]

    """
    facilities = {}

    for act in facilities_gdf['activity'].unique():
        act_idx = facilities_gdf['activity'] == act
        f_idx = range(len(facilities_gdf[act_idx]))
        if 'facility' in facilities_gdf.columns:
            # assign IDs only where there is nothing else
            nonempty_idx = facilities_gdf[act_idx].loc[
                facilities_gdf[act_idx]['facility'].isna(),
                'facility'
            ].index
            facilities_gdf.loc[nonempty_idx, 'facility'] = [
                act + str(i) for i in range(len(nonempty_idx))
            ]
        else:
            facilities_gdf.loc[act_idx, 'facility'] = [act + str(i) for i in f_idx]
        # set names for all facilities
        facilities[act] = facilities_gdf[act_idx]
    return facilities


def get_spatial_units(
        gdf: gpd.GeoDataFrame
        ) -> Dict[str, List[str]]:
    """
    Extract all spatial units that are present in a certain activity's
    facilities table (not from the facilities dictionary!)

    Parameters
    ----------
    gdf : gpd.GeoDataFrame
        Single activity facilities table

    Returns
    -------
    Dict[str, List[str]]

    """
    return {su: list(sorted(gdf[su].unique())) for su in SPATIAL_LEVELS}


def ensure_square_od_matrix(
        tpoints_gdf: gpd.GeoDataFrame,
        facility_columns: List[str]
        ):
    """
    Raise RuntimeError, if number of transit columns is not equal to number
    of rows for each mode

    Parameters
    ----------
    tpoints_gdf : gpd.GeoDataFrame
        Transit points table
    facility_columns : List[str]
        Columns that have facilities names

    Raises
    ------
    RuntimeError

    """
    for mode, gdf in tpoints_gdf.groupby('mode'):
        if set(gdf['facility']) != set(facility_columns):
            raise RuntimeError(f"Mode '{mode}' doesn't have square OD matrix "
                               "in transit points. Facilities and column "
                               " names don't match")


def has_only_supported_modes(
        table: Union[gpd.GeoDataFrame, pd.DataFrame],
        modes: List[str] = MODES,
        mode_col: str = 'mode'
        ) -> bool:
    """
    Check if tthere are not unallowed modes

    Parameters
    ----------
    table : Union[gpd.GeoDataFrame, pd.DataFrame]
        Any table with modes related column
    mode_col : str, optional
        Column that contains used modes. The default is 'mode'

    Returns
    -------
    bool

    """
    return table[mode_col].isin(modes).all()


def load_transit_points(
        transit_points_path: str
        ) -> gpd.GeoDataFrame:
    """
    Load, check and reformat transit points file

    Parameters
    ----------
    transit_points_path : str
        Transit points location

    Raises
    ------
    RuntimeError
        If modes specified in the table are unsupported

    Returns
    -------
    gpd.GeoDataFrame

    """
    tpoints_gdf = load_facilities_common_part(
        transit_points_path,
        static_columns=TRANSIT_POINTS_STATIC_COLUMNS,
        dynamic_columns=[v.acts['transit']],
        dynamic_cols_num=2,
        schema=TRANSIT_POINTS_SCHEMA,
        name_hint='transit points'
        )

    if not has_only_supported_modes(tpoints_gdf, modes=TRANSIT_MODES):
        raise RuntimeError("There are unsupported modes in transit points. "
                           f"Supported modes are: {TRANSIT_MODES}")

    ensure_square_od_matrix(tpoints_gdf,  # raises error
                            [c for c in tpoints_gdf.columns
                             if c not in TRANSIT_POINTS_STATIC_COLUMNS])

    return tpoints_gdf


def load_facilities_common_part(
        path: str,
        static_columns: List[str],
        dynamic_columns: List[str] = None,
        schema: Dict[str, Callable] = None,
        dynamic_cols_num: int = None,
        name_hint: str = 'facilities'
        ) -> gpd.GeoDataFrame:
    """
    Initial processing for every `facility` related shapefile, which is common
    for every of them.

    Parameters
    ----------
    path : str
        Path to the table derived from facililies
    static_columns : List[str]
        Mandatory columns for the table
    dynamic_columns : List[str], optional
        Dynamic columns of table (have digits on the end). The default is None
    schema : Dict[str, Callable], optional
        Schema to call .astype() on GeoDataFrame. The default is None
    dynamic_cols_num : int, optional
        Minimum count of dynamic columns to consider them valid.
        The default is None
    name_hint : str, optional
        If error is raised, how to call table, that is being processed.
        The default is 'facilities'

    Raises
    ------
    RuntimeError
        - If some of static columns are missing
        - If some of dynamic columns are missing, or not enough of them
        - If got wrong precision (must be `zone`)

    Returns
    -------
    gpd.GeoDataFrame

    """

    gdf = load_shapefile(path, 'Point')

    mcols = check_columns(gdf.columns.tolist(), static_columns)

    if mcols['missing']:
        raise RuntimeError(f"{name_hint} don't contain all required "
                           f"static columns, missing: {mcols['missing']}")

    if schema is not None:
        gdf = gdf.astype(schema)

    precision = fix_spatial_precisions(gdf)
    if precision != 'zone':
        raise RuntimeError("Transit points spatial precision level must be "
                           f"'zone', got '{precision}'")

    if dynamic_columns is not None:
        matching = filter_dynamic_columns(mcols['unexpected'], dynamic_columns)

        if not dynamic_columns_valid(matching,
                                     dynamic_columns,
                                     min_count=dynamic_cols_num):
            if dynamic_cols_num is not None:
                raise RuntimeError(f"There must be al least {dynamic_cols_num}"
                                   f" columns in every set in {name_hint}: "
                                   f"{dynamic_columns} missing")
            raise RuntimeError(f"There are not enough dynamic columns"
                               f" columns in every set in {name_hint}: "
                               f"{dynamic_columns} missing")

        unexpected = [c for c in mcols['unexpected'] if c not in matching]
    else:
        unexpected = mcols['unexpected']

    if unexpected:
        gdf.drop(unexpected, axis=1, inplace=True)
        logging.warning('Unexpected columns were removed '
                        f'from {name_hint}: {unexpected}')
    return gdf


def load_freight_points(
        freight_points_path: str
        ) -> gpd.GeoDataFrame:
    """
    Load, check and format freight points

    Parameters
    ----------
    freight_points_path : str
        Freight points location

    Raises
    ------
    RuntimeError
        If points have wrong activity

    Returns
    -------
    gpd.GeoDataFrame

    """
    fpoints_gdf = load_facilities_common_part(
        freight_points_path,
        static_columns=FREIGHT_POINTS_STATIC_COLUMNS,
        dynamic_columns=[v.acts['transit']],
        schema=FREIGHT_POINTS_SCHEMA,
        name_hint='freight points')

    fpoints_gdf['mode'] = 'truck'  # only truck mode is for freight

    if not all(re.match(rf'{v.acts["freight"]}\d+', fp)
               for fp in fpoints_gdf['facility']):
        raise RuntimeError('Freight points have wrong activity type, '
                           f'must be "{v.acts["freight"]}*"')
    return fpoints_gdf


def load_citylog_points(
        citylog_points_path: str
        ) -> gpd.GeoDataFrame:
    """
    Load and check city logistics points

    Parameters
    ----------
    citylog_points_path : str
        City logistics points location

    Returns
    -------
    gpd.GeoDataFrame

    """

    cpoints_gdf = load_facilities_common_part(
        citylog_points_path,
        static_columns=CITYLOG_POINTS_COLUMNS,
        schema=CITYLOG_POINTS_SCHEMA,
        name_hint='city logistics points'
        )

    cpoints_gdf['facility'] = [f'{v.acts["citylog"]}{i}'
                               for i in range(len(cpoints_gdf))]

    return cpoints_gdf


def constants_to_cols(
        facilities: Dict[str, gpd.GeoDataFrame],
        write_xy: bool = True,
        write_center_dist: bool = True,
        center_coords: Tuple[float] = None
        ):
    """
    Write essential constants to facilities of all activiites, such as distance
    to the center, that never changes, or simple coordinates (not Point object,
    which is extremely slow). Changes are made in place

    Parameters
    ----------
    facilities : Dict[str, gpd.GeoDataFrame]
        Dictionary with facilities
    write_xy : bool, optional
        Whether to write coordinates other than Point obj. The default is True.
    write_center_dist : bool, optional
        Whether to write distance to center. The default is True.

    """
    for act in facilities:
        if write_xy:
            facilities[act]['x'] = facilities[act]['geometry'].apply(lambda r: r.coords[0][0])
            facilities[act]['y'] = facilities[act]['geometry'].apply(lambda r: r.coords[0][1])
        if write_center_dist:
            facilities[act]['center_dist'] = (
                facilities[act]['geometry'].distance(Point(center_coords))
                )


def get_city_center(
        facilities: Dict[str, gpd.GeoDataFrame],
        capacity_affected: List[str],
        consider_capacity: bool = True
        ) -> Tuple[float]:
    """
    Get city center using Gaussian Kernel Density Estimation (KDE). Specified
    activities' facilities are weighted by their capacity.

    Parameters
    ----------
    facilities : Dict[str, gpd.GeoDataFrame]
        Facilities in a dictionary
    capacity_affected : List[str]
        Names of activities containing info about capacity, that is reducible
    consider_capacity : bool, optional
        Whether to consider weight during KDE analysis. The default is True

    Returns
    -------
    Tuple[float]
        x, y coordinates in input CRS

    """

    xs, ys, weights = [], [], []

    for act, f_gdf in facilities.items():
        if act in capacity_affected:
            city_f_gdf = f_gdf[f_gdf['region'] == 'city']
            xs.extend(city_f_gdf['geometry'].apply(lambda r: r.coords[0][0]))
            ys.extend(city_f_gdf['geometry'].apply(lambda r: r.coords[0][1]))
            weights.extend(city_f_gdf['capacity'].tolist())

    xys = np.vstack([xs, ys])
    kde = stats.gaussian_kde(
        xys, weights=weights if consider_capacity else None
    )
    density = kde(xys)

    return tuple(xys.transpose()[np.argmax(density)])


def split_facilities(
        facilities: Dict[str, gpd.GeoDataFrame],
        pieces: int = 6
        ) -> Dict[str, gpd.GeoDataFrame]:
    """
    # !!!

    Parameters
    ----------
    facilities : TYPE
        DESCRIPTION.
    pieces : TYPE, optional
        DESCRIPTION. The default is 6.

    Returns
    -------
    outdict : TYPE
        DESCRIPTION.

    """
    v = Variables()
    outdict = {num: {} for num in range(pieces)}
    for act, df in facilities.items():
        if act in v.capacity_affected:
            newdf = df.copy()
            # try to equally split
            newdf['quotient'], newdf['remainder'] = newdf['capacity'].divmod(pieces)

            for num in range(pieces):
                newdf[f'remainder{num}'] = 0

            # if split wasn't equal, randomize remainder
            for ind in newdf[newdf['remainder'] != 0].index:
                # randomly assign one to some remainder columns
                # but max only once per column
                to_put = np.random.choice(range(pieces),
                                          newdf.loc[ind].remainder,
                                          replace=False)
                cols = [f'remainder{put}' for put in to_put]
                newdf.loc[ind, cols] = 1

            for num in range(pieces):
                part_df = newdf.copy()
                part_df['capacity'] = part_df['quotient'] + part_df[f'remainder{num}']
                dropcols = [c for c in part_df.columns
                            if 'remainder' in c or 'quotient' in c]
                part_df = part_df[part_df['capacity'] != 0]
                outdict[num].update({act: part_df.drop(dropcols, axis=1)})

        else:
            for num in range(pieces):
                outdict[num].update({act: df})
        logging.info(f'Act {act} facilities splitted')
    return outdict


def load_facilities(
        facilities_path: str,
        clusters_path: str = None,
        transit_points_path: str = None,
        freight_points_path: str = None,
        citylog_points_path: str = None
        ) -> Dict[str, gpd.GeoDataFrame]:
    """
    # !!!

    Parameters
    ----------
    facilities_path : str
        DESCRIPTION.
    clusters_path : str, optional
        DESCRIPTION. The default is None.
    transit_points_path : str, optional
        DESCRIPTION. The default is None.
    freight_points_path : str, optional
        DESCRIPTION. The default is None.
    citylog_points_path : str, optional
        DESCRIPTION. The default is None.

    Returns
    -------
    facilities : TYPE
        DESCRIPTION.

    """
    facilities_gdf = load_facilities_common_part(
        facilities_path,
        static_columns=FACILITIES_COLUMNS,
        schema=FACILITIES_SCHEMA
    )

    activities = facilities_gdf['activity'].unique().tolist()
    if clusters_path is not None:
        clusters = load_clusters(clusters_path, activities)
        assign_facilities_clusters(facilities_gdf, clusters)

    facilities = unpack_regular_facilities(facilities_gdf)
    del facilities_gdf

    if transit_points_path:
        facilities[v.acts['transit']] = load_transit_points(transit_points_path)
    if freight_points_path:
        facilities[v.acts["freight"]] = load_freight_points(freight_points_path)
    if citylog_points_path:
        facilities[v.acts["citylog"]] = load_citylog_points(citylog_points_path)

    if v.center_coords is None:
        v.center_coords = get_city_center(facilities, v.capacity_affected)
        v.save_state()

    center_coords = v.center_coords

    constants_to_cols(facilities,
                      write_xy=True,
                      write_center_dist=True,
                      center_coords=center_coords)

    return facilities
