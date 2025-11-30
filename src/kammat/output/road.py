# -*- coding: utf-8 -*-
"""
Created on Thu Feb  2 14:07:50 2023

@author: dgrishchuk
"""

import lxml
import copy
import math
import string
import momepy
import matsim
import shapely
import warnings
# import logging
import platform
import itertools
import matplotlib
import numpy as np
import pandas as pd
import geopandas as gpd
from lxml import etree
import matplotlib.dates as mdates
from shapely.affinity import rotate
from shapely.geometry import LineString, Point, MultiLineString
from shapely.ops import substring  # , split, linemerge, nearest_points,
from pathlib import Path
from datetime import timedelta as td  # , datetime as dt
from matplotlib import pyplot as plt
from collections import defaultdict, Counter
from itertools import product
from kammat.output.utils import DbHandler
from typing import Union, List, Tuple, Dict, Optional, Sequence

# from kammat.output.utils import get_timestep_precision
from kammat.output.utils import (
    round_timestep, defaultdict2dict,
    EVENTS_MODES, LINK_STATS_DF_COLS, LINK_STATS_FIGURE_SIZE,
    RIBBON_DIAGRAMS_DF_COLS, RIBBON_DIAGRAMS_GROUP_DF_COLS,
    get_timestep_precision, get_timeline
)

MAX_TURN_WIDTH = 10
MIN_TURN_WIDTH = 1
SPACE_BW_TURNS = 1
NORMAL_RD_TEXT_SIZE = 10
NORMAL_RD_CIRCLE_RADIUS = 100
MIN_RD_TEXT_SIZE = 2

MODES_COLORS = {
    'pt': 'C0',
    'car': 'C3',
    'truck': 'C5',
    'citylog': 'C6',
    'total': 'C7'
}


def get_link_stats_plot(
        link_stats: Dict[str, List[float]],
        net: gpd.GeoDataFrame
) -> matplotlib.figure.Figure:
    try:
        info = net[net['link_id'] == link_stats['link_id']].iloc[0].to_dict()
    except Exception:
        raise RuntimeError('No such link in the network')

    title = f'Stats of link {info["link_id"]}'
    subtitle = '\n'.join(
        f'{k}: {v}' for k, v in info.items() if k not in ['geometry', 'link_id']
    )
    every_s = get_timestep_precision(link_stats)
    every = td(seconds=every_s)

    fig, ax1 = plt.subplots(figsize=LINK_STATS_FIGURE_SIZE)
    ax2 = ax1.twinx()
    ax1.set_title(title)
    ax1.set_xlabel(f'Time (every {every})')
    ax1.set_ylabel('Count [vehicles]')
    ax2.set_ylabel('Capacity usage [%]')
    ax1.minorticks_on()
    ax2.minorticks_on()

    plots_count = 0
    tdtimesteps = list(pd.to_datetime(link_stats['timestep'], unit='s'))

    for mode, mode_counts in link_stats.items():
        if mode not in EVENTS_MODES or not mode_counts:
            continue
        line, = ax1.plot(tdtimesteps, mode_counts, label=mode)
        
        cap = info['capacity']
        if every_s != 3600:
            cap *= every_s / 3600
        mode_usages = [mc * 100 / cap for mc in mode_counts]
        ax2.plot(tdtimesteps, mode_usages, alpha=1)
        plots_count += 1

    if plots_count > 1:
        total_counts = list(sum(
            np.array(link_stats[mode]) for mode in EVENTS_MODES if link_stats[mode]
        ))
        total_usages = [tc * 100 / info['capacity'] for tc in total_counts]
        line, = ax1.plot(tdtimesteps, total_counts, label='total')
        ax2.plot(tdtimesteps, total_usages, alpha=1)

    ax1.legend()
    plt.tight_layout()

    bbox = ax1.get_position()
    plt.suptitle(
        subtitle,
        fontsize=8, ha='left', va='top',
        y=bbox.ymax - bbox.ymax * .01,
        x=bbox.xmin + bbox.xmax * .01
    )

    ax1.xaxis.set_major_formatter(mdates.DateFormatter('%H:%M'))
    return fig


def load_network(
        path: Union[str, Path],
        crs: str = None,
        as_geo: bool = True,
        include_links: bool = True,
        include_nodes: bool = False
        ) -> Union[Tuple[Union[gpd.GeoDataFrame, pd.DataFrame]],
                   Union[gpd.GeoDataFrame, pd.DataFrame]]:
    """
    B.

    Parameters
    ----------
    path : Union[str, Path]
        DESCRIPTION.
    crs : str, optional
        DESCRIPTION. The default is None.
    as_geo : bool, optional
        DESCRIPTION. The default is True.
    include_links : bool, optional
        DESCRIPTION. The default is True.
    include_nodes : bool, optional
        DESCRIPTION. The default is False.

    Returns
    -------
    Union[Tuple[Union[gpd.GeoDataFrame, pd.DataFrame]],
               Union[gpd.GeoDataFrame, pd.DataFrame]]

    """
    if not include_links and not include_nodes:
        raise ValueError('You must pick at least one element (links / nodes)')

    netobj = matsim.read_network(path)

    if include_links:
        if as_geo:
            net = netobj.as_geo(crs)
        else:
            net = netobj.links
        if len(netobj.link_attrs):
            for attr, df in netobj.link_attrs.groupby('name'):
                if attr == 'geometry' and as_geo:
                    df['value'] = gpd.GeoSeries.from_wkt(df['value'], crs=crs)
                    df = gpd.GeoDataFrame(df)
                    orig_geom = net['geometry']
                    net.drop('geometry', axis=1, inplace=True)
                    net = net.merge(
                        df.drop('name', axis=1),
                        how='left', on='link_id'
                    )
                    net = gpd.GeoDataFrame(
                        net.rename({'value': 'geometry'}, axis=1), crs=crs
                    )
                    net.loc[
                        net['geometry'].isna(), 'geometry'
                    ] = orig_geom[net['geometry'].isna()]
                else:
                    net = net.merge(
                        df.drop('name', axis=1).rename({'value': attr}, axis=1),
                        how='left', on='link_id'
                    )

        if not include_nodes:
            return net

    if include_nodes:
        nodes = netobj.nodes
        nodes['geometry'] = gpd.points_from_xy(nodes['x'], nodes['y'])
        nodes = gpd.GeoDataFrame(nodes, crs=crs)
    if len(netobj.node_attrs):
        for attr, df in netobj.node_attrs.groupby('name'):
            nodes = nodes.merge(
                df.drop('name', axis=1).rename({'value': attr}, axis=1),
                how='left', on='node_id'
            )
    if not include_links:
        return nodes
    return net, nodes


