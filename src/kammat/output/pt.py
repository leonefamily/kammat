# -*- coding: utf-8 -*-
"""
Created on Thu Feb  2 14:06:34 2023

@author: dgrishchuk
"""

import gzip
import lxml
import matplotlib
import numpy as np
import pandas as pd
import geopandas as gpd
from pathlib import Path
import matplotlib.dates as mdates
from lxml.etree import _ElementTree
from matplotlib import pyplot as plt
from collections import defaultdict
from datetime import timedelta as td
from typing import Union, List, Dict, Tuple, Optional, Literal  # , Sequence, Any

from kammat.output.utils import (
    get_timeline, defaultdict2dict,
    td2str, LINK_STATS_FIGURE_SIZE
)
from kammat.defaults.constants import CSV_STYLE

Profiles = Dict[str, Dict[str, List[Tuple[str, List[str]]]]]
Lrvs = Dict[str, List[str]]
PtStops = Dict[str, Dict[str, str]]
PtCounts = Dict[str, Dict[str, Union[str, int, float]]]


def load_pt_schedule(
        path: Union[str, Path]
        ) -> _ElementTree:
    """
    

    Parameters
    ----------
    path : Union[str, Path]
        DESCRIPTION.

    Returns
    -------
    _ElementTree
        DESCRIPTION.

    """
    tree = lxml.etree.parse(str(path))
    return tree


# def load_transit_vehicle_types(
#         path: Union[str, Path],
#         namespace: Optional[str] = '{http://www.matsim.org/files/dtd}'
# ) -> Dict[str, str]:
#     tree = lxml.etree.parse(str(path))

#     vtypes_info = {}
#     vtypes = {}

#     for vtype_el in tree.findall(f'{namespace}vehicleType'):
#         vtype = {}
#         attrs_el = vtype_el.find(f'{namespace}attributes')
#         if attrs_el:
#             for attr in attrs_el.findall(f'{namespace}attribute'):
#                 vtype[f'attr_{attr.attrib["name"]}'] = attr.text

#         try:
#             cap = vtype_el.find(f'{namespace}capacity')
#             for key, val in cap.items():
#                 vtype[f'capacity_{key}'] = cap.attrib[key]
#         except Exception:
#             pass

#         try:
#             vtype[f'length'] = float(
#                 vtype_el.find(f'{namespace}length').attrib['meter']
#             )
#         except Exception:
#             pass

#         vtypes_info[vtype_el.attrib['id']] = vtype

#     for veh in tree.findall(f'{namespace}vehicle'):
#         vtypes[veh.attrib['id']] = veh.attrib['type']

#     return vtypes


def get_transit_stops(
        pt_schedule: _ElementTree
        ) -> Dict[str, Dict[str, str]]:
    """
    Get stops as a dictionary name with dictionary of attributes.

    Parameters
    ----------
    pt_schedule : _ElementTree
        Transit schedule tree

    Returns
    -------
    Dict[str, Dict[str, str]]

    """
    pt_stops = {}
    stop_facilities = pt_schedule.xpath("//transitStops/stopFacility")
    for sfac in stop_facilities:
        attrs = sfac.attrib
        pt_stops[attrs['id']] = {k: attrs[k] for k in attrs if k != 'id'}
    return pt_stops


def get_route_profile(
        route_element: lxml.etree._Element,
        pt_stops: Dict[str, Dict[str, str]]
) -> List[Tuple[str, List[str]]]:
    """
    Get route profile in form "stop - list of links to next stop"

    Parameters
    ----------
    route_element : lxml.etree._Element
        `route` element from transit schedule xml
    pt_stops : Dict[str, Dict[str, str]]
        Stops IDs with attributes

    Returns
    -------
    Dict[str, List[str]]

    """
    route_profile = []
    stops_list = [
        el.attrib['refId'] for el in route_element.find('routeProfile')
    ]
    links_list = [
        el.attrib['refId'] for el in route_element.find('route')
    ]
    stops_refs = [
        pt_stops[s]['linkRefId'] for s in stops_list
    ]

    buffer = []
    last_stop = None
    cutoff = len(links_list)
    for i, link in enumerate(links_list):
        if link in stops_refs:
            if i != 0:
                stop = stops_list[stops_refs.index(link)]
                route_profile.append((stop, buffer))
                buffer = []
                if i < cutoff:
                    last_stop = stop
        buffer.append(link)
    route_profile[-1][1].extend(buffer)
    return route_profile


def get_pt_stats(
        pt_counts: PtCounts,
        pt_schedule: _ElementTree,
        pt_stops: PtStops,
        lines: List[str] = None,
        link_id: str = None,
        start: int = 0,
        end: int = 86400
        ) -> Tuple[Dict[str, int], Dict[str, Dict[str, int]]]:
    """
    Get total passenger numbers carried by specified lines on specified links.

    Also count, how many people get on and off on stops or pass by them.

    Parameters
    ----------
    pt_counts : PtCounts
        Entering and leaving counts from JSON.
    pt_schedule : _ElementTree
        Transit schedule tree.
    pt_stops : PtStops
        Stops IDs with attributes
    lines : List[str], optional
        List of line names (as in GTFS). The default is None.
    link_id : str, optional
        ID of link to check. The default is None.
    start : int, optional
        Start of time interval. The default is 0.
    end : int, optional
        End of time interval. The default is 86400.

    Returns
    -------
    Tuple[Dict[str, int], Dict[str, Dict[str, int]]]

    """
    pt_links_stats = defaultdict(int)
    stops_stats = defaultdict(lambda: defaultdict(int))

    lrvs, profiles = get_lines_routes_vehicles_profiles(
        pt_schedule, pt_stops, lines,
        link_ids=None if not link_id else [link_id]
    )

    for lname, rid, veh, mode in zip(*lrvs.values()):
        cumulative = 0
        route_profile = profiles[lname][rid]

        for i, info in enumerate(pt_counts[veh]):

            if info['arrival'] < start:
                continue
            if 'departure' in info and info['departure'] > end:
                break

            stops_stats[info['stop']]['entered'] += info['entered']
            stops_stats[info['stop']]['left'] += info['left']

            # for stop, trails in route_profile:
            #     if info['stop'] == stop:
            #         for link in trails:
            #             pt_links_stats[link] += cumulative
            for link in route_profile[i - 1][-1]:
                pt_links_stats[link] += cumulative

            cumulative -= info['left']

            stops_stats[info['stop']]['passed'] += cumulative

            cumulative += info['entered']

    pt_links_stats = dict(pt_links_stats)
    stops_stats = {k: dict(v) for k, v in stops_stats.items()}
    return pt_links_stats, stops_stats


