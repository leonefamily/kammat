# -*- coding: utf-8 -*-
"""
Created on Tue May  9 17:42:11 2023.

@author: dgrishchuk
"""
import logging
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
from shapely.ops import unary_union
from shapely.geometry import Point, Polygon
from typing import List, Literal, Union, Dict, Tuple
from kammat.defaults.variables import Variables
from kammat.defaults.constants import SPATIAL_LEVELS_LIST

ACTIONS = ['add', 'create']
v = Variables()


def get_random_points(
        polygon: Polygon,
        number: int
) -> List[Point]:
    """
    Get random points within specified polygon

    Parameters
    ----------
    polygon : Polygon
        Any shapely Polygon.
    number : int
        How many points should be generated within the polygon.

    Returns
    -------
    List[Point]

    """
    points = []
    minx, miny, maxx, maxy = polygon.bounds
    while len(points) < number:
        pnt = Point(
            np.random.uniform(minx, maxx),
            np.random.uniform(miny, maxy)
            )
        if polygon.contains(pnt):
            points.append(pnt)
    return points


def create_new_facilities(
        grid: gpd.GeoDataFrame,
        spatial_units: gpd.GeoDataFrame,
        max_points_per_tile: int = 9,
        action: Literal[ACTIONS] = 'add',
        current_inhabitants_column: str = 'OB_S',
        future_inhabitants_column: str = 'OB_K',
        current_workplaces_column: str = 'PM_S',
        future_workplaces_column: str = 'PM_K',
        seed: int = None
) -> Tuple[gpd.GeoDataFrame, Dict[str, Dict[int, int]]]:
    """
    Create facilities based on grid data.

    Parameters
    ----------
    grid : gpd.GeoDataFrame
        Grid of tiles with information about current and future counts.
    spatial_units : gpd.GeoDataFrame
        GeoDataFrame with spatial units geometries and descriptions
        (zone, area etc..)
    max_points_per_tile : int, optional
        How many points appear within each grid tile. The default is 9.
    action : Literal[ACTIONS], optional
        `add`: Use difference of future and current counts to assign to points;
        `create`: Use only future counts to assign to points.
        The default is 'add'.
    current_inhabitants_column : str, optional
        Grid GeoDataFrame column. The default is 'OB_S'.
    future_inhabitants_column : str, optional
        Grid GeoDataFrame column. The default is 'OB_K'.
    current_workplaces_column : str, optional
        Grid GeoDataFrame column. The default is 'PM_S'.
    future_workplaces_column : str, optional
        Grid GeoDataFrame column. The default is 'PM_K'.
    seed : int, optional
        Random seed for reproducing the same results. The default is None.

    Raises
    ------
    RuntimeError
        If wrong ``action`` supplied

    Returns
    -------
    Tuple[gpd.GeoDataFrame, Dict[str, Dict[int, int]]]
        new_facilities : GeoDataFrame
            Fully valid facilities to serve as input for kammat framework
        negative_change : Dict[str, Dict[int, int]]
            Values to remove capacity, if negative change encountered

    """
    if action not in ACTIONS:
        raise RuntimeError(f'action must be in {ACTIONS}')

    roles = ['work', 'home']
    new_facilities_rows = []
    negative_change = {role: {} for role in roles}
    np.random.seed(seed)
    for i, grid_part in grid.iterrows():
        for role in roles:

            if role == 'work':
                if action == 'add':
                    capacity = grid_part[future_workplaces_column] - grid_part[current_workplaces_column]
                else:
                    capacity = grid_part[future_workplaces_column]
            else:
                if action == 'add':
                    capacity = grid_part[future_inhabitants_column] - grid_part[current_inhabitants_column]
                else:
                    capacity = grid_part[future_inhabitants_column]

            if capacity == 0:
                continue
            elif capacity < 0:
                negative_change[role][i] = int(capacity)
                continue

            possible_spatial_units = spatial_units[spatial_units.intersects(grid_part.geometry)]
            pts = get_random_points(
                grid_part.geometry, min(max_points_per_tile, capacity)
                )
            pt_capacity, remainder = divmod(capacity, len(pts))

            for pt in pts:
                for j, spatial_unit in possible_spatial_units.iterrows():
                    if spatial_unit.geometry.contains(pt):

                        if remainder != 0:
                            final_capacity = pt_capacity + 1
                            remainder -= 1
                        else:
                            final_capacity = pt_capacity

                        attrs = spatial_unit[SPATIAL_LEVELS_LIST].to_dict()
                        attrs['activity'] = v.acts[role]
                        attrs['index'] = 0
                        attrs['capacity'] = int(final_capacity)
                        attrs['geometry'] = pt
                        attrs['info'] = 'future'
                        new_facilities_rows.append(attrs)
                        break

    new_facilities = gpd.GeoDataFrame(new_facilities_rows, crs=grid.crs)
    return new_facilities, negative_change