def get_links_pairs(
        net: gpd.GeoDataFrame,
        node_id: str,
        tolerance: float = 1.0
        ):
    """
    Get bidirectional links. If link is single direction, it has None in pair.

    Parameters
    ----------
    net : gpd.GeoDataFrame
        DESCRIPTION.
    node_id : str
        DESCRIPTION.

    Returns
    -------
    pairs : TYPE
        DESCRIPTION.

    """
    pairs = {}

    outedges = net[net['from_node'] == node_id].copy()
    inedges = net[net['to_node'] == node_id].copy()
    alledges = pd.concat([outedges, inedges])

    for n, outedge in alledges.iterrows():
        endcoord = list(outedge.geometry.coords)[-1]
        startcoord = list(outedge.geometry.coords)[0]
        dists1 = alledges.apply(
            lambda r: math.dist(list(r.geometry.coords)[0], endcoord), axis=1
        )
        dists2 = alledges.apply(
            lambda r: math.dist(list(r.geometry.coords)[-1], startcoord), axis=1
        )
        if dists1.min() < tolerance and dists2.min() < tolerance:
            inedge = alledges.loc[
                (dists1 < tolerance) &
                (dists2 < tolerance)
            ].iloc[0]
            if outedge['link_id'] not in pairs:
                pairs[outedge['link_id']] = inedge['link_id']
            if inedge['link_id'] not in pairs:
                pairs[inedge['link_id']] = outedge['link_id']
        else:
            pairs[outedge['link_id']] = None
    return pairs


def extrapolate_line(
        p1: Tuple[float],
        p2: Tuple[float],
        target_length: Union[int, float] = 100
        ) -> LineString:
    """Create a line extrapolated in p1 -> p2 direction."""
    ratio = target_length / math.dist(p1, p2)
    np1 = p1
    np2 = (
        p1[0] + ratio * (p2[0] - p1[0]),
        p1[1] + ratio * (p2[1] - p1[1])
    )
    return LineString([np1, np2])


def get_unique_link_geoms(
        net: gpd.GeoDataFrame,
        pairs: Dict[str, str],
        node_id: str
        ) -> Dict[str, LineString]:

    unique_link_geoms = {}
    for link in pairs:
        if pairs[link] in unique_link_geoms:
            geom = unique_link_geoms[pairs[link]]
        else:
            row = net[net['link_id'] == link].iloc[0]
            if row['from_node'] == node_id:
                geom = row['geometry']
            else:
                geom = LineString(reversed(list(row['geometry'].coords)))
            pregeom = list(geom.coords)
            geom = extrapolate_line(
                p1=pregeom[0],
                p2=pregeom[-1],
                target_length=100
            )
            splitter = geom.interpolate(25)
            geom = LineString(
                [list(geom.coords)[0],
                 list(splitter.coords)[0],
                 list(geom.coords)[-1]]
            )
        unique_link_geoms[link] = geom

    return unique_link_geoms


def get_turns_groups(
        nodeturns: Dict[Tuple[str], int],
        pairs: Dict[str, str],
        rename_groups: Optional[Dict[str, str]] = None,
        group_prefix: Optional[str] = ''
) -> Dict[Tuple[str], Dict[str, str]]:
    pair_sets = list(set(
        tuple(set(pair)) for pair in zip(pairs.keys(), pairs.values())
    ))

    groups_names = {}
    poss_group_names = iter(
        group_prefix + letter for letter in string.ascii_uppercase
    )
    for turn in pair_sets:
        from_edge, to_edge = turn
        if rename_groups:
            if from_edge in rename_groups:
                group_name = rename_groups[from_edge]
            elif to_edge in rename_groups:
                group_name = rename_groups[to_edge]
            else:
                group_name = next(poss_group_names)
        else:
            group_name = next(poss_group_names)
        for edge in turn:
            if edge is not None:
                groups_names[edge] = group_name

    groups = defaultdict(lambda: defaultdict(list))

    turns_groups = {}
    for turn in nodeturns:
        if turn not in groups[groups_names[turn[0]]]['outbound']:
            groups[groups_names[turn[0]]]['outbound'].append(turn)
        if turn not in groups[groups_names[turn[1]]]['inbound']:
            groups[groups_names[turn[1]]]['inbound'].append(turn)
        turns_groups[turn] = {
            'from_group': groups_names[turn[0]],
            'to_group': groups_names[turn[1]]
            }
    groups = defaultdict2dict(groups)
    return turns_groups, groups


def calculate_line_angle(
        pa: Tuple[float],
        pb: Tuple[float]
        ) -> float:
    """
    Get angle between two points.

    Parameters
    ----------
    pa : Tuple[float]
        First point.
    pb : Tuple[float]
        Second point.

    Returns
    -------
    float
        Angle between 0 and 360

    """
    angle = math.atan2(pa[1] - pb[1], pa[0] - pb[0])
    angle_degrees = (angle * 360 / (2 * math.pi)) % 360
    return angle_degrees


def calculate_angle(
        linea: List[Tuple[float]],
        lineb: List[Tuple[float]]
        ) -> float:
    """
    Get angle between two lines.

    Make sure they are rotated correctly.

    Parameters
    ----------
    linea : List[Tuple[float]]
        First line.
    lineb : List[Tuple[float]]
        Second line.

    Returns
    -------
    float
        Angle between 0 and 360

    """
    line1x1, line1y1 = linea[0]
    line1x2, line1y2 = linea[-1]

    line2x1, line2y1 = lineb[0]
    line2x2, line2y2 = lineb[-1]

    angle1 = math.atan2(line1y1 - line1y2, line1x1 - line1x2)
    angle2 = math.atan2(line2y1 - line2y2, line2x1 - line2x2)
    angle_degrees = ((angle1 - angle2) * 360 / (2 * math.pi)) % 360 - 180

    return angle_degrees


def det(
        a: Tuple[float],
        b: Tuple[float]
        ) -> float:
    return a[0] * b[1] - a[1] * b[0]


