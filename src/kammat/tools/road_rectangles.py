# -*- coding: utf-8 -*-
"""
Created on Wed Aug  7 16:33:27 2024

@author: dgrishchuk
"""

import shapely
import geopandas as gpd
from typing import List, Tuple, Any, Optional, Union
from shapely.geometry import Point, MultiPoint, LineString, Polygon


def merge_and_order_by_values(
        list1: List[Any],
        list2: List[Any],
        values1: List[Union[int, float]],
        values2: List[Union[int, float]]
) -> List[Any]:
    """
    Amalgamate and order two lists in an ascending manner.

    Let:
    list1 = ['Pear', 'Eggplant']
    list2 = ['Apple', 'Strawberry', 'Lemon']
    values1 = [3.5, 5]
    values2 = [3, 0.5, 2]

    values* serve as keys for sorting. list* will be merged into one list,
    with entries order corresponding to their values*, e.g. in this example:

    ['Strawberry', 'Lemon', 'Apple', 'Pear', 'Eggplant']

    Parameters
    ----------
    list1 : List[Any]
        List of any length with any elements.
    list2 : List[Any]
        Second list of any length with any elements.
    values1 : List[Union[int, float]]
        Numeric values that can be compared across both lists.
    values2 : List[Union[int, float]]
        Numeric values that can be compared across both lists.

    Returns
    -------
    List[Any]

    """
    enumvalues1 = sorted(
        list(enumerate(values1)), key=lambda x: x[1], reverse=True
    )
    enumvalues2 = sorted(
        list(enumerate(values2)), key=lambda x: x[1], reverse=True
    )

    lastval1 = enumvalues1.pop() if enumvalues1 else None
    lastval2 = enumvalues2.pop() if enumvalues2 else None

    result = []
    while True:  # can potentially get stuck in the loop, but it didn't yet...
        if lastval1 is None and lastval2 is None:
            break
        elif lastval1 is None:
            result.append(list2[lastval2[0]])
            lastval2 = enumvalues2.pop() if enumvalues2 else None
        elif lastval2 is None:
            result.append(list1[lastval1[0]])
            lastval1 = enumvalues1.pop() if enumvalues1 else None
        else:
            if lastval1[1] < lastval2[1]:
                result.append(list1[lastval1[0]])
                lastval1 = enumvalues1.pop() if enumvalues1 else None
            elif lastval1[1] > lastval2[1]:
                result.append(list2[lastval2[0]])
                lastval2 = enumvalues2.pop() if enumvalues2 else None
            elif lastval1[1] == lastval2[1]:
                result.append(list1[lastval1[0]])
                result.append(list2[lastval2[0]])
                lastval1 = enumvalues1.pop() if enumvalues1 else None
                lastval2 = enumvalues2.pop() if enumvalues2 else None
    return result


def split_linestring(
        lstr: LineString,
        dist: Union[int, float]
) -> List[LineString]:
    """
    Split any linestring into chunks with segments that are ``dist`` long.

    Parameters
    ----------
    lstr : LineString
        Any valid LineString.
    dist : Union[int, float]
        What distance should segments of the LineString have.

    Returns
    -------
    List[LineString]
        No MultiLineString is returned, but an ordered list of LineStrings.
    """
    lcoords = list(lstr.coords)
    ldists = [lstr.project(Point(lc)) for lc in lcoords]

    splitters = []
    splitcoords = []
    splitdists = []
    quot, remn = divmod(lstr.length, dist)
    for mult in range(1, int(quot) + (1 if remn > 0 else 0)):
        dist_tot = mult * dist
        splitdists.append(dist_tot)
        splitter = lstr.interpolate(dist_tot)
        splitcoords.append((splitter.x, splitter.y))
        splitters.append(splitter)

    newlcoords = merge_and_order_by_values(
        list1=lcoords,
        list2=splitcoords,
        values1=ldists,
        values2=splitdists
    )
    newl = LineString(newlcoords)
    multil = shapely.ops.split(newl, MultiPoint(splitters))
    multil_list = [gm for gm in list(multil.geoms)]
    return multil_list


def make_parallel_polygon(
        basis: LineString,
        width: Union[int, float]
) -> Polygon:
    """
    Create a polygon from line and its offset clone.

    Parameters
    ----------
    basis : LineString
        A line that will be the bottom of the polygon.
    width : Union[int, float]
        A distance that ``basis``'s copy will be offset to the right.

    Returns
    -------
    Polygon

    """
    top = basis.parallel_offset(width)
    topcoords = list(top.reverse().coords)
    basiscoords = list(basis.coords)
    polycoords = basiscoords + topcoords + [basiscoords[0]]
    poly = Polygon(polycoords)
    return poly


def create_cells_along_roads(
        roads: gpd.GeoDataFrame,
        parcel_size: Tuple[float, float] = (20, 20),
        duplicate_oneway: bool = False,
        oneway_column: Optional[str] = 'ONEWAY',
        oneway_value: Union[str, int, float, bool] = 'FT'
) -> gpd.GeoDataFrame:
    """
    Make pseudo-rectangle cells parallel to roads' geometries.

    Parameters
    ----------
    roads : gpd.GeoDataFrame
        A GeoDataFrame of roads with Cartesian CRS.
    parcel_size : Tuple[float, float], optional
        Length (along road) X width of resulting polygons cells.
        The default is (20, 20).
    duplicate_oneway : bool, optional
        If True, both*way roads will be populated with cells on both sides.
        The default is False.
    oneway_column : Optional[str], optional
        Name of column representing oneway road. The default is 'ONEWAY'.
    oneway_value : Union[str, int, float, bool], optional
        Value that means a road is oneway. The default is 'FT'.

    Returns
    -------
    gpd.GeoDataFrame
        Rows are taken from corresponding roads, their geometry is replaced
        with polygons.

    """
    polys_rows = []
    for rid, rrow in roads.reset_index(drop=True).iterrows():
        g = rrow.geometry
        multigs = split_linestring(lstr=g, dist=parcel_size[0])
        for bottom in multigs:
            if bottom.length < parcel_size[0] - parcel_size[0] * 0.01:
                continue
            poly = make_parallel_polygon(basis=bottom, width=parcel_size[1])
            prow = rrow.copy()
            prow.geometry = poly
            polys_rows.append(prow)
            if duplicate_oneway and rrow[oneway_column] != oneway_value:
                rbottom = bottom.reverse()
                rpoly = make_parallel_polygon(
                    basis=rbottom, width=parcel_size[1]
                )
                rprow = rrow.copy()
                rprow.geometry = rpoly
                polys_rows.append(rprow)
    polys_gdf = gpd.GeoDataFrame(
        polys_rows, crs=roads.crs
    ).reset_index(drop=True)
    return polys_gdf