def pt_stops_to_gdf(
        pt_stops: Dict[str, Dict[str, str]],
        crs: str = None
        ) -> gpd.GeoDataFrame:
    """
    Convert dictionary to GeoDataFrame.

    Parameters
    ----------
    pt_stops : Dict[str, Dict[str, str]]
        Stops IDs with attributes
    crs : str, optional
        Coordinate reference system to use. The default is None.

    Returns
    -------
    gpd.GeoDataFrame

    """
    pt_stops_df = pd.DataFrame(pt_stops).transpose().rename_axis('stopRefId').reset_index()
    pt_stops_df['geometry'] = gpd.points_from_xy(
        pt_stops_df['x'], pt_stops_df['y']
        )
    pt_stops_gdf = gpd.GeoDataFrame(pt_stops_df, crs=crs)
    return pt_stops_gdf


def filter_line_names(
        pt_net: gpd.GeoDataFrame,
        lines: List[str],
        count_thresh: int = None
        ) -> gpd.GeoDataFrame:
    """
    Keep only links passed by specified lines and correct `lines` column.

    Parameters
    ----------
    pt_net : gpd.GeoDataFrame
        Network with only PT links.
    lines : List[str]
        List of lines to keep.
    count_thresh : int, optional
        Drop links, that have count below this value. The default is None.

    Returns
    -------
    gpd.GeoDataFrame

    """
    idx = []
    newlines = []
    for n, row in pt_net.iterrows():
        if count_thresh is not None and row['count'] < count_thresh:
            continue
        lns = row['lines']
        if isinstance(lns, str):
            splns = lns.split(', ')
            req = set()
            for spln in splns:
                if spln in lines:
                    req.add(spln)
            if req:
                idx.append(n)
                newlines.append(', '.join(req))
    pt_net_new = pt_net.loc[idx].copy()
    pt_net_new['lines'] = newlines
    return pt_net_new


def pt_net_to_plot_gdf(
        pt_net: gpd.GeoDataFrame,
        lines: List[str] = None,
        count_thresh: int = None
        ) -> gpd.GeoDataFrame:
    """
    Convert original PT network to a reduced version based on line names.

    Parameters
    ----------
    pt_net : gpd.GeoDataFrame
        Network with only PT links.
    lines : List[str], optional
        List of lines names. The default is None - don't filter by lines.
    count_thresh : int, optional
        Drop links, that have count below this value. The default is None.

    Returns
    -------
    gpd.GeoDataFrame

    """
    if lines is None:
        if count_thresh is not None:
            return pt_net[pt_net['count'] >= count_thresh].copy()
        return pt_net.copy()
    return filter_line_names(pt_net, lines, count_thresh)


def merge_opposite_directions(
        pt_net: gpd.GeoDataFrame
        ) -> gpd.GeoDataFrame:
    """
    Merge bidirectional links into one link with sum of passengers counts.

    Parameters
    ----------
    pt_net : gpd.GeoDataFrame
        Network with only PT links.

    Returns
    -------
    gpd.GeoDataFrame

    """
    seen_combs = []
    rows = []
    for comb, subnet in pt_net.groupby(
            ['length', 'from_node', 'to_node', 'lines']
            ):
        length, from_node, to_node, lines = comb
        newcomb = length, to_node, from_node, lines
        if comb in seen_combs or newcomb in seen_combs:
            continue
        seen_combs.extend([comb, newcomb])
        opposite_subnet = pt_net[
            (pt_net['length'] == length) &
            (pt_net['from_node'] == to_node) &
            (pt_net['to_node'] == from_node) &
            (pt_net['lines'] == lines)
            ]

        newcount = subnet['count'].sum() + opposite_subnet['count'].sum()
        newrow = subnet.iloc[[0]].copy()
        newrow['count'] = newcount
        rows.append(newrow)
    mergedf = pd.concat(rows).reset_index(drop=True)
    return mergedf