def get_line_intersection(
        line1: List[Tuple[float]],
        line2: List[Tuple[float]]
        ) -> Tuple[float]:
    xdiff = (line1[0][0] - line1[-1][0], line2[0][0] - line2[-1][0])
    ydiff = (line1[0][1] - line1[-1][1], line2[0][1] - line2[-1][1])

    div = det(xdiff, ydiff)
    if div == 0:
        return None

    d = (det(*line1), det(*line2))
    x = det(d, xdiff) / div
    y = det(d, ydiff) / div
    return x, y


def get_smooth_turn(
        linea: LineString,
        lineb: LineString,
        smoothing_points_count: int = 10,
        zero_angle_tolerance: float = 0.1,
        left_sided: bool = False
        ) -> LineString:
    """
    Get smoothed turn connection with Bezier curve.

    All lines must FACE AWAY FROM intersection and consist of two segments!

    Parameters
    ----------
    linea : LineString
        First geometry of a turn. Must have two segments (three points).
    lineb : LineString
        Second geometry of a turn. Must have two segments (three points).
    center : Point, optional
        Point to use as an intersection center.
        If None, use lines' own intersection point.
    smoothing_points_count : int, optional
        Count of points in Bezier curve

    Returns
    -------
    LineString
        Oriented in correct direction LineString.

    """
    import bezier

    parta = list(linea.coords)[0:2]
    partb = list(lineb.coords)[0:2]
    lineac = list(linea.coords)
    linebc = list(lineb.coords)

    angle = calculate_angle(parta, partb)
    if angle < -170 or angle > 170:
        center = LineString([lineac[1], linebc[1]]).centroid
    elif -10 <= angle <= 10:
        diff_dist = linea.distance(lineb) / 2
        middle_geom = linea.parallel_offset(
            diff_dist, side='right' if left_sided else 'left'
            )
        middle_geom_coords = list(middle_geom.coords[1:3])
        if len(middle_geom_coords) != 2:
            middle_geom_coords = list(middle_geom.coords[:2])
        if not left_sided:
            diff_dist = -diff_dist
        offset_geom = extrapolate_line(*middle_geom_coords, -diff_dist * 2)
        center = Point(list(offset_geom.coords)[-1])
    else:
        center = Point(get_line_intersection(parta, partb))

    if linea.intersects(lineb):
        shorta = LineString([parta[0], list(center.coords)[0]])
        shortb = LineString([partb[0], list(center.coords)[0]])
        linea = extrapolate_line(*parta, target_length=shorta.length * 0.8)
        lineb = extrapolate_line(*partb, target_length=shortb.length * 0.8)

    nodes_coords = [lineac[1]] + list(center.coords) + [linebc[1]]
    x, y = np.array(list(zip(*nodes_coords)))
    nodes = np.asfortranarray([x, y])
    curve = bezier.Curve(nodes, degree=2)
    s_vals = np.linspace(0, 1, smoothing_points_count)
    points = curve.evaluate_multi(s_vals)
    smooth_turn = LineString([lineac[0]] + list(zip(*points)) + [linebc[-1]])
    return smooth_turn


def get_turns_by_node(
        net: gpd.GeoDataFrame,
        turns: Dict[float, Dict[str, int]],
        pairs: Dict[str, str],
        node_id: str,
        start: int = 0,
        end: int = 86399,
        mode: str = 'car'
        ) -> Dict[str, int]:

    nodeturns = defaultdict(int)

    combs = {
        turn for turn in product(pairs.keys(), pairs.keys())
        if turn[0] != turn[-1] and
        ((net['to_node'] == node_id) & (net['link_id'] == turn[0])).any() and
        ((net['from_node'] == node_id) & (net['link_id'] == turn[-1])).any()
    }

    for timestep in turns[mode]:
        if not (start <= timestep <= end):
            continue
        for turn in combs:
            if turn in turns[mode][timestep]:
                nodeturns[turn] += turns[mode][timestep][turn]
            else:
                nodeturns[turn] += 0

    nodeturns = {k: v for k, v in nodeturns.items() if v != 0}
    return nodeturns


def get_intersection_data(
        net: gpd.GeoDataFrame,
        turns: Dict[float, Dict[str, int]],
        node_id: str,
        tolerance: float = 1.0,
        start: int = 0,
        end: int = 86399,
        mode: str = 'car'
):
    pairs = get_links_pairs(net, node_id, tolerance)
    unique_link_geoms = get_unique_link_geoms(net, pairs, node_id)
    nodeturns = get_turns_by_node(
        net=net,
        turns=turns,
        pairs=pairs,
        node_id=node_id,
        start=start,
        end=end,
        mode=mode
    )
    turns_groups, groups = get_turns_groups(nodeturns, pairs)
    turns_geoms, thicknesses = get_intersection_geometry(
        net, nodeturns, unique_link_geoms, turns_groups, groups
    )
    return nodeturns, turns_geoms, turns_groups, thicknesses


def get_intersection_data_db(
        net: gpd.GeoDataFrame,
        db_path: Union[str, Path],
        node_id: str,
        tolerance: float = 1.0,
        start: int = 0,
        end: int = 86399,
        mode: str = 'car'
):
    pairs = get_links_pairs(net, node_id, tolerance)
    unique_link_geoms = get_unique_link_geoms(net, pairs, node_id)
    nodeturns = get_turns_by_node_db(
        net=net,
        db_path=db_path,
        pairs=pairs,
        node_id=node_id,
        start=start,
        end=end,
        mode=mode
    )
    turns_groups, groups = get_turns_groups(nodeturns, pairs)
    turns_geoms, thicknesses = get_intersection_geometry(
        net, nodeturns, unique_link_geoms, turns_groups, groups
    )
    return nodeturns, turns_geoms, turns_groups, thicknesses