def reduce_capacity(
        grid: gpd.GeoDataFrame,
        new_facilities: gpd.GeoDataFrame,
        negative_change: Tuple[gpd.GeoDataFrame, Dict[str, Dict[int, int]]],
        reduce_outside: bool = True,
        buffer_step: Union[int, float] = 100,
        buffer_threshold: Union[int, float] = 1000
) -> gpd.GeoDataFrame:
    """
    Remove capacity in tiles, where reducing is assumed.

    Parameters
    ----------
    grid : gpd.GeoDataFrame
        Grid which was used in ``create_new_facilities``.
    new_facilities : gpd.GeoDataFrame
        New facilities, possibly combined with old ones.
    negative_change : Tuple[gpd.GeoDataFrame, Dict[str, Dict[int, int]]]
        Dictionary with negative numbers for each activity whose capacity
        to be reduced.
    reduce_neighbors : bool, optional
        Whether to try to reduce capacities in neighboring grids, if original
        grid doesn't have enough capacity to remove. The default is True.

    Returns
    -------
    gpd.GeoDataFrame

    """
    logging.info('Reducing capacities')
    reduced_facilities = new_facilities.copy()
    for role, role_change in negative_change.items():
        # if v.acts[role] not in v.capacity_affected:
        #     continue
        for gid, change in role_change.items():
            curr_change = -change
            curr_geom = grid.loc[gid].geometry
            curr_buffer = 0
            while curr_buffer < buffer_threshold:
                candidates = reduced_facilities[
                    reduced_facilities.within(
                        curr_geom.buffer(curr_buffer, join_style=2)
                    ) & (
                        reduced_facilities['activity'] == v.acts[role]
                    )
                ].copy()
                available_cap = candidates['capacity'].sum()
                if available_cap < curr_change:
                    reduced_facilities.drop(candidates.index, inplace=True)
                    curr_change -= available_cap
                    curr_buffer += buffer_step
                    if not reduce_outside:
                        break
                    else:
                        continue
                else:
                    for _ in range(abs(int(curr_change))):
                        pick_probs = (
                            candidates['capacity'] /
                            candidates['capacity'].sum()
                        )
                        pick_id = np.random.choice(
                            pick_probs.index, p=pick_probs.values
                        )
                        if curr_change < 0:
                            candidates.loc[pick_id, 'capacity'] += 1
                        else:
                            candidates.loc[pick_id, 'capacity'] -= 1
                    # if reduced_facilities.loc[candidates.index, 'capacity'].sum() - candidates['capacity'].sum() != curr_change:
                    #     raise
                    reduced_facilities.loc[
                        candidates.index,
                        'capacity'
                    ] = candidates['capacity']
                    break
        reduced_facilities.drop(
            reduced_facilities[
                (reduced_facilities['capacity'] <= 0) &
                reduced_facilities['activity'] == v.acts[role]
            ].index
        )
    return reduced_facilities


def handle_new_facilities(
        grid_path: Union[str, Path],
        spatial_units_path: Union[str, Path],
        new_facilities_save_path: Union[str, Path],
        max_points_per_tile: int = 9,
        action: Literal[ACTIONS] = 'add',
        old_facilities_path: Union[str, Path] = None,
        current_inhabitants_column: str = 'OB_S',
        future_inhabitants_column: str = 'OB_K',
        current_workplaces_column: str = 'PM_S',
        future_workplaces_column: str = 'PM_K',
        seed: int = None
):
    """
    Create new facilities from grid data and optionally append to existing.

    Parameters
    ----------
    grid_path : Union[str, Path]
        Path to grid of tiles with information about current and future counts.
    spatial_units_path : Union[str, Path]
        Path to GeoDataFrame with spatial units geometries and descriptions.
    new_facilities_save_path : Union[str, Path]
        DESCRIPTION.
    max_points_per_tile : int, optional
        How many points appear within each grid tile. The default is 9.
    action : Literal[ACTIONS], optional
        `add`: Use difference of future and current counts to assign to points;
        `create`: Use only future counts to assign to points.
        The default is 'add'.
    old_facilities_path : Union[str, Path], optional
        Path to existing facilities. New will be appended. The default is None.
    current_inhabitants_column : str, optional
        Grid GeoDataFrame column. The default is 'OB_S'.
    future_inhabitants_column : str, optional
        Grid GeoDataFrame column. The default is 'OB_K'.
    current_workplaces_column : str, optional
        Grid GeoDataFrame column. The default is 'PM_S'.
    future_workplaces_column : str, optional
        Grid GeoDataFrame column. The default is 'PM_K'.
    seed : int, optional
        Random seed for reproducing the same results. The default is None.

    """
    grid = gpd.read_file(grid_path)
    spatial_units = gpd.read_file(spatial_units_path)
    new_facilities, negative_change = create_new_facilities(
        grid=grid,
        spatial_units=spatial_units,
        max_points_per_tile=max_points_per_tile,
        action=action,
        current_inhabitants_column=current_inhabitants_column,
        future_inhabitants_column=future_inhabitants_column,
        current_workplaces_column=current_workplaces_column,
        future_workplaces_column=future_workplaces_column,
        seed=seed
    )
    if old_facilities_path is not None:
        old_facilities = gpd.read_file(old_facilities_path)
        new_facilities = gpd.GeoDataFrame(
            pd.concat([old_facilities, new_facilities]), crs=grid.crs
            )
    reduce_capacity(
        grid, new_facilities, negative_change, reduce_neighbors=True
        )
    new_facilities.to_file(new_facilities_save_path, encoding='utf-8')