def get_line_route_plot(
        pt_net: gpd.GeoDataFrame,
        lines: List[str] = None
        ) -> matplotlib.figure.Figure:
    """
    Get plot of lines routes with links widths corresponding with counts.

    Parameters
    ----------
    pt_net : gpd.GeoDataFrame
        Network with only PT links.
    lines : List[str], optional
        List of lines names. The default is None - don't filter by lines.

    Returns
    -------
    matplotlib.figure.Figure

    """
    if lines is None:
        title = 'Passenger on all lines'
    else:
        title = f'Passengers on lines: {", ".join(lines)}'

    ref_pt_net = merge_opposite_directions(pt_net)

    bins = np.linspace(
        ref_pt_net['count'].min(), ref_pt_net['count'].max(), 100
        )

    ref_pt_net['width'] = pd.cut(
        ref_pt_net['count'], bins=bins
        ).cat.codes / 100 * 15

    # fig, ax = plt.subplots(figsize=LINK_STATS_FIGURE_SIZE)
    ax = ref_pt_net.plot(linewidth=ref_pt_net['width'],
                         column='lines', legend=lines is not None,
                         figsize=LINK_STATS_FIGURE_SIZE)
    fig = ax.get_figure()
    ax.set_title(title)
    ax.tick_params(
        axis='both', which='both', labelbottom=False, bottom=False,
        right=False, left=False, top=False
        )
    plt.axis('off')
    ax.spines['top'].set_visible(False)
    # ax.axes.xaxis.set_ticklabels([])
    # ax.axes.yaxis.set_ticklabels([])
    # ax.yaxis.set_ticks_position('left')
    # ax.xaxis.set_ticks_position('bottom')
    # ax.spines['top'].set_visible(False)
    # ax.spines['right'].set_visible(False)
    # ax.spines['bottom'].set_visible(False)
    # ax.spines['left'].set_visible(False)
    return fig


def add_stop_name_columns(
        pt_net: gpd.GeoDataFrame,
        pt_stops: Dict[str, Dict[str, str]]
        ):

    stops_names = {
        el['linkRefId']:
            (el['name'] if 'name' in el else 'Unnamed')
            for el in pt_stops.values()
    }
    stops_names_ser = pd.Series(stops_names, name='from_stop')

    pt_net = pt_net.merge(stops_names_ser, how='left', left_on='from_node',
                          right_on=stops_names_ser.index)

    stops_names_ser.name = 'to_stop'
    pt_net = pt_net.merge(stops_names_ser, how='left', left_on='to_node',
                          right_on=stops_names_ser.index)
    return pt_net


def add_lines_column(
        pt_net: gpd.GeoDataFrame,
        pt_schedule: _ElementTree
        ):
    prelinemap = defaultdict(set)
    for lineel in pt_schedule.findall('transitLine'):
        for routeel in lineel.findall('transitRoute'):
            for link in routeel.find('route').findall('link'):
                if 'name' in lineel.attrib:
                    prelinemap[link.attrib['refId']].add(lineel.attrib['name'])
                else:
                    prelinemap[link.attrib['refId']].add('unnamed')
    linemap = {k: ', '.join(v) for k, v in prelinemap.items()}
    lines_ser = pd.Series(linemap, name='lines')
    pt_net = pt_net.merge(lines_ser, how='left', left_on='link_id',
                          right_on=lines_ser.index)
    pt_net['lines'].fillna('', inplace=True)
    return pt_net


def merge_stops_pt_counts(
        pt_stops_gdf: gpd.GeoDataFrame,
        stops_stats: Dict[str, Dict[str, int]],
        drop_empty: bool = False
) -> gpd.GeoDataFrame:
    stops_stats_df = pd.DataFrame(stops_stats).transpose().rename_axis('stopRefId').reset_index()
    pt_stops_counts = pt_stops_gdf.merge(stops_stats_df, how='left')
    if drop_empty:
        pt_stops_counts.dropna(
            axis=0, how='all', subset=['entered', 'left', 'passed'], inplace=True
        )
    return pt_stops_counts


def handle_pt(
        pt_counts: PtCounts,
        pt_schedule: _ElementTree,
        net: gpd.GeoDataFrame
        ) -> Tuple[gpd.GeoDataFrame]:
    """
    For big runs, only basic info about pt.

    Parameters
    ----------
    pt_counts : PtCounts
        DESCRIPTION.
    net : gpd.GeoDataFrame
        DESCRIPTION.
    schedule_path : Union[str, Path]
        DESCRIPTION.

    Returns
    -------
    pt_net : TYPE
        DESCRIPTION.
    pt_stops_counts : TYPE
        DESCRIPTION.

    """
    pt_stops = get_transit_stops(pt_schedule)
    pt_stops_gdf = pt_stops_to_gdf(
        pt_stops, crs=':'.join(net.crs.to_authority()) if net.crs else None
        )
    pt_links_stats, stops_stats = get_pt_stats(
        pt_counts, pt_schedule, pt_stops
    )
    pt_net = merge_net_pt_counts(net, pt_links_stats, drop_empty=True)
    pt_net = add_stop_name_columns(pt_net, pt_stops)
    pt_stops_counts = merge_stops_pt_counts(pt_stops_gdf, stops_stats)
    return pt_net, pt_stops_counts


def merge_net_pt_counts(
        net: gpd.GeoDataFrame,
        pt_links_stats: Dict[str, int],
        drop_empty: bool = True
        ) -> gpd.GeoDataFrame:
    """
    B.

    Parameters
    ----------
    net : gpd.GeoDataFrame
        DESCRIPTION.
    counts : Dict[str, Dict[float, Dict[str, int]]]
        DESCRIPTION.

    """
    pt_counts_ser = pd.Series(pt_links_stats, dtype=int, name='count')
    pt_net = net.merge(
        pt_counts_ser, right_on=pt_counts_ser.index, left_on='link_id',
        how='inner' if drop_empty else 'left'
    )
    pt_net.drop(
        pt_net[pt_net['from_node'] == pt_net['to_node']].index, inplace=True
    )
    return pt_net