def get_turns_by_node_db(
        net: gpd.GeoDataFrame,
        db_path: Union[str, Path],
        pairs: Dict[str, str],
        node_id: str,
        start: int = 0,
        end: int = 86399,
        mode: str = 'car'
) -> Dict[str, int]:
    dbh = DbHandler(db_path=db_path)
    dbh.connect()
    combs = {
        turn for turn in product(pairs.keys(), pairs.keys())
        if turn[0] != turn[-1] and
        ((net['to_node'] == node_id) & (net['link_id'] == turn[0])).any() and
        ((net['from_node'] == node_id) & (net['link_id'] == turn[-1])).any()
    }
    unique_orig_ids = {k[0] for k in combs}.union({v[1] for v in combs})
    orig_links_ids_map = dict(dbh._conn.execute(
        f"""
        SELECT orig_link_id, link_id FROM links WHERE orig_link_id IN (
            {','.join(f"'{v}'" for v in unique_orig_ids)}
        );
        """
    ).fetchall())
    link_ids_orig_map = {v: k for k, v in orig_links_ids_map.items()}

    combs_ids = set()
    for fr, to in combs:
        if fr not in orig_links_ids_map or to not in orig_links_ids_map:
            continue
        combs_ids.add((orig_links_ids_map[fr], orig_links_ids_map[to]))

    strlinkids = ' OR\n'.join(
        [f"(prev_link_id = {p[0]} AND link_id = {p[1]})" for p in combs_ids]
    )
    turns_times = dbh._conn.execute(
        f"""SELECT * FROM events
        WHERE "time" BETWEEN {start} AND {end}
        AND ({strlinkids});
        """
    ).fetchall()
    dbh.close()

    pick_trip_ids = dbh.get_mode_trip_ids(mode=mode)
    nodeturns = Counter(
        [row[1:3] for row in turns_times if row[0] in pick_trip_ids]
    )
    nodeturns = {
        (link_ids_orig_map[k[0]], link_ids_orig_map[k[1]]): v
        for k, v in nodeturns.items()
    }
    nodeturns = {k: v for k, v in nodeturns.items() if v != 0}
    return nodeturns


def get_nodes_by_links(
        net: gpd.GeoDataFrame,
        links: List[str],
        tolerance: float = 1.0
):
    netlinks = net[net['link_id'].isin(links)]
    if len(netlinks) != len(links):
        raise RuntimeError('Not all links are found in the network!')

    subgraph = momepy.gdf_to_nx(netlinks, directed=True)
    innernodes = {}
    for n, ndata in subgraph.nodes(data=True):
        outd = subgraph.out_degree[n]
        ind = subgraph.in_degree[n]
        if outd == 0 or ind == 0:
            continue
        outes = list(subgraph.out_edges(n, keys=True, data=True))
        ines = list(subgraph.in_edges(n, keys=True, data=True))
        if outd == ind == 1:
            if outes[0][0] == ines[0][1]:
                continue
            if math.dist(outes[0][0], ines[0][1]) < tolerance:
                continue
        ndata['node'] = ines[0][-1]['to_node']
        innernodes[ines[0][-1]['to_node']] = {
            'in': set(e[-1]['link_id'] for e in ines),
            'out': set(e[-1]['link_id'] for e in outes)
        }
    nodes_affections = {
        nid: set() for nid in innernodes
    }
    for nid1, inout_info1 in innernodes.items():
        for nid2, inout_info2 in innernodes.items():
            if nid1 == nid2:
                continue
            nodes_affections[nid1] = set(itertools.chain.from_iterable([
                inout_info1['in'].intersection(inout_info2['out']),
                inout_info1['out'].intersection(inout_info2['in']),
                nodes_affections[nid1]
            ]))
    nodes_order = sorted(
        nodes_affections,
        key=lambda x: len(nodes_affections[x]),
        reverse=True
    )
    will_have_fixed_groups = set(
        itertools.chain.from_iterable(nodes_affections.values())
    )
    subnodes, subnet = momepy.nx_to_gdf(subgraph)
    subnodes.dropna(inplace=True)
    return nodes_order, will_have_fixed_groups, subnodes, subnet


def get_intersection_data_by_links(
        net: gpd.GeoDataFrame,
        turns,
        links: List[str],
        tolerance: float = 1.0,
        start: int = 0,
        end: int = 86399,
        mode: str = 'car',
        move_by: Union[int, float] = 50
):
    node_ids, will_have_fixed_groups, subnodes, subnet = get_nodes_by_links(
        net=net, links=links, tolerance=tolerance
    )
    nodes_info = {
        node_id: {
            'pairs': None,
            'nodeturns': None,
            'turns_groups': None,
            'groups': None,
            'unique_link_geoms': None,
            'turns_geoms': None,
            'thicknesses': None
        }
        for node_id in node_ids
    }
    fixed_groups = {}
    max_flow = 0
    sum_flow = 0
    for node_id in node_ids:
        pairs = get_links_pairs(
            net=net, node_id=node_id, tolerance=tolerance
        )
        nodeturns = get_turns_by_node(
            net, turns, pairs, node_id, start, end, mode
        )
        turns_groups, groups = get_turns_groups(
            nodeturns, pairs,
            rename_groups=fixed_groups,
            group_prefix=f'{node_id}_'
        )
        for whfg in will_have_fixed_groups:
            if whfg in fixed_groups:
                continue
            for (from_link, to_link), from_to_group in turns_groups.items():
                from_group = from_to_group['from_group']
                to_group = from_to_group['to_group']
                if from_link == whfg:
                    fixed_groups[whfg] = from_group
                if to_link == whfg:
                    fixed_groups[whfg] = to_group
        max_node_flow = max(nodeturns.values())
        if max_node_flow > max_flow:
            max_flow = max_node_flow
        nodes_info[node_id]['pairs'] = pairs
        nodes_info[node_id]['nodeturns'] = nodeturns
        nodes_info[node_id]['turns_groups'] = turns_groups
        nodes_info[node_id]['groups'] = groups

    for node_id in node_ids:
        pairs = nodes_info[node_id]['pairs']
        nodeturns = nodes_info[node_id]['nodeturns']
        turns_groups = nodes_info[node_id]['turns_groups']
        groups = nodes_info[node_id]['groups']
        unique_link_geoms = get_unique_link_geoms(net, pairs, node_id)
        nodes_info[node_id]['unique_link_geoms'] = unique_link_geoms
        turns_geoms, thicknesses = get_intersection_geometry(
            net, nodeturns, unique_link_geoms, turns_groups, groups
        )
        nodes_info[node_id]['turns_geoms'] = turns_geoms
        nodes_info[node_id]['thicknesses'] = thicknesses

    new_nodes_info, connectors = adjust_node_turn_geoms(
        node_ids=node_ids, nodes_info=nodes_info, fixed_groups=fixed_groups,
        move_by=move_by
    )
    return new_nodes_info, connectors, subnodes, subnet


