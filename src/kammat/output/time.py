# -*- coding: utf-8 -*-
"""
Created on Mon Sep  2 18:07:38 2024

@author: dgrishchuk
"""

import logging
import pandas as pd
import geopandas as gpd
from pathlib import Path
from shapely.geometry import Point
from collections import defaultdict
from typing import Union, List, Optional
from kammat.output.utils import td2str
from kammat.input.data.utils import load_shapefile, check_columns
from kammat.defaults.constants import CSV_STYLE, SPATIAL_LEVELS_LIST, SPATIAL_LEVELS_SCHEMA


def load_spatial_units_shapes(
        spatial_units_path: str
) -> gpd.GeoDataFrame:
    """
    Load and check spatial units shapes file.

    Parameters
    ----------
    spatial_units_path : str
        Spatial units file location.

    Raises
    ------
    RuntimeError
        If there is not every required static column

    Returns
    -------
    gpd.GeoDataFrame

    """
    spatial_units = load_shapefile(spatial_units_path, 'Polygon')

    ccols = check_columns(spatial_units.columns.tolist(), SPATIAL_LEVELS_LIST)
    if ccols['missing']:
        raise RuntimeError("Spatial units don't contain all required "
                           f"static columns, missing: {ccols['missing']}")

    spatial_units = spatial_units.astype(SPATIAL_LEVELS_SCHEMA)
    return spatial_units



def get_time_matrices(
        legs_df: pd.DataFrame,
        trips_df: pd.DataFrame,
        spatial_units: gpd.GeoDataFrame,
        output_directory: Union[str, Path],
        exclude_patterns: Optional[List[str]] = None,
        include_patterns: Optional[List[str]] = None
) -> pd.DataFrame:
    # trips_df = pd.read_csv(
    #     trips_path,
    #     **CSV_STYLE,
    #     usecols=[
    #         'person', 'start_x', 'start_y', 'end_x', 'end_y', 'trav_time',
    #         'longest_distance_mode'
    #     ]
    # )
    # for c in trips_df.columns:
    #     if c.endswith('_time'):
    #         trips_df[c] = pd.to_timedelta(trips_df[c])
    #     elif c.endswith('_x') or c.endswith('_y'):
    #         trips_df[c] = trips_df[c].astype(float)

    # spatial_units = load_spatial_units_shapes(spatial_units_path)

    exclude_patterns = ['tra', 'fre', 'noise', 'taxi', 'cit', 'delivery', 'ambulance', 'driving', 'police']
    select_trips_df = trips_df[
        ~trips_df['person'].str.contains('|'.join(exclude_patterns), regex=True)
    ]
    stats_cols = ['distname', 'zonename', 'region']

    all_simple_points = set()

    for x, y in zip(select_trips_df['start_x'], select_trips_df['start_y']):
        all_simple_points.add((x, y))
    for x, y in zip(select_trips_df['end_x'], select_trips_df['end_y']):
        all_simple_points.add((x, y))

    all_simple_points_geoms = gpd.GeoSeries(
        [Point(*p) for p in all_simple_points],
        crs=spatial_units.crs
    )
    points_spatial_units = {}
    for su_id, su_row in spatial_units.iterrows():
        geoms_within = all_simple_points_geoms[
            all_simple_points_geoms.within(su_row.geometry)
        ]
        for geom in geoms_within.geometry:
            points_spatial_units[(geom.x, geom.y)] = su_id
        all_simple_points_geoms.drop(geoms_within.index, inplace=True)

    time_relations = defaultdict(lambda: defaultdict(list))
    for num, trip_row in select_trips_df.reset_index(drop=True).iterrows():
        mode = trip_row['longest_distance_mode']
        start_xy = trip_row['start_x'], trip_row['start_y']
        end_xy = trip_row['end_x'], trip_row['end_y']
        try:
            start_su_id = points_spatial_units[start_xy]
            end_su_id = points_spatial_units[end_xy]
        except KeyError:
            continue
        su_relation = start_su_id, end_su_id
        time_relations[su_relation][mode].append(trip_row['trav_time'])
        if num % 100000 == 0:
            logging.info(f'Trip # {num}')

    agg_time_relations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(list)
        )
    )
    for (from_id, to_id), mode_values in time_relations.items():
        for col in spatial_units.columns:
            if col == 'geometry':
                continue
            if stats_cols and col not in stats_cols:
                continue
            from_col_id = spatial_units.loc[from_id, col]
            to_col_id = spatial_units.loc[to_id, col]
            col_relation = from_col_id, to_col_id
            for mode, values in mode_values.items():
                agg_time_relations[col][mode][col_relation].extend(values)

    agg_df_stats_time_relations = defaultdict(
        lambda: defaultdict(
            lambda: defaultdict(pd.DataFrame)
        )
    )
    for col, spatial_values in agg_time_relations.items():
        for mode, mode_values in spatial_values.items():
            if mode not in ['car', 'pt']:
                continue
            for (from_col_id, to_col_id), values in mode_values.items():
                ser = pd.Series(values)
                statvals = ser.describe()
                statvals['sum'] = ser.sum()
                for name, item in statvals.iteritems():
                    if isinstance(item, pd.Timedelta):
                        val = td2str(item)
                    else:
                        val = item
                    agg_df_stats_time_relations[col][mode][name].loc[from_col_id, to_col_id] = val

    for col, spatial_values in agg_df_stats_time_relations.items():
        for mode, mode_values in spatial_values.items():
            if mode not in ['car', 'pt']:
                continue
            for name, df in mode_values.items():
                spath = Path(output_directory) / f'{col}_{mode}_{name}.csv'
                df.to_csv(spath, **CSV_STYLE, encoding='utf-8-sig')