def get_lines_routes_vehicles_profiles(
        pt_schedule: _ElementTree,
        pt_stops: PtStops,
        lines: List[str] = None,
        link_ids: List[str] = None,
        stop_ids: List[str] = None,
        stop_ids_type: Literal['id', 'linkRefId', 'name'] = 'id'
) -> Tuple[Lrvs, Profiles]:
    """
    Extract vehicles infos and route profiles.

    Parameters
    ----------
    pt_schedule : _ElementTree
        TransitSchedule from XML.
    pt_stops : PtStops
        PtStops dict from get_.
    lines : List[str], optional
        DESCRIPTION. The default is None.
    link_ids : List[str], optional
        DESCRIPTION. The default is None.
    stop_ids : List[str], optional
        DESCRIPTION. The default is None.
    stop_ids_type : Literal['id', 'linkRefId', 'name'], optional
        DESCRIPTION. The default is 'id'.

    Returns
    -------
    lrvs : Lrvs
        DESCRIPTION.
    profiles : Profile
        DESCRIPTION.

    """
    lrvs = {
        'lines': [],
        'routes': [],
        'vehicles': [],
        'modes': []
    }

    profiles = {}

    unnamed_n = 0
    for element in pt_schedule.iter():
        if element.tag == 'departure':
            routeel = element.getparent().getparent()
            if link_ids is not None:
                links = [el.attrib['refId'] for el in routeel.find('route')]
                if not any(link in link_ids for link in links):
                    continue
            if stop_ids is not None:
                stop_refs = [
                    el.attrib['refId'] for el in routeel.find('routeProfile')
                ]
                if stop_ids_type == 'linkRefId':
                    stop_refs = [
                        pt_stops[stop_ref]['linkRefId']
                        for stop_ref in stop_refs
                    ]
                elif stop_ids_type == 'name':
                    stop_refs = [
                        pt_stops[stop_ref]['name'] for stop_ref in stop_refs
                        if 'name' in pt_stops[stop_ref]
                    ]
                if not any(stop_ref in stop_ids for stop_ref in stop_refs):
                    continue
            route = routeel.attrib['id']
            parent_attr = routeel.getparent().attrib
            if 'name' in parent_attr:
                line = parent_attr['name']
                isunnamed = False
            else:
                line = f'u_{unnamed_n}'
                isunnamed = True
            mode = routeel.find('transportMode').text
            if lines is not None:
                if line not in lines:
                    continue
            if line not in profiles:
                profiles[line] = {}
            rprofile = get_route_profile(routeel, pt_stops)
            profiles[line][route] = rprofile
            lrvs['lines'].append(line)
            lrvs['routes'].append(route)
            lrvs['vehicles'].append(element.attrib['vehicleRefId'])
            lrvs['modes'].append(mode)
            if isunnamed:
                unnamed_n += 1
    return lrvs, profiles


def get_pt_stops_time_stats(
        pt_counts: PtCounts,
        pt_schedule: _ElementTree,
        pt_stops: PtStops,
        lines: List[str] = None,
        link_ids: List[str] = None,
        start: int = 0,
        end: int = 86400,
        aggregate_by: Optional[int] = 3600
) -> Dict[str, Dict[float, Dict[str, int]]]:
    if aggregate_by:
        timeline = get_timeline(start, end, aggregate_by, aggregate_unit='s')
        pt_stops_time_stats = defaultdict(
            lambda: {ts: defaultdict(
                lambda: {'entered': 0, 'left': 0, 'passed': 0, 'interactions': 0}
            ) for ts in timeline}
        )
    else:
        pt_stops_time_stats = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(
                    lambda: {
                        'entered': 0, 'left': 0, 'passed': 0, 'interactions': 0
                    }
                )
            )
        )
    lrvs, profiles = get_lines_routes_vehicles_profiles(
        pt_schedule, pt_stops, lines=lines, link_ids=link_ids
    )
    rid_allowed_stops = defaultdict(list)

    for lname, rid, veh, mode in zip(*lrvs.values()):
        cumulative = 0
        route_profile = profiles[lname][rid]

        if link_ids:
            if rid not in rid_allowed_stops:
                allowed_stops = set()
                for link_id in link_ids:
                    for stop, links in route_profile:
                        if link_id in links:
                            allowed_stops.add(stop)
                            for stop_id, stop_data in pt_stops.items():
                                # links[0] - ref link of a previous stop
                                if stop_data['linkRefId'] == links[0]:
                                    allowed_stops.add(stop_id)
                                    break
                rid_allowed_stops[rid] = allowed_stops
            else:
                allowed_stops = rid_allowed_stops[rid]
        else:
            allowed_stops = set(info['stop'] for info in pt_counts[veh])

        for info in pt_counts[veh]:

            if info['arrival'] < start:
                cumulative = cumulative + info['entered'] - info['left']
                continue
            if 'departure' in info and info['departure'] > end:
                break

            if aggregate_by:
                seg_start = max([t for t in timeline if t <= info['arrival']])
            else:
                seg_start = info['arrival']

            sid = info['stop']

            if sid in allowed_stops:
                pt_stops_time_stats[lname][seg_start][sid]['entered'] += info['entered']
                pt_stops_time_stats[lname][seg_start][sid]['left'] += info['left']
                pt_stops_time_stats[lname][seg_start][sid]['interactions'] += (
                    info['left'] + info['entered']
                )

            cumulative -= info['left']

            if sid in allowed_stops:
                pt_stops_time_stats[lname][seg_start][sid]['passed'] += cumulative

            cumulative += info['entered']

    pt_stops_time_stats = defaultdict2dict(pt_stops_time_stats)
    return pt_stops_time_stats