def sort_nodes_by_importance(
        node_ids: List[str],
        nodes_to_sort: List[str]
) -> List[str]: 
    # Create a dictionary that maps els in nodes_ids to their indices
    index_dict = {el: i for i, el in enumerate(node_ids)}

    # Sort based on the indices of els in nndes_ids
    sorted_nodes = [el for el in nodes_to_sort if el in index_dict]
    sorted_nodes.sort(key=lambda x: index_dict[x])

    # Add the remaining els from unsorted list
    sorted_nodes += [
        el for el in nodes_to_sort if el not in index_dict
    ]
    return sorted_nodes


def adjust_node_turn_geoms(
        node_ids: List[str],
        nodes_info,
        fixed_groups: Dict[str, str],
        move_by: Union[int, float] = 50
):
    movable_groups = []
    for n in node_ids:
        ngroups = set(
            nodes_info[n]['groups'].keys()).intersection(
                set(fixed_groups.values())
        )
        for ngroup in ngroups:
            if ngroup not in movable_groups:
                movable_groups.append(ngroup)

    new_nodes_info = {
        node_ids[0]: copy.deepcopy(nodes_info[node_ids[0]])
    }
    connectors = {}
    for mg in movable_groups:
        affected_nodes = {
            n: ni for n, ni in nodes_info.items()
            if mg in ni['groups']
        }
        imp_nodes = sort_nodes_by_importance(
            node_ids=node_ids, nodes_to_sort=list(affected_nodes.keys())
        )
        can_be_moved = {n for n in imp_nodes if n not in new_nodes_info}
        main_node_info = new_nodes_info[imp_nodes[0]]
        for inferior in imp_nodes[1:]:
            if inferior in new_nodes_info:
                inferior_node_info = new_nodes_info[inferior]
                new_inferior_node_info, connector = move_group_geoms(
                    main_node_info=main_node_info,
                    inferior_node_info=inferior_node_info,
                    group_id=mg,
                    move=False,
                    move_by=move_by
                )
            else:
                inferior_node_info = nodes_info[inferior]
                new_inferior_node_info, connector = move_group_geoms(
                    main_node_info=main_node_info,
                    inferior_node_info=inferior_node_info,
                    group_id=mg,
                    move=True,
                    move_by=move_by
                )
            new_nodes_info[inferior] = new_inferior_node_info
            connectors[(imp_nodes[0], inferior)] = connector
    # allturngeoms = []
    # for n, ninfo in new_nodes_info.items():
    #     allturngeoms.extend(
    #         list(ninfo['turns_geoms'].values())
    #     )
    # allturngeoms.extend(list(connectors.values()))
    # gpd.GeoDataFrame({'geometry': allturngeoms}).plot()
    return new_nodes_info, connectors


def move_group_geoms(
        main_node_info,
        inferior_node_info,
        group_id: str,
        move: bool = False,
        move_by: Union[int, float] = 50  # m
):
    new_inferior_node_info = copy.deepcopy(inferior_node_info)
    mginfo = main_node_info['groups'][group_id]
    iginfo = inferior_node_info['groups'][group_id]

    # All unique geoms MUST face AWAY from their respective nodes
    if 'outbound' in mginfo:
        main_geom = main_node_info['unique_link_geoms'][mginfo['outbound'][0][0]]
    else:
        main_geom = main_node_info['unique_link_geoms'][mginfo['inbound'][0][-1]]

    if 'outbound' in iginfo:
        infer_geom = inferior_node_info['unique_link_geoms'][iginfo['outbound'][0][0]]
    else:
        infer_geom = inferior_node_info['unique_link_geoms'][iginfo['inbound'][0][-1]]

    mgcoords = list(main_geom.coords)
    igcoords = list(infer_geom.coords)

    # creating a line from main geometry, that will be a buffer between
    # main and inferior coordinates
    angle_deg = calculate_line_angle(mgcoords[-1], mgcoords[0])
    angle_rad = math.radians(angle_deg)
    start = mgcoords[-1]
    end = Point(start[0] + move_by, start[1])
    pre_move_line = LineString([start, end])
    # this line is a connector as well
    move_line = rotate(
        pre_move_line, angle_rad, origin=start, use_radians=True
    )

    if move:
        mlcoords = list(move_line.coords)
        # we are comapring the LAST inferior coordinate to the LAST position
        # of the line we need to move to
        xdiff = mlcoords[-1][0] - igcoords[-1][0]
        ydiff = mlcoords[-1][1] - igcoords[-1][1]
        # now just shift all the inferior geometries using these ratios
        for link, geom in inferior_node_info['unique_link_geoms'].items():
            new_geom = shift_geometry(geom, xdiff, ydiff)
            new_inferior_node_info['unique_link_geoms'][link] = new_geom
        for turn, tgeom in new_inferior_node_info['turns_geoms'].items():
            new_tgeom = shift_geometry(tgeom, xdiff, ydiff)
            new_inferior_node_info['turns_geoms'][turn] = new_tgeom
    return new_inferior_node_info, move_line


def shift_geometry(
        geom: LineString,
        xdiff: Union[int, float],
        ydiff: Union[int, float]
) -> LineString:
    new_coords = []
    for c in list(geom.coords):
        nc = list(c)
        nc[0] += xdiff
        nc[1] += ydiff
        new_coords.append(nc)
    new_geom = LineString(new_coords)
    return new_geom


def get_turns_parts_offsets(
        order: List[Tuple[str]],
        thicknesses: Dict[Tuple[str], float],
        spacing: float = SPACE_BW_TURNS
) -> List[float]:
    offsets = []
    cumulative = 0
    for num, turn in enumerate(order):
        curr_thickness = thicknesses[turn]
        prev_thickness = 0 if num == 0 else thicknesses[order[num - 1]]
        cumulative += (curr_thickness / 2) + spacing + (prev_thickness / 2)
        offsets.append(cumulative)
    return offsets


def get_turns_parts_order(
        angles: Dict[Tuple[str], float],
        direction: str,
        zero_angle_tolerance: float = 0.1,
        left_sided: bool = False
        ) -> List[Tuple[str]]:
    order = sorted(angles, key=angles.get, reverse=direction == 'outbound')
    if left_sided:
        order = order[::-1]
    for turn, angle in angles.items():
        if -zero_angle_tolerance <= angle <= zero_angle_tolerance:
            order.remove(turn)
            order.insert(0, turn)
    return order