def get_pt_links_time_stats(
        pt_counts: PtCounts,
        pt_schedule: _ElementTree,
        pt_stops: PtStops,
        lines: List[str] = None,
        link_ids: List[str] = None,
        start: int = 0,
        end: int = 86400,
        aggregate_by: Optional[int] = 3600
) -> Dict[str, Dict[float, Dict[str, int]]]:
    if aggregate_by:
        timeline = get_timeline(start, end, aggregate_by, aggregate_unit='s')
        pt_links_time_stats = defaultdict(
            lambda: {ts: defaultdict(int) for ts in timeline}
        )
    else:
        pt_links_time_stats = defaultdict(
            lambda: defaultdict(
                lambda: defaultdict(int)
            )
        )
    lrvs, profiles = get_lines_routes_vehicles_profiles(
        pt_schedule, pt_stops, lines=lines, link_ids=link_ids
    )

    for lname, rid, veh, mode in zip(*lrvs.values()):
        cumulative = 0
        route_profile = profiles[lname][rid]
        for i, info in enumerate(pt_counts[veh]):

            if info['arrival'] < start:
                cumulative = cumulative + info['entered'] - info['left']
                continue
            if 'departure' in info and info['departure'] > end:
                break

            if aggregate_by:
                seg_start = max([t for t in timeline if t <= info['arrival']])
            else:
                seg_start = info['arrival']

            # for stop, trails in route_profile:
            #     if info['stop'] == stop:
            #         for link in trails:
            #             if link_ids is not None:
            #                 if link not in link_ids:
            #                     continue
            #             pt_links_time_stats[lname][seg_start][link] += cumulative
            for link in route_profile[i - 1][-1]:
                if link_ids is not None:
                    if link not in link_ids:
                        continue
                pt_links_time_stats[lname][seg_start][link] += cumulative

            cumulative -= info['left']
            cumulative += info['entered']

    pt_links_time_stats = defaultdict2dict(pt_links_time_stats)
    if not aggregate_by:
        for lname, timestep_data in pt_links_time_stats.items():
            pt_links_time_stats[lname] = {
                k: timestep_data[k] for k in sorted(timestep_data)
            }
    return pt_links_time_stats


def get_pt_stops_time_plot_df(
    pt_stops_time_stats: Dict[str, Dict[float, Dict[str, int]]],
    pt_stops: PtStops,
    link_id: str,
    as_geo: bool = False,
    crs: Optional[str] = None
) -> Union[pd.DataFrame, gpd.GeoDataFrame]:
    df_rows = []
    for line, timestepdata in pt_stops_time_stats.items():
        for timestep, stopsdata in timestepdata.items():
            for stop, info in stopsdata.items():
                row = dict(line=line, timestep=timestep, stop=stop, **info)
                df_rows.append(row)

    pt_stops_time_plot_df = pd.DataFrame(df_rows)
    pt_stops_time_plot_df['timestep'] = pd.to_datetime(
        pt_stops_time_plot_df['timestep'], unit='s'
    )

    pt_stops_df = pd.DataFrame(pt_stops).transpose()
    pt_stops_df.index.name = 'stop'
    pt_stops_df.reset_index(inplace=True)

    pt_stops_time_plot_df = pt_stops_time_plot_df.merge(
        pt_stops_df, how='left', on='stop'
    )

    if as_geo:
        pt_stops_time_plot_gdf = gpd.GeoDataFrame(
            pt_stops_time_plot_df,
            geometry=gpd.points_from_xy(
                x=pt_stops_time_plot_df['x'],
                y=pt_stops_time_plot_df['y']
            )
        )
        pt_stops_time_plot_gdf['timestep'] = pt_stops_time_plot_gdf['timestep'].astype(str)
        return pt_stops_time_plot_gdf
    return pt_stops_time_plot_df


def get_pt_link_time_plot_df(
    pt_links_time_stats: Dict[str, Dict[float, Dict[str, int]]],
    pt_net: gpd.GeoDataFrame,
    link_id: str
    ) -> pd.DataFrame:
    passengers_lines = {}

    for line in pt_links_time_stats:
        passengers_lines[line] = {
            'timestep': list(pt_links_time_stats[line].keys()),
            'passengers': []
            }
        for timestep in pt_links_time_stats[line]:
            if link_id in pt_links_time_stats[line][timestep]:
                passengers_lines[line]['passengers'].append(
                    pt_links_time_stats[line][timestep][link_id]
                    )
            else:
                passengers_lines[line]['passengers'].append(0)
        if all(c == 0 for c in passengers_lines[line]['passengers']):
            del passengers_lines[line]

    passenger_lines = {
        line: passengers_lines[line] for line in sorted(passengers_lines)
        }

    pt_link_time_plot_df = pd.DataFrame(passenger_lines).transpose().rename_axis('line')
    pt_link_time_plot_df = pt_link_time_plot_df.explode(['timestep', 'passengers'])
    pt_link_time_plot_df['timestep'] = pd.to_datetime(
        pt_link_time_plot_df['timestep'], unit='s'
        )
    pt_link_time_plot_df.reset_index(inplace=True)
    return pt_link_time_plot_df