def get_intersection_geometry(
        net: gpd.GeoDataFrame,
        nodeturns: Dict[Tuple[str], int],
        unique_link_geoms: Dict[Tuple[str], LineString],
        turns_groups: Dict[Tuple[str], Dict[str, str]],
        groups: Dict[str, Dict[str, List[Tuple[str]]]],
        left_sided: bool = False
) -> Tuple[Dict[str, LineString]]:

    turns_parts_geoms = defaultdict(lambda: defaultdict(dict))
    thicknesses = {}
    groups_offsets = defaultdict(lambda: defaultdict(list))

    relative_turns_sizes = {
        t: c / sum(nodeturns.values()) for t, c in nodeturns.items()
    }
    # due to rotated end segments of turn bug, see below
    iswindows = platform.system().lower() == 'windows'

    for gr, group in groups.items():
        for direction, dirturns in group.items():
            angles = {}
            for dirturn in dirturns:
                froml = list(unique_link_geoms[dirturn[int(direction == 'outbound')]].coords)[::-1][:2]
                tol = list(unique_link_geoms[dirturn[int(direction == 'inbound')]].coords)[-2:]
                angle = calculate_angle(froml, tol) % 360
                angles[dirturn] = angle
                if dirturn not in thicknesses:
                    thickness = max(
                        relative_turns_sizes[dirturn] * MAX_TURN_WIDTH /
                        max(relative_turns_sizes.values()),
                        MIN_TURN_WIDTH
                    )
                    thicknesses[dirturn] = thickness
            order = get_turns_parts_order(angles, direction, left_sided=left_sided)
            offsets = get_turns_parts_offsets(order, thicknesses)
            base_geom = unique_link_geoms[dirturn[int(direction == 'inbound')]]
            sign = -1 if direction == 'outbound' else 1
            for turn, offset in zip(order, offsets):
                groups_offsets[gr][direction].append({
                    'turn': turn, 'offset': offset
                    })
                turns_parts_geoms[gr][turn][direction] = base_geom.parallel_offset(sign * offset)

    turns_geoms = {}
    for turn, data in turns_groups.items():
        start_geom = turns_parts_geoms[data['from_group']][turn]['outbound']
        end_geom = turns_parts_geoms[data['to_group']][turn]['inbound']
        if not left_sided:
            start_geom = substring(start_geom, 1, 0, normalized=True)
            # TODO wierdest bug, only occurs on Windows...
            if not iswindows:
                end_geom = substring(end_geom, 1, 0, normalized=True)
        turn_geom = get_smooth_turn(start_geom, end_geom, left_sided=left_sided)
        turns_geoms[turn] = turn_geom
    return turns_geoms, thicknesses


def get_intersection_plot(
        nodeturns: Dict[Tuple[str], int],
        turns_geoms: Dict[Tuple[str], LineString],
        thicknesses: Dict[Tuple[str], float],
        turns_groups: Dict[Tuple[str], Dict[str, str]],
        node_id: str,
        start: int,
        end: int,
        mode: str
        ) -> matplotlib.figure.Figure:
    fig, ax = plt.subplots()

    colors = {}
    ctext = []
    ccolors = []
    group_labels_geoms = defaultdict(list)
    group_labels_inout = defaultdict(lambda: {'in': 0, 'out': 0, 'sum': 0})
    # ax.set_prop_cycle(plt.cycler("color", plt.cm.Paired.colors))
    for turn, geom in turns_geoms.items():
        count = nodeturns[turn]
        coords = list(geom.coords)
        line, = ax.plot(
            *list(zip(*coords)),
            linewidth=thicknesses[turn],
            solid_capstyle='butt',
            label=' -> '.join(turn)
            )
        # TODO: implement color by from_group
        colors[turn] = line.get_color()
        ccolors.append([
            matplotlib.colors.to_rgb(line.get_color()) + (0.9,)
            if col in ['from_link', 'to_link'] else (0, 0, 0, 0)
            for col in RIBBON_DIAGRAMS_DF_COLS
            ])
        fg = turns_groups[turn]['from_group']
        tg = turns_groups[turn]['to_group']

        group_labels_inout[fg]['out'] += count
        group_labels_inout[fg]['sum'] += count
        group_labels_inout[tg]['in'] += count
        group_labels_inout[tg]['sum'] += count

        group_labels_geoms[fg].append(list(turns_geoms[turn].coords)[0])
        group_labels_geoms[tg].append(list(turns_geoms[turn].coords)[-1])
        ctext.append(
            [turn[0], turn[1], fg, tg, count]
        )

    # order
    ctext, ccolors = list(
        zip(*list(sorted(zip(ctext, ccolors), key=lambda zp: zp[0][2:-1])))
    )

    group_ctext = []
    for gname, gcoords in group_labels_geoms.items():
        if len(gcoords) > 1:
            centroid = LineString([Point(gcoord) for gcoord in gcoords]).centroid
        else:
            centroid = Point(gcoords[0])
        label = gname
        plt.text(
            *list(centroid.coords)[0], s=label,
            bbox={'facecolor': 'white', 'alpha': .7, 'linewidth': .5}
            )
        group_ctext.append([
            gname,
            group_labels_inout[gname]["out"],
            group_labels_inout[gname]["in"],
            group_labels_inout[gname]["sum"]
            ])
    group_ctext = list(sorted(group_ctext, key=lambda x: x[0]))
    group_ctext.append(['intersection', '', '', str(sum(nodeturns.values()))])

    plt.xticks([]), plt.yticks([])

    tb = plt.table(
            colLabels=RIBBON_DIAGRAMS_DF_COLS,
            cellColours=ccolors,
            cellText=ctext,
            loc='bottom'
    )
    tb_size = tb.properties()['children'][0].get_fontsize()

    tt = plt.table(colLabels=RIBBON_DIAGRAMS_GROUP_DF_COLS,
                   cellText=group_ctext, loc='top')
    tt.set_fontsize(tb_size)

    pad = tt.get_tightbbox().ymax / tt.get_tightbbox().ymin
    pad += pad * 0.03

    st = td(seconds=start)
    et = td(seconds=end)

    mode_text = '$\it{' + mode +  '}$'
    ax.set_title(
        f'Ribbon diagram for node {node_id}\nMode: {mode_text}\nTime period {st} - {et}',
        fontname='Franklin Gothic Medium',
        y=pad,
        va='bottom'
    )

    tables = {
        'turns': pd.DataFrame(data=ctext, columns=RIBBON_DIAGRAMS_DF_COLS),
        'groups': pd.DataFrame(data=group_ctext, columns=RIBBON_DIAGRAMS_GROUP_DF_COLS)
    }

    return fig, tables


def get_ribbon_diagram_by_links(
        net: gpd.GeoDataFrame,
        turns: Dict[float, Dict[str, int]],
        links: List[str],
        mode: str = 'car',
        start: int = 0,
        end: int = 86400
) -> Tuple[matplotlib.figure.Figure, Dict[str, pd.DataFrame]]:
    new_nodes_info, connectors, subnodes, subnet = (
        get_intersection_data_by_links(
            net=net, turns=turns, links=links, start=start, end=end, mode=mode
        )
    )
    rd, tables = get_intersection_plot_by_links(
        new_nodes_info=new_nodes_info, start=start, end=end, mode=mode
    )
    return rd, tables


def string_links_to_list(
        string_links: str
) -> List[str]:
    links = string_links.split()
    return links


def get_intersection_plot_by_links(
        new_nodes_info,
        start: int,
        end: int,
        mode: str
) -> matplotlib.figure.Figure:
    fig, ax = plt.subplots()

    colors = {}
    ctext = []
    ccolors = []
    group_labels_geoms = defaultdict(list)
    # group_labels_inout = defaultdict(lambda: {'in': 0, 'out': 0, 'sum': 0})
    
    all_geoms = []
    for node_id, node_info in new_nodes_info.items():
        unique_link_geoms = node_info['unique_link_geoms']
        all_geoms.extend(list(unique_link_geoms.values()))
    multigeom = MultiLineString(all_geoms)
    minradius = shapely.minimum_bounding_radius(multigeom)
    shrink_ratio = minradius / NORMAL_RD_CIRCLE_RADIUS

    for node_id, node_info in new_nodes_info.items():
        turns_geoms = node_info['turns_geoms']
        nodeturns = node_info['nodeturns']
        thicknesses = node_info['thicknesses']
        turns_groups = node_info['turns_groups']
        for turn, geom in turns_geoms.items():
            count = nodeturns[turn]
            coords = list(geom.coords)
            line, = ax.plot(
                *list(zip(*coords)),
                linewidth=thicknesses[turn] / shrink_ratio,
                solid_capstyle='butt',
                label=' -> '.join(turn)
            )
            colors[turn] = line.get_color()
            ccolors.append([
                matplotlib.colors.to_rgb(line.get_color()) + (0.9,)
                if col in ['from_link', 'to_link'] else (0, 0, 0, 0)
                for col in RIBBON_DIAGRAMS_DF_COLS
            ])
            fg = turns_groups[turn]['from_group']
            tg = turns_groups[turn]['to_group']

            group_labels_geoms[fg].append(list(turns_geoms[turn].coords)[0])
            group_labels_geoms[tg].append(list(turns_geoms[turn].coords)[-1])
            ctext.append(
                [turn[0], turn[1], fg, tg, count]
            )

    for gname, gcoords in group_labels_geoms.items():
        if len(gcoords) > 1:
            centroid = LineString([Point(gcoord) for gcoord in gcoords]).centroid
        else:
            centroid = Point(gcoords[0])
        label = gname
        fontsize = max(MIN_RD_TEXT_SIZE, NORMAL_RD_TEXT_SIZE / shrink_ratio)
        lineweight = 0.5 / shrink_ratio
        plt.text(
            *list(centroid.coords)[0], s=label, fontsize=fontsize,
            bbox={
                'facecolor': 'white', 'alpha': .7, 'linewidth': lineweight,
                'boxstyle': 'round,pad=0.2'
            }
        )

    plt.xticks([]), plt.yticks([])

    tb = plt.table(
            colLabels=RIBBON_DIAGRAMS_DF_COLS,
            cellColours=ccolors,
            cellText=ctext,
            loc='bottom'
            )

    st = td(seconds=start)
    et = td(seconds=end)
    mode_text = '$\it{' + mode +  '}$'
    plt.title(
        f'Ribbon diagram for node {node_id}\nMode: {mode_text}\nTime period {st} - {et}',
        fontname='Franklin Gothic Medium'
        )

    tables = {
        'turns': pd.DataFrame(data=ctext, columns=RIBBON_DIAGRAMS_DF_COLS),
        # 'groups': pd.DataFrame(data=group_ctext, columns=RIBBON_DIAGRAMS_GROUP_DF_COLS)
    }
    return fig, tables


def get_ribbon_diagram(
        net: gpd.GeoDataFrame,
        turns: Optional[Dict[float, Dict[str, int]]],
        node_id: str,
        mode: str = 'car',
        start: int = 0,
        end: int = 86400,
        db_path: Optional[Union[str, Path]] = None
) -> Tuple[matplotlib.figure.Figure, Dict[str, pd.DataFrame]]:
    nodeturns, turns_geoms, turns_groups, thicknesses = (
        get_intersection_data(
            net, turns, node_id, start=start, end=end, mode=mode
        ) if turns is not None and db_path is None else
        get_intersection_data_db(
            net, db_path, node_id, start=start, end=end, mode=mode
        )
    )
    rd, tables = get_intersection_plot(
        nodeturns, turns_geoms, thicknesses,
        turns_groups, node_id, start, end, mode
    )
    return rd, tables


def get_link_count_stats(
        counts: Dict[str, Dict[float, Dict[str, int]]],
        link_id: str
        ) -> Dict[str, List[float]]:
    """
    B.

    Parameters
    ----------
    counts : Dict[str, Dict[float, Dict[str, int]]]
        DESCRIPTION.
    link_id : str
        DESCRIPTION.

    Returns
    -------
    Dict[str, List[float]]
        DESCRIPTION.

    """
    link_stats = {m: [] for m in EVENTS_MODES}
    link_stats['timestep'] = []
    link_stats['link_id'] = link_id
    timestep_nrs = set()

    for mode in counts:
        if mode not in EVENTS_MODES:
            continue
        for nr, timestep in enumerate(counts[mode]):
            if nr not in timestep_nrs:
                link_stats['timestep'].append(timestep)
                timestep_nrs.add(nr)
            if link_id in counts[mode][timestep]:
                link_stats[mode].append(counts[mode][timestep][link_id])
            else:
                link_stats[mode].append(0)
    return link_stats