def get_pt_link_time_plot(
        pt_link_time_plot_df: pd.DataFrame,
        pt_net: gpd.GeoDataFrame,
        link_id: str
):
    try:
        info = pt_net[pt_net['link_id'] == link_id].iloc[0].to_dict()
        info['from_stop'], info['to_stop'], info['lines']
    except IndexError:
        raise RuntimeError('No such link in the network')
    except KeyError:
        raise RuntimeError(
            'Network does not have stop name and lines related columns'
        )

    segment_name = f'{info["from_stop"]} — {info["to_stop"]}'
    title = f'Stats of link {info["link_id"]} ({segment_name})'
    title += f'\nLines: {info["lines"]}'
    subtitle = '\n'.join(
        f'{k}: {v}' for k, v in info.items()
        if k not in ['geometry', 'link_id', 'from_stop', 'to_stop',
                     'nofacility', 'lines', 'oneway', 'permlanes']
        )

    diffs = np.diff(pt_link_time_plot_df['timestep'])
    every = td(seconds=pd.Series(diffs).mode().item().total_seconds())  # gives errors

    fig, ax = plt.subplots(figsize=LINK_STATS_FIGURE_SIZE)
    ax.set_title(title)
    dt_fmt = mdates.DateFormatter('%H:%M')
    ax.xaxis.set_major_formatter(dt_fmt)
    ax.xaxis.set_minor_formatter(dt_fmt)
    # ax.xaxis.major_ticklabels.set_ha('center')
    ax.minorticks_on()

    grp = pt_link_time_plot_df.set_index('timestep').groupby('line')
    grp['passengers'].plot(ax=ax, legend=True)

    if len(ax.get_lines()) > 1:
        total = pd.Series(data=sum(df['passengers'] for line, df in grp),
                          index=pt_link_time_plot_df['timestep'].unique(),
                          name='total')
        total.plot(ax=ax, label='total', alpha=0.3,
                   linestyle='--', colormap="cubehelix")

    ax.set_xlabel(f'Time (every {every})')
    ax.set_ylabel('Count [passengers]')
    ax.legend()
    plt.tight_layout()

    bbox = ax.get_position()
    plt.suptitle(
        subtitle, fontsize=8, ha='left', va='top',
        y=bbox.ymax - bbox.ymax * .01, x=bbox.xmin + bbox.xmax * .01
    )
    ax.tick_params(
        axis='x', which='major', labelrotation=90
    )
    ax.tick_params(
        axis='x', which='minor', labelrotation=90, labelsize='small'
    )
    return fig


def get_routes_details(
        pt_counts: PtCounts,
        pt_schedule: _ElementTree,
        pt_stops: PtStops,
        net: gpd.GeoDataFrame,
        lines: List[str],
        link_id: Optional[str] = None,
        start: int = 0,
        end: int = 86400
) -> Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Get info about in/out passengers on stops and passengers on links.

    Parameters
    ----------
    pt_counts : PtCounts
        Entering and leaving counts from JSON.
    pt_schedule : _ElementTree
        Transit schedule tree.
    pt_stops : PtStops
        Stops IDs with attributes
    net : gpd.GeoDataFrame
        A network with ALL links.
    lines : List[str]
        List of short line string names (as in GTFS).
        Works only with named lines.
    start : int, optional
        Start of time interval. The default is 0.
    end : int, optional
        End of time interval. The default is 86400.

    Returns
    -------
    Tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]
        Net and stops with results.

    """
    stops_gdf = pt_stops_to_gdf(
        pt_stops, crs=':'.join(net.crs.to_authority()) if net.crs else None
    )

    linkstats = {}
    stopstats = {}
    for line in lines:
        line_linkstats, line_stopstats = get_pt_stats(
            pt_counts, pt_schedule, pt_stops, lines=[line],
            start=start, end=end
        )
        linkstats[line] = line_linkstats
        stopstats[line] = line_stopstats

    pt_nets_gdfs = []
    pt_stops_gdfs = []
    for line in lines:
        pt_net = merge_net_pt_counts(net, linkstats[line], drop_empty=True)
        pt_net = add_stop_name_columns(pt_net, pt_stops)
        pt_net['route'] = line
        pt_stops_counts = merge_stops_pt_counts(
            stops_gdf, stopstats[line], drop_empty=True
        )
        pt_stops_counts['route'] = line
        pt_nets_gdfs.append(pt_net)
        pt_stops_gdfs.append(pt_stops_counts)

    total_pt_net = gpd.GeoDataFrame(pd.concat(pt_nets_gdfs), crs=net.crs)
    total_pt_stops = gpd.GeoDataFrame(pd.concat(pt_stops_gdfs), crs=net.crs)
    return total_pt_net, total_pt_stops


def extract_stop_name(
        stop_id: str,
        pt_stops: PtStops
) -> Optional[str]:
    """
    Get stop name, if there's any.

    Parameters
    ----------
    stop_id : str
        The ID of a stop that is being searched for.
    pt_stops : PtStops
        Public transport stops object.

    Returns
    -------
    Optional[str]
        None if `name` attribute doesn't exist.

    """
    stop_dict = pt_stops[stop_id]
    if 'name' in stop_dict:
        return stop_dict['name']


def map_trip_on_pt_schedule(
        pt_counts: _ElementTree,
        access_stop_id: str,
        egress_stop_id: str,
        transit_route: str,
        departure_time: Union[td, str]
):
    pass


def get_pt_decay_diagrams_data(
        pt_schedule: _ElementTree,
        pt_stops: PtStops,
        pt_counts: PtCounts,
        legs_df: pd.DataFrame,
        link_ids: List[str] = None,
        stop_ids: List[str] = None,
        stop_ids_type: Literal['id', 'linkRefId', 'name'] = 'id',
        lines: Optional[List[str]] = None,
        start: int = 0,
        end: int = 86400
):
    raise NotImplementedError(
        'This function is in development'
    )

    if stop_ids is not None and link_ids is not None:
        raise ValueError(
            'Only one of `link_ids` or `stop_ids` must be provided'
        )
    if stop_ids is None and link_ids is None:
        raise ValueError('Either `link_ids` or `stop_ids` must be provided')

    lrvs, profiles = get_lines_routes_vehicles_profiles(
        pt_schedule, pt_stops, lines=lines,
        link_ids=link_ids, stop_ids=stop_ids
    )

    vroutes = {v: set() for v in lrvs['routes']}
    for veh, route in zip(lrvs['vehicles'], lrvs['routes']):
        vroutes[route].add(veh)

    pt_legs_df = legs_df[legs_df['mode'] == 'pt'].sort_values('dep_time')
    for col in ['dep_time', 'trav_time', 'wait_time']:
        pt_legs_df[col] = pd.to_timedelta(pt_legs_df[col])

    decay_data = []
    for trip_id, trip_df in pt_legs_df.groupby('trip_id'):
        for n, leg_row in trip_df.iterrows():
            veh_boarding = (
                leg_row['dep_time'] + leg_row['wait_time']
            ).total_seconds()
            veh_exiting = (
                leg_row['dep_time'] + leg_row['trav_time']
            ).total_seconds()
            leg_route = leg_row['transit_route']
            poss_vehs = list(vroutes[leg_route])
            veh_arrival_diffs = defaultdict(int)
            for poss_veh in poss_vehs:
                veh_counts = pt_counts[poss_veh]
                for stop_count in veh_counts:
                    if stop_count['stop'] == leg_row['access_stop_id']:
                        diff = stop_count['departure'] - veh_boarding
                        if diff >= 0:
                            veh_arrival_diffs[poss_veh] += diff
                    if stop_count['stop'] == leg_row['egress_stop_id']:
                        diff = veh_exiting - stop_count['arrival']
                        if diff >= 0:
                            veh_arrival_diffs[poss_veh] += diff


def get_pt_transfers(
        pt_schedule: _ElementTree,
        pt_stops: PtStops,
        legs_df: pd.DataFrame,
        start: int = 0,
        end: int = 86400,
        flush_to: Optional[Union[str, Path]] = None,
        flush_n: int = 5000
) -> Optional[pd.DataFrame]:
    """
    Derive transfers from legs table.

    Parameters
    ----------
    pt_schedule : _ElementTree
        Transit schedule tree.
    pt_stops : PtStops
        Stops object.
    legs_df : pd.DataFrame
        Legs table from MATSim output.
    start : int, optional
        Earliest transfer time time in seconds. The default is 0.
    end : int, optional
        Latest transfer time in seconds. The default is 86400.
    flush_to : Optional[Union[str, Path]], optional
        If not None, write processed data to file. The default is None.
        Helps to avoid overwhelming of the RAM.
    flush_n : int, optional
        Write every N transfers. Works if ``flush_to`` is not None.
        The default is 5000.

    Returns
    -------
    Optional[pd.DataFrame]
        If ``flush_to`` is specified, None is returned.

    """
    pt_legs_df = legs_df[legs_df['mode'] == 'pt'].sort_values('dep_time')
    for col in ['dep_time', 'trav_time', 'wait_time']:
        pt_legs_df[col] = pd.to_timedelta(pt_legs_df[col])

    lrvs, profiles = get_lines_routes_vehicles_profiles(pt_schedule, pt_stops)
    vtypes = {
         ln: md for ln, md in zip(lrvs['routes'], lrvs['modes'])
    }
    lnames = {
         rid: lnm for rid, lnm in zip(lrvs['routes'], lrvs['lines'])
    }

    start_td = pd.Timedelta(seconds=start)
    end_td = pd.Timedelta(seconds=end)

    if flush_to is not None:
        started_writing = False
        if Path(flush_to).suffix.endswith('.gz'):
            flusher = gzip.open(
                flush_to, mode='wt', encoding='utf-8', newline='\n'
            )
        else:
            flusher = open(flush_to, mode='w', encoding='utf-8', newline='\n')

    transfers_rows = []
    for trip_id, trip_df in pt_legs_df.groupby('trip_id'):
        if len(trip_df) == 1:
            continue
        last_leg = trip_df.iloc[0]
        orig_stop = trip_df.iloc[0]['access_stop_id']
        orig_stop_name = extract_stop_name(
            stop_id=orig_stop, pt_stops=pt_stops
        )
        dest_stop = trip_df.iloc[-1]['egress_stop_id']
        dest_stop_name = extract_stop_name(
            stop_id=dest_stop, pt_stops=pt_stops
        )
        for i, leg_row in trip_df.iloc[1:].iterrows():
            arr_time = last_leg['dep_time'] + last_leg['trav_time']
            # departure is the start of waiting after arriving at the stop
            dep_time = leg_row['dep_time']
            if start_td <= dep_time <= end_td:
                from_stop = last_leg['egress_stop_id']
                from_stop_name = extract_stop_name(
                    stop_id=from_stop, pt_stops=pt_stops
                )
                to_stop = leg_row['access_stop_id']
                to_stop_name = extract_stop_name(
                    stop_id=to_stop, pt_stops=pt_stops
                )
                # after arriving to curr stop
                # and before boarding towards the next
                wait_time = leg_row['wait_time']
                # time equal to the skipped 'walk' leg
                transfer_time = dep_time - arr_time
                transfer_row = {
                    'person_id': last_leg['person'],
                    'trip_id': trip_id,
                    'from_id': from_stop,
                    'to_id': to_stop,
                    'from_name': from_stop_name,
                    'to_name': to_stop_name,
                    'origin_id': orig_stop,
                    'destination_id': dest_stop,
                    'origin_name': orig_stop_name,
                    'destination_name': dest_stop_name,
                    'from_route_id': last_leg['transit_route'],
                    'to_route_id': leg_row['transit_route'],
                    'from_line_id': last_leg['transit_line'],
                    'to_line_id': leg_row['transit_line'],
                    'from_line_name': lnames[last_leg['transit_route']],
                    'to_line_name': lnames[leg_row['transit_route']],
                    'from_line_mode': vtypes[last_leg['transit_route']],
                    'to_line_mode': vtypes[leg_row['transit_route']],
                    'arrival_time': dep_time,  # yes, that's correct
                    'departure_time': dep_time + wait_time,
                    'wait_time': wait_time,
                    'transfer_time': transfer_time
                }
                transfers_rows.append(transfer_row)
            if flush_to is not None and transfers_rows and len(transfers_rows) % flush_n == 0:
                part_transfers_df = pd.DataFrame(transfers_rows)
                for c in part_transfers_df.columns:
                    if not c.endswith('_time'):
                        continue
                    part_transfers_df[c] = part_transfers_df[c].apply(td2str)
                flusher.write(
                    part_transfers_df.to_csv(
                        index=False, **CSV_STYLE, header=not started_writing
                    )
                )
                started_writing = True
                transfers_rows.clear()
            last_leg = leg_row

    if flush_to is None:
        transfers_df = pd.DataFrame(transfers_rows)
        return transfers_df
    else:
        part_transfers_df = pd.DataFrame(transfers_rows)
        for c in part_transfers_df.columns:
            if not c.endswith('_time'):
                continue
            part_transfers_df[c] = part_transfers_df[c].apply(td2str)
        flusher.write(
            part_transfers_df.to_csv(
                index=False, header=False, **CSV_STYLE
            )
        )
        flusher.close()


def write_pt_transfers(
        transfers_df: pd.DataFrame,
        output_path: Union[str, Path]
):
    """
    Save transfers table while converting timedeltas to HH:MM:SS format.

    Parameters
    ----------
    transfers_df : pd.DataFrame
        Transfers table.
    output_path : Union[str, Path]
        Path to save the table.

    """
    w_transfers_df = transfers_df.copy()
    for c in w_transfers_df.columns:
        if pd.api.types.is_timedelta64_dtype(w_transfers_df[c]):
            w_transfers_df[c] = w_transfers_df[c].apply(td2str)
    w_transfers_df.to_csv(output_path, index=False, **CSV_STYLE)


def read_pt_transfers(
        transfers_path: Union[str, Path],
) -> pd.DataFrame:
    """
    Load transfers table and convert string `_time` columns to timedeltas.

    Parameters
    ----------
    transfers_path : Union[str, Path]
        Path to load the table from.

    Returns
    -------
    pd.DataFrame

    """
    transfers_df = pd.read_csv(transfers_path, **CSV_STYLE)
    for c in transfers_df.columns:
        if c.endswith('_time'):
            transfers_df[c] = pd.to_timedelta(transfers_df[c])
    return transfers_df


def get_pt_stop_transfers(
        find_ids: List[str],
        transfers_df: pd.DataFrame,
        id_type: Literal['id', 'name'] = 'name'
) -> pd.DataFrame:
    """
    Extract required stops from transfers table.

    Parameters
    ----------
    find_ids : List[str]
        List of strings with stops names or IDs.
    transfers_df : pd.DataFrame
        Table of transfers.
    id_type : Literal['id', 'name'], optional
        Whether to look for IDs or names of stops. The default is 'name'.

    Returns
    -------
    pd.DataFrame

    """

    stop_transfers_df = transfers_df[
        (transfers_df[f'from_{id_type}'].isin(find_ids)) |
        (transfers_df[f'to_{id_type}'].isin(find_ids))
    ].copy()

    return stop_transfers_df

    # for Brno only
    # city_lines = []
    # for num in range(1, 100):
    #     city_lines.extend([str(num), f'x{num}', f'E{num}', f'N{num}'])
    # stop_transfers_df.loc[
    #     ~stop_transfers_df['from_line_name'].isin(city_lines) &
    #     (stop_transfers_df['from_line_mode'] == 'bus'),
    #     'from_line_mode'
    # ] = 'suburban bus'
    # stop_transfers_df.loc[
    #     ~stop_transfers_df['to_line_name'].isin(city_lines) &
    #     (stop_transfers_df['to_line_mode'] == 'bus'),
    #     'to_line_mode'
    # ] = 'suburban bus'
    # stop_transfers_df.loc[
    #     stop_transfers_df['from_line_name'].isin([str(num) for num in range(25, 40)]) &
    #     (stop_transfers_df['from_line_mode'] == 'bus'),
    #     'from_line_mode'
    # ] = 'trolleybus'
    # stop_transfers_df.loc[
    #     stop_transfers_df['to_line_name'].isin([str(num) for num in range(25, 40)]) &
    #     (stop_transfers_df['to_line_mode'] == 'bus'),
    #     'to_line_mode'
    # ] = 'trolleybus'

    # Maybe we'll use that later
    # stop_transfers_origin_df = stop_transfers_df[
    #     stop_transfers_df[f'from_{id_type}'].isin(find_ids)
    # ].copy()
    # stop_transfers_origin_rail_df = stop_transfers_origin_df[
    #     stop_transfers_origin_df[f'from_line_mode'] == 'rail'
    # ].copy()
    # stop_transfers_origin_tram_df = stop_transfers_origin_df[
    #     stop_transfers_origin_df[f'from_line_mode'] == 'tram'
    # ].copy()

    # modes_share_abs = stop_transfers_origin_rail_df['to_line_mode'].value_counts()
    # modes_share_rel = modes_share_abs / modes_share_abs.sum()
    
    # modes_share_tram_abs = stop_transfers_origin_tram_df['to_line_mode'].value_counts()
    # modes_share_tram_rel = modes_share_tram_abs / modes_share_tram_abs.sum()