def reaggregate_counts(
        counts: Dict[str, Dict[float, Dict[str, int]]],
        aggregate_by: int = 900,
        start: int = 0,
        end: int = 86400
) -> Dict[str, Dict[float, Dict[str, int]]]:
    mode = list(counts.keys())[0]  # get one mode
    every = get_timestep_precision(counts[mode], timesteps_are_keys=True)
    old_timeline = list(counts[mode])
    first_val = old_timeline[0]
    last_val = old_timeline[-1] + every

    if aggregate_by == every and first_val == start and last_val == end:
        warnings.warn(
            'Aggregation is the same as data, returning the same object!'
        )
        return counts
    elif aggregate_by < every:
        raise RuntimeError(
            f'Requested aggregation value ({aggregate_by}) is smaller '
            f'than the aggregation of actual data ({every})'
        )
    elif aggregate_by % every != 0:
        raise RuntimeError(
            f'Requested aggregation value ({aggregate_by}) is not a suitable '
            f'divisor for the aggregation of actual data ({every}). '
            'There should be a modulo equal to 0'
        )
    elif start % every != 0:
        raise RuntimeError(
            f'Requested start time ({start}) is not a suitable '
            f'divisor for the aggregation of actual data ({every}). '
            'There should be a modulo equal to 0'
        )
    elif end % every != 0:
        raise RuntimeError(
            f'Requested end time ({end}) is not a suitable '
            f'divisor for the aggregation of actual data ({every}). '
            'There should be a modulo equal to 0'
        )

    new_timeline = get_timeline(
        start=start, stop=end, aggregate_by=aggregate_by, aggregate_unit='s'
    )
    new_to_old = {}
    for step in new_timeline:
        nstep = round_timestep(
            step + aggregate_by, aggregate_by=aggregate_by, aggregate_unit='s'
        )
        new_to_old[step] = [v for v in old_timeline if step <= v < nstep]

    new_counts = defaultdict(
        lambda: {v: defaultdict(int) for v in new_timeline}
    )

    for mode, mode_counts in counts.items():
        for ntimestep in new_timeline:
            old_timesteps = new_to_old[ntimestep]
            for timestep in old_timesteps:
                for link, value in mode_counts[timestep].items():
                    new_counts[mode][ntimestep][link] += value

    new_counts = defaultdict2dict(new_counts)
    return new_counts


def link_is_road(
        modes: List[str]
        ) -> bool:
    return any(el in ['car', 'truck'] for el in modes)


def merge_net_counts(
        net: gpd.GeoDataFrame,
        counts: Dict[str, Dict[float, Dict[str, int]]],
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
    fullcounts = {
        mode: defaultdict(int) for mode in EVENTS_MODES
    }

    for mode in counts:
        for timestep in counts[mode]:
            for link in counts[mode][timestep]:
                fullcounts[mode][link] += counts[mode][timestep][link]

    countsdf = pd.DataFrame(
        fullcounts, dtype='Int64').rename_axis('link_id').reset_index()
    net = net.merge(
        countsdf, on='link_id', how='inner' if drop_empty else 'left'
    )
    net.drop(
        net[~net['modes'].str.split(',').apply(link_is_road)].index,
        inplace=True
    )
    return net


def link_stats_to_df(
        link_stats: Dict[str, Union[List[float], str]]
) -> pd.DataFrame:
    """
    B.

    Parameters
    ----------
    link_stats : Dict[str, Union[List[float], str]]
        DESCRIPTION.

    Returns
    -------
    TYPE
        DESCRIPTION.

    """
    to_df = {k: link_stats[k] for k in LINK_STATS_DF_COLS
             if k in link_stats and link_stats[k]}
    df = pd.DataFrame(to_df)
    missing = set(LINK_STATS_DF_COLS).difference(set(df.columns))
    if missing:
        for col in missing:
            df[col] = 0
    df['total'] = df[list(EVENTS_MODES)].sum(axis=1).astype(int)
    df['timestep'] = pd.to_datetime(df['timestep'], unit='s')
    return df[list(LINK_STATS_DF_COLS)]


def get_decay_diagram(
        net: gpd.GeoDataFrame,
        plans_path: Union[str, Path],
        link_ids: List[str],
        modes: Sequence[str] = ('car', 'truck')
) -> gpd.GeoDataFrame:
    link_ids_decays = {
        mode: defaultdict(lambda: defaultdict(int)) for mode in modes
    }
    plans = matsim.plan_reader(plans_path, selected_plans_only=True)
    legs_count = 0
    for person, plan in plans:
        if 'selected' not in plan.attrib or plan.attrib['selected'] != 'yes':
            raise
        for el in plan:
            if el.tag == 'leg':
                legs_count += 1
                mode = el.attrib['mode']
                if mode not in modes:
                    continue
                route = el.findall('route')
                if not route:
                    continue
                route_links = route[0].text.strip()
                if not route_links:
                    continue
                route_links_list = route_links.split()
                commons = link_ids.intersection(route_links_list)
                if commons:
                    for link in route_links_list:
                        for common in commons:
                            link_ids_decays[mode][common][link] += 1
                if legs_count % 10000 == 0:
                    print('Agent:', person.attrib['id'])

    decay_gdfs = []
    for mode, link_data in link_ids_decays.items():
        for link, spread_counts in link_data.items():
            countsdf = pd.Series(
                spread_counts,
            ).to_frame().reset_index().rename(
                {'index': 'link_id', 0: mode}, axis=1
            )
            countsdf['profile'] = link
            decay_gdf = net.merge(
                countsdf, on='link_id', how='right'
            ).sort_values(mode)
            decay_gdf[f'{mode}_rel'] = decay_gdf[mode] / decay_gdf[mode].max()
            decay_gdfs.append(decay_gdf)
    total_decay_gdf = gpd.GeoDataFrame(pd.concat(decay_gdfs), crs=net.crs)
    return total_decay_gdf
