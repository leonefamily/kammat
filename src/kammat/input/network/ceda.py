# -*- coding: utf-8 -*-
"""
Created on Tue Aug 23 12:49:15 2022

@author: dgrishchuk
"""
from typing import Union, List, Tuple, Dict, Any, Optional, Set, Literal

import geopandas as gpd
import pandas as pd
import dbfread
from pathlib import Path
from collections import defaultdict, Counter
import networkx as nx
import momepy
import copy
import logging
import shapely
import itertools
from shapely.geometry import LineString, MultiPoint
from io import StringIO
import argparse
import sys
from copy import deepcopy
from itertools import chain
from math import atan2, degrees, dist
from kammat.defaults.constants import LOGGER_FORMAT
from kammat.output.utils import defaultdict2dict
from kammat.input.network.utils import hash_coordinate, hash_inout_edges

DIRS = {'FT': 3, 'TF': 2, 'N': 4}
PT_MODES = ['pt', 'tram', 'rail', 'bus']

logging.basicConfig(
    format=LOGGER_FORMAT,
    level=logging.INFO
)

LaneConnections = Dict[int, Dict[Union[str, int], List[Tuple[str, Union[int, str, None]]]]]
Edge = Tuple[Union[Tuple[float, float], int, Dict[str, Any]]]
Accessibility = Dict[str, Dict[Union[str, int], Dict[str, bool]]]


def read_dbf(
        p: Union[str, Path],
        encoding: str = 'windows-1250'
) -> pd.DataFrame:
    table = dbfread.DBF(p, encoding=encoding, load=True)
    return pd.DataFrame(table)


def read_and_filter_ceda(
        shp_path: Union[str, Path]
) -> gpd.GeoDataFrame:
    logging.info(f'Reading and processing {shp_path}')
    shp = gpd.read_file(shp_path).dropna(subset=['geometry'])

    if len(shp['ROAD_ID'].unique()) != len(shp):
        raise RuntimeError(
            'There are duplicated ROAD_ID values '
            'in the subset that can cause problems'
        )
    shp['METER'] = shp.length
    # 3 - oneway along, 2 - oneway opposite, 4 - no way, 1 - both
    shp['ONEWAY'] = shp['ONEWAY'].replace(DIRS)
    shp.loc[~shp['ONEWAY'].isin(DIRS.values()), 'ONEWAY'] = 1
    return shp.reset_index(drop=True)


def set_attributes_to_ceda(
        shp: gpd.GeoDataFrame
):
    if 'speed' not in shp.columns:
        shp['speed'] = 50
    if 'permlanes' not in shp.columns:
        shp['permlanes'] = 1
    if 'capacity' not in shp.columns:
        shp['capacity'] = None

    shp.loc[pd.isnull(shp['capacity']), 'capacity'] = (
        shp.loc[pd.isnull(shp['capacity'])].apply(
            lambda r: guess_capacity(r['speed'], r['permlanes'])
        )
    )

    # shp['capacity'] *= shp['permlanes']
    if 'modes' not in shp.columns:
        shp['modes'] = 'car,truck'
    else:
        shp.loc[shp['modes'].isna(), 'modes'] = 'car,truck'

    if 'nofacility' not in shp.columns:
        shp['nofacility'] = 0
        # where agents cannot spawn, BT - bridge 1, tunnel 4
        shp.loc[shp['BT'].isin([1, 4]), 'nofacility'] = 1
    shp['freespeed'] = (shp['speed'] / 3.6).round(2)
    return shp


def assign_links_nodes_ids(
        digraph: nx.MultiDiGraph,
        lanes: Optional[LaneConnections] = None,
        hash_nodes: bool = True
) -> LaneConnections:

    dilanes = defaultdict(lambda: defaultdict(list))

    for i, n in enumerate(digraph.nodes):
        if hash_nodes:
            digraph.nodes[n]['nodenum'] = hash_coordinate(n)
            digraph.nodes[n]['alt_nodenum'] = hash_inout_edges([
                str(e[-1]['ROAD_ID']) for e in
                list(digraph.out_edges(n, data=True)) +
                list(digraph.in_edges(n, data=True))
            ])
        else:
            digraph.nodes[n]['nodenum'] = i
        digraph.nodes[n]['previous'] = None
        digraph.nodes[n]['in'] = []
        digraph.nodes[n]['out'] = []

    for *e, attrs in digraph.edges(keys=True, data=True):
        u, v, k = e
        fn = digraph.nodes[u]['nodenum']
        tn = digraph.nodes[v]['nodenum']
        rid = attrs['ROAD_ID']
        lid = f'{fn}_{tn}_{rid}'
        try:
            afn = digraph.nodes[u]['alt_nodenum']
            atn = digraph.nodes[v]['alt_nodenum']
            alt_lid = f'{afn}_{atn}_{rid}'
        except KeyError:
            alt_lid = None

        if lanes is not None and rid in lanes:
            for lane, torids in lanes[rid].items():
                for torid, tolane in torids:
                    allowed = [tuple(e) for *e, attrs in
                               digraph.out_edges(v, keys=True, data=True)
                               if attrs['ROAD_ID'] == torid and attrs['modes']
                               not in PT_MODES
                               ]
                    for edgeid in allowed:
                        dilanes[lid][lane].append((edgeid, tolane))
                        # print(lid, lane, '->', edge_link[edgeid], tolane)

        if attrs['modes'] not in PT_MODES:
            digraph.nodes[u]['out'].append(lid)
            digraph.nodes[v]['in'].append(lid)
        digraph.edges[e]['link_id'] = lid
        digraph.edges[e]['node_start'] = fn
        digraph.edges[e]['node_end'] = tn
        digraph.edges[e]['custom'] = False  # !!!
        digraph.edges[e]['kind'] = None  # !!!
        if alt_lid is not None:
            digraph.edges[e]['alt_link_id'] = alt_lid

    edge_link = nx.get_edge_attributes(digraph, 'link_id')
    dilanes = defaultdict2dict(dilanes)
    for fromlink, fromlanes in dilanes.items():
        for fromlane, todatas in fromlanes.items():
            newtodatas = []
            for todata in todatas:
                newtodatas.append((edge_link[todata[0]], todata[1]))
            dilanes[fromlink][fromlane] = newtodatas
    return dilanes


def get_lane_connections(
        shp: gpd.GeoDataFrame,
        lcon_dbf: pd.DataFrame
) -> LaneConnections:
    lanecon = shp.merge(lcon_dbf, on='ROAD_ID')
    lanes = defaultdict(lambda: defaultdict(list))
    for connid, gdf in lanecon.sort_values('SEQNR').groupby('LCON_ID'):
        found = len(gdf)
        if found < 2:
            continue
        elif found > 2:
            raise RuntimeError(f'Connection ID {connid} has {found} parts')
        fromlaneid, tolaneid = gdf['LANE'].tolist()
        fromid, toid = gdf['ROAD_ID'].tolist()
        # if toid, tolaneid not in lanes[fromid][fromlaneid]:
        lanes[fromid][fromlaneid].append((toid, tolaneid))
    lanes = dict(lanes)
    for fromid in lanes:
        lanes[fromid] = {k: lanes[fromid][k] for k in sorted(lanes[fromid].keys())}
    return lanes


def reverse_geom(
        geom: List[Tuple[float, float]]
) -> LineString:
    def _reverse(x, y, z=None):
        if z:
            return x[::-1], y[::-1], z[::-1]
        return x[::-1], y[::-1]

    return shapely.ops.transform(_reverse, geom)


def guess_capacity(
        speed: Union[int, float],
        permlanes: int = 1
) -> int:
    if speed <= 5:
        return 100 * permlanes
    else:
        return int(min(17.5 * speed + 60, 1800)) * permlanes


def find_successors(
        digraph: nx.MultiDiGraph,
        e: Tuple[float, float, int],
        tolinks: List[int]
        ) -> List[str]:
    u, v, k = e
    return [data['link_id'] for *ne, data in
            digraph.out_edges(v, keys=True, data=True)
            if data['ROAD_ID'] in tolinks]


def _ws(
        num: int
) -> str:
    """Get ``num`` whitespaces multiplied by 4"""
    return ' ' * num * 4


def get_lane_definitions(
        newdilanes: LaneConnections,
        newdigraph: gpd.GeoDataFrame,
        common_lane: bool = True
) -> str:
    edge_link = nx.get_edge_attributes(newdigraph, 'link_id')
    link_edge = {v: k for k, v in edge_link.items()}

    ld = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    ld += (
        '<laneDefinitions xsi:schemaLocation='
        '"http://www.matsim.org/files/dtd '
        'http://www.matsim.org/files/dtd/laneDefinitions_v2.0.xsd" '
        'xmlns="http://www.matsim.org/files/dtd" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
        )

    for fromlink, tolinkdict in newdilanes.items():

        e = link_edge[fromlink]
        # newdigraph.edges[e]['permlanes'] = len(tolinkdict)  # TODO: does it make sense?
        ldata = newdigraph.edges[e]
        ld += f'{_ws(1)}<lanesToLinkAssignment linkIdRef="{fromlink}">\n'

        tolinks_all = list(
            chain.from_iterable(
                [data[0] for data in datas] for datas in tolinkdict.values()
                )
            )
        tolinks_unique = list(set(tolinks_all))

        if common_lane:
            tolinkdict = {'cl1': [(tol, None) for tol in tolinks_unique]}
            represented_lanes = {'cl1': ldata["permlanes"]}
            base_capacity = ldata["capacity"] / ldata["permlanes"]
        else:
            len_unique = len(tolinks_unique)
            len_all = len(tolinks_all)
            if len_unique != len_all:
                base_capacity = ldata["capacity"] / len_all
                tolinkdict = {}
                represented_lanes = {}
                multipliers = Counter(tolinks_all)
                for j in range(1, len_unique + 1):
                    target_link = tolinks_unique[j - 1]
                    tolinkdict[j] = [(target_link, None)]
                    represented_lanes[j] = multipliers[target_link]
            else:
                base_capacity = ldata["capacity"] / len(tolinkdict)
                represented_lanes = {
                    lane: 1 for lane in tolinkdict
                    }

        for alignment, (fromlane, todata) in enumerate(tolinkdict.items()):
            if not todata:
                raise ValueError(f'Link {fromlink} has empty destinations')
            rl = represented_lanes[fromlane]
            lane_capacity = round(base_capacity * rl)
            fromlaneref = f'{fromlink}.{fromlane}'
            ld += f'{_ws(2)}<lane id="{fromlaneref}">\n'
            ld += f'{_ws(3)}<leadsTo>\n'
            for tolink, tolane in todata:
                ld += f'{_ws(4)}<toLink refId="{tolink}"/>\n'
            ld += f'{_ws(3)}</leadsTo>\n'
            ld += f'{_ws(3)}<representedLanes number="{rl}"/>\n'
            ld += f'{_ws(3)}<capacity vehiclesPerHour="{lane_capacity}"/>\n'
            ld += f'{_ws(3)}<startsAt meterFromLinkEnd="{ldata["METER"]}"/>\n'
            ld += f'{_ws(3)}<alignment>{alignment}</alignment>\n'
            ld += f'{_ws(2)}</lane>\n'
        ld += f'{_ws(1)}</lanesToLinkAssignment>\n'
    ld += '</laneDefinitions>'
    return ld


def explore_chain(
        in_link: str,
        in_lane: str,
        out_links: List[str],
        marked_links: List[str],
        newdilanes: LaneConnections,
        visited: Set[str],
        accessible: Dict[str, bool]
        ):
    if in_link not in newdilanes:
        return
    for fromlane, tolinkslanes in newdilanes[in_link].items():
        if fromlane != in_lane:
            continue
        for tolink, tolane in tolinkslanes:
            if (tolink, tolane) in visited or tolink not in marked_links + out_links:
                continue
            visited.add((tolink, tolane))
            if tolink in newdilanes and tolane in newdilanes[tolink]:
                accessible[tolink] = True
                explore_chain(
                    tolink, tolane, out_links, marked_links, newdilanes, visited, accessible
                    )
            elif tolink in out_links:
                accessible[tolink] = True


def get_links_accessibility(
        in_link: str,
        out_links: List[str],
        marked_links: List[str],
        newdilanes: LaneConnections
        ) -> Optional[Dict[str, bool]]:

    if in_link in newdilanes:
        accessible = {}
        for in_lane in newdilanes[in_link]:
            lane_accessible = {out_link: False for out_link in out_links}
            visited = set()
            visited.add((in_link, in_lane))
            explore_chain(
                in_link, in_lane, out_links, marked_links, newdilanes, visited, lane_accessible
                )
            lane_accessible = {
                out: a for out, a in lane_accessible.items() if out in out_links
                }
            if all(not a for a in lane_accessible.values()):
                raise RuntimeError(
                    f'Link {in_link} on lane {in_lane} has no candidate links '
                    'according to provided lane connections, '
                    'but is a part of some node according to shapefile'
                    )
            accessible[in_lane] = lane_accessible
        return accessible
    raise KeyError(f'{in_link} has no lane definition')


def replace_edges(
        pack: List[Edge],
        kind: Literal['in', 'out'],
        nodecoords: Tuple[float, float],
        nodenum: int,
        newdigraph: nx.MultiDiGraph
        ):
    for *edge, key, data in pack:
        newdata = deepcopy(data)
        newdata[f'node_{"end" if kind == "in" else "start"}'] = nodenum
        newgeom = list(newdata['geometry'].coords)
        # checking which of vertices /end, start/
        # is closer to the new node to replace it
        geom_node_pos = (
            0 if dist(newgeom[0], nodecoords) < dist(newgeom[-1], nodecoords) else -1
            )
        # nodes are simpler, it is ensured by graph they have correct geometry
        node_pos = -1 if kind == 'in' else 0

        newdigraph.remove_edge(*edge)
        edge[node_pos] = nodecoords
        newgeom[geom_node_pos] = nodecoords
        newdata['geometry'] = LineString(newgeom)
        newdigraph.add_edge(*edge, **newdata)


def simplify_intersections(
        newdilanes: LaneConnections,
        newdigraph: nx.MultiDiGraph,
        hash_nodes: bool = True
):
    intersection_ids = {
        data['node'] for *e, data in newdigraph.edges(data=True)
        if not pd.isnull(data['node']) and data['node'] != 0
        }
    if not hash_nodes:
        next_nodenum = max(
            data['nodenum'] for n, data in newdigraph.nodes(data=True)
        ) + 1
    else:
        next_nodenum = None

    for iid in intersection_ids:
        marked_edges = [
            e for e in newdigraph.edges(data=True, keys=True)
            if e[-1]['node'] == iid
            ]
        marked_nodes = list(
            set(chain.from_iterable(e[:2] for e in marked_edges))
            )
        marked_links = [e[-1]['link_id'] for e in marked_edges]

        in_edges = list(filter(
            lambda e: e not in marked_edges,
            chain.from_iterable(
                newdigraph.in_edges(n, data=True, keys=True)
                for n in marked_nodes
                )
            ))
        in_links = [e[-1]['link_id'] for e in in_edges]
        out_edges = list(filter(
            lambda e: e not in marked_edges,
            chain.from_iterable(
                newdigraph.out_edges(n, data=True, keys=True)
                for n in marked_nodes
                )
            ))
        out_links = [e[-1]['link_id'] for e in out_edges]

        try:
            out_accessibility = {}
            for in_link in in_links:
                try:
                    accessibility = get_links_accessibility(
                        in_link, out_links, marked_links, newdilanes
                        )
                except KeyError as e:
                    continue
                out_accessibility[in_link] = accessibility
            intersection_center = list(
                MultiPoint(marked_nodes).convex_hull.centroid.coords
            )[0]
            if hash_nodes:
                next_nodenum = hash_coordinate(intersection_center)
                next_alt_nodenum = hash_inout_edges(
                    [e[-1]['ROAD_ID'] for e in in_edges] +
                    [e[-1]['ROAD_ID'] for e in out_edges]
                )
            else:
                next_alt_nodenum = None
            center_attributes = {
                'nodenum': next_nodenum,
                'previous': None,
                'in': in_links,
                'out': out_links
            }
            if next_alt_nodenum is not None:
                center_attributes['alt_nodenum'] = next_alt_nodenum
            if newdilanes:
                simplify_lane_definitions(newdilanes, marked_links, out_accessibility)
            newdigraph.add_node(intersection_center, **center_attributes)
            replace_edges(out_edges, 'out', intersection_center, next_nodenum, newdigraph)
            replace_edges(in_edges, 'in', intersection_center, next_nodenum, newdigraph)
            for *marked_edge, key, data in marked_edges:
                newdigraph.remove_edge(*marked_edge)
            if not hash_nodes:
                next_nodenum += 1
        except RuntimeError as e:
            print(f'Node {int(iid)}:', e)


def simplify_lane_definitions(
        newdilanes: LaneConnections,
        marked_links: List[str],
        out_accessibility: Accessibility
        ):

    for ml in marked_links:
        if ml in newdilanes:
            del newdilanes[ml]

    for fromlink, accesses in out_accessibility.items():
        simple_ldefs = {lane: [] for lane in accesses}
        for lane, access in accesses.items():
            for tolink, valid in access.items():
                if valid:
                    simple_ldefs[lane].append((tolink, None))
        newdilanes[fromlink] = simple_ldefs


def write_lane_definitions(
        ld: str,
        outpath: Union[str, Path]
):
    with open(outpath, mode='w', encoding='utf-8') as f:
        f.write(ld)


def delete_islands_undir(
        graph: nx.MultiGraph
):
    logging.info('Deleting islands')
    islands = list(nx.connected_components(graph))
    if len(islands) > 1:
        conns_num = {}
        for i, isle in enumerate(islands):
            conns_num[i] = len(isle)
        max_key = max(conns_num, key=conns_num.get)
        g = graph
        components = [g.subgraph(c).copy() for c in nx.connected_components(g)]
        logging.info(f"There are {len(components)} islands")
        for i, g in enumerate(components):
            if i != max_key:
                graph.remove_nodes_from(g.nodes())
                graph.remove_edges_from(g.edges())


def delete_dead_ends_toend(
        graph: nx.MultiDiGraph
):
    logging.info('Deleting dead ends with zero out-degree')
    while True:
        doubtful = [n for n in graph.nodes() if graph.out_degree(n) == 0]
        del_loop = set()
        for node in doubtful:
            for from_node, to_node, edge_num, data in (
                    tuple(graph.in_edges(node, keys=True, data=True))):
                if data['ONEWAY'] in [2, 3]:
                    del_loop.add((from_node, to_node))
        if not del_loop:
            break
        graph.remove_edges_from(del_loop)


def delete_dead_ends_fromend(
        graph: nx.MultiDiGraph
):
    logging.info('Deleting dead ends with zero in-degree')
    while True:
        doubtful = [n for n in graph.nodes() if graph.in_degree(n) == 0]
        del_loop = set()
        for node in doubtful:
            for from_node, to_node, edge_num, data in (
                    tuple(graph.out_edges(node, keys=True, data=True))):
                if data['ONEWAY'] in [2, 3]:
                    del_loop.add((from_node, to_node))
        if not del_loop:
            break
        graph.remove_edges_from(del_loop)


def delete_islands_dir(
        graph: nx.MultiDiGraph
):
    logging.info('Deleting islands')
    islands = list(nx.strongly_connected_components(graph))
    if len(islands) > 1:
        conns_num = {}

        for i, isle in enumerate(islands):
            conns_num[i] = len(isle)
        max_key = max(conns_num, key=conns_num.get)

        g = graph
        components = [g.subgraph(c).copy()
                      for c in nx.strongly_connected_components(g)]
        logging.info(f"There are {len(components)} islands")
        for i, g in enumerate(components):
            if i != max_key:
                graph.remove_nodes_from(g.nodes())
                graph.remove_edges_from(g.edges())


def make_graph_directed(
        graph: nx.MultiGraph,
) -> nx.MultiDiGraph:
    logging.info('Adding opposite directions for both-directional roads')
    digraph = nx.MultiDiGraph(graph)
    flipped = set()
    for n, edge in enumerate(digraph.edges):
        from_node, to_node, edge_num = edge
        attrs = digraph.edges[edge]
        if attrs['ONEWAY'] != 1:
            flip = not (from_node == list(attrs['geometry'].coords)[0] and
                        to_node == list(attrs['geometry'].coords)[-1])
            if not flip:
                try:
                    digraph.remove_edge(to_node, from_node, edge_num)
                except nx.NetworkXError:
                    pass
        if attrs['ONEWAY'] == 1 and (to_node, from_node) not in flipped:
            geom = list(attrs['geometry'].coords)
            geom.reverse()
            attrs['geometry'] = shapely.geometry.LineString(geom)
            nx.set_edge_attributes(digraph,
                                   {(from_node, to_node, edge_num): attrs})
            flipped.add((from_node, to_node))
    return digraph


def ensure_digraph_connectivity(
        digraph: nx.MultiDiGraph
):
    delete_dead_ends_toend(digraph)
    delete_dead_ends_fromend(digraph)
    delete_islands_dir(digraph)


def create_conn_graph(
        shp: gpd.GeoDataFrame
) -> nx.MultiDiGraph:
    logging.info('Creating connected graph')
    try:
        graph = momepy.gdf_to_nx(shp, approach="primal")
    except NotImplementedError:
        logging.warning('Had to explode geometry, vertical size increazed...')
        graph = momepy.gdf_to_nx(shp.explode(index_parts=True), approach="primal")
    delete_islands_undir(graph)
    digraph = make_graph_directed(graph)
    ensure_digraph_connectivity(digraph)
    return digraph


def generate_attrs_string(
        attrs: Dict[str, Any],
        towrite: List[str] = None
) -> str:
    if towrite is None:
        return ''
    s = '      <attributes>\n'
    fails = 0
    for c in towrite:
        if c not in attrs:
            fails += 1
            continue
        val = attrs[c]
        if c == 'geometry':
            val = val.wkt
        if not pd.isnull(val):
            s += f'        <attribute name="{c}" class="java.lang.String">{val}</attribute>\n'
        else:
            fails += 1
    if fails == len(towrite):
        return ''
    return s + '      </attributes>\n'


def write_network(
        graph: nx.MultiDiGraph,
        outf: str
) -> nx.MultiDiGraph:
    logging.info(f'Writing network {outf}')
    bigstring = StringIO()
    bigstring.write('<?xml version="1.0" encoding="utf-8"?>\n')
    bigstring.write(
        '<!DOCTYPE network SYSTEM '
        '"http://matsim.org/files/dtd/network_v2.dtd">\n')
    bigstring.write('<network name="net">\n')

    bigstring.write('<nodes>\n')
    for (x, y), node in graph.nodes(data=True):
        num = node['nodenum']
        bigstring.write(f'    <node id="{num}" x="{x}" y="{y}">\n')
        if 'alt_nodenum' in node:
            node_attr_str = generate_attrs_string(node, ['alt_nodenum'])
            bigstring.write(node_attr_str)
        bigstring.write(f'    </node>\n')
    bigstring.write('</nodes>\n')

    bigstring.write('<links>\n')
    for j, edge in enumerate(graph.edges):
        from_node, to_node, edge_num = edge
        attrs = graph.edges[edge]
        fr = graph.nodes[from_node]['nodenum']
        to = graph.nodes[to_node]['nodenum']

        geoms = list(attrs['geometry'].coords)
        if from_node != geoms[0] and to_node != geoms[-1]:
            attrs['geometry'] = LineString(geoms[::-1])

        if 'link_id' in attrs:
            bigstring.write(generate_link_string(fr, to, attrs))
        else:
            bigstring.write(generate_link_string(fr, to, attrs, j))

    bigstring.write('</links>\n')
    bigstring.write('</network>\n')

    with open(outf, mode='w', encoding='utf-8') as wr:
        wr.write(bigstring.getvalue())
    return graph


def generate_link_string(
        fr: Union[str, int],
        to: Union[str, int],
        attrs: Dict[str, Any],
        add_attrs: Tuple[str] = ('nofacility', 'geometry', 'alt_link_id')
):
    l_len = attrs["METER"]
    l_id = attrs["link_id"]
    attrstr = generate_attrs_string(attrs, add_attrs)
    return (f'    <link id="{l_id}" from="{fr}" to="{to}" length="{l_len}" '
            f'capacity="{int(attrs["capacity"])}" '
            f'freespeed="{attrs["freespeed"]}" '
            f'modes="{attrs["modes"]}" permlanes="{attrs["permlanes"]}" >\n'
            f'{attrstr}'
            '    </link>\n')


def extract_nodeset_from_dilanes(
        inlink: str,
        dilanes: LaneConnections
        ) -> Set[Tuple[float, float]]:
    nodeset = set()
    for fromlane, tolinks in dilanes[inlink].items():
        for tolink in tolinks:
            pass


def get_restricted_moves(
        digraph: nx.MultiDiGraph,
        dilanes: LaneConnections
) -> Tuple[List[Tuple[str]], List[Tuple[float]], Dict[int, List[Dict[str, Tuple[float]]]]]:
    edge_link = nx.get_edge_attributes(digraph, 'link_id')
    link_edge = {v: k for k, v in edge_link.items()}

    node_nodenums = nx.get_node_attributes(digraph, 'nodenum')
    nodenums_node = {v: k for k, v in node_nodenums.items()}

    inlinks = {
        node_nodenums[n]: ins for n, ins in nx.get_node_attributes(digraph, 'in').items()
        }
    outlinks = {
        node_nodenums[n]: outs for n, outs in nx.get_node_attributes(digraph, 'out').items()
        }

    nodes_dilanes = {}
    for nodenum in nodenums_node:
        inls = inlinks[nodenum]
        nodeset = {}
        for inl in inls:

            if inl in dilanes:
                nodeset[inl] = set(
                    list(zip(*list(chain.from_iterable(dilanes[inl].values()))))[0]
                    )
        if nodeset:
            nodes_dilanes[nodenum] = nodeset

    intersections = defaultdict(list)

    for nodenum, node in nodenums_node.items():
        if nodenum in nodes_dilanes:
            ninedges = inlinks[nodenum]
            node_dilanes = nodes_dilanes[nodenum]
            for ninedge, tolinks in node_dilanes.items():
                allowed = [(ninedge, oe) for oe in tolinks]
                restricted = [(ninedge, oe) for oe in outlinks[nodenum] if oe not in tolinks]
                intersection = {
                    'allowed': allowed,
                    'restricted': restricted
                    }
                intersections[nodenum].append(intersection)

    restrictions_ids = []
    restrictions_nds = []
    for nodenum, inoutlinks in intersections.items():
        node = nodenums_node[nodenum]
        for restr in inoutlinks:
            restrictions_ids.extend(restr['restricted'])
            restrictions_nds.extend(
                [tuple(link_edge[e] for e in turn) for turn in restr['restricted']]
                )
    return restrictions_ids, restrictions_nds, intersections


def clean_previous_nodes(
        digraph: nx.MultiDiGraph
):
    for i, n in enumerate(digraph.nodes):
        digraph.nodes[n]['previous'] = None


def correct_lane_definitions(
        dilanes: LaneConnections,
        digraph: nx.MultiDiGraph
        ) -> LaneConnections:
    newdilanes = defaultdict(lambda: defaultdict(list))

    edge_link = nx.get_edge_attributes(digraph, 'link_id')
    link_edge = {v: k for k, v in edge_link.items()}

    for fromlink, lanedict in dilanes.items():
        # check if link still exists in graph
        if fromlink in link_edge:
            fe = link_edge[fromlink]
            # fu, fv, fk = fe
            for lane, toids in lanedict.items():
                for toid, tolane in toids:
                    if toid in link_edge:
                        tes = link_edge[toid]
                        newdilanes[fromlink][lane].append((toid, tolane))
                        
    newdilanes = defaultdict2dict(newdilanes)
    return newdilanes


def azimuth(x1, y1, x2, y2, rads=False):
    angle = atan2(y2 - y1, x2 - x1)
    if rads:
        return angle
    return degrees(angle)


def copy_lanes(
        inedge: Tuple[float, float, int, Dict[str, Any]],
        outedge: Tuple[float, float, int, Dict[str, Any]],
        add_dilanes: LaneConnections,
        digraph: nx.MultiDiGraph,
        kind: str = 'uturn'
):  # !!! remove digraph?
    attr_name = f'no{kind}'
    attr_name_alt = f'no_{kind}'
    should_copy = (
        True if attr_name not in digraph.edges[inedge[:3]] else
        (not bool(digraph.edges[outedge[:3]][attr_name]) or
         not bool(digraph.edges[outedge[:3]][attr_name_alt]))
        )

    if should_copy:

        digraph.edges[inedge[:3]]['custom'] = True
        digraph.edges[outedge[:3]]['custom'] = True
        digraph.edges[inedge[:3]]['kind'] = kind

        for lanenum in range(int(inedge[3]['permlanes'])):
            lanename = kind + str(lanenum + 1)
            add_dilanes[inedge[3]['link_id']][lanename].append(
                (outedge[3]['link_id'], lanename)
                )


def get_fws(
        ie: Tuple[float, float, int, Dict[str, Any]],
        oe: Tuple[float, float, int, Dict[str, Any]],
        other_ie: Tuple[float, float, int, Dict[str, Any]],
        other_oe: Tuple[float, float, int, Dict[str, Any]]
):
    return ie[3]['FW'], oe[3]['FW'], other_ie[3]['FW'], other_oe[3]['FW']


def get_azimuths(
        ie: Tuple[float, float, int, Dict[str, Any]],
        oe: Tuple[float, float, int, Dict[str, Any]],
        other_ie: Tuple[float, float, int, Dict[str, Any]],
        other_oe: Tuple[float, float, int, Dict[str, Any]]
) -> Tuple[float]:
    ie_startcoord = ie[3]['geometry'].coords[0]
    ie_endcoord = ie[3]['geometry'].coords[1]
    oe_startcoord = oe[3]['geometry'].coords[-2]
    oe_endcoord = oe[3]['geometry'].coords[-1]

    oie_startcoord = other_ie[3]['geometry'].coords[0]
    oie_endcoord = other_ie[3]['geometry'].coords[1]
    ooe_startcoord = other_oe[3]['geometry'].coords[-2]
    ooe_endcoord = other_oe[3]['geometry'].coords[-1]

    iaz = azimuth(ie_startcoord[0], ie_startcoord[1],
                  ie_endcoord[0], ie_endcoord[1], rads=True)
    oaz = azimuth(oe_startcoord[0], oe_startcoord[1],
                  oe_endcoord[0], oe_endcoord[1], rads=True)
    other_iaz = azimuth(oie_startcoord[0], oie_startcoord[1],
                        oie_endcoord[0], oie_endcoord[1], rads=True)
    other_oaz = azimuth(ooe_startcoord[0], ooe_startcoord[1],
                        ooe_endcoord[0], ooe_endcoord[1], rads=True)
    return iaz, oaz, other_iaz, other_oaz


def get_azimuths_difference(
        ie: Tuple[float, float, int, Dict[str, Any]],
        other_oe: Tuple[float, float, int, Dict[str, Any]]
):
    ie_startcoord = ie[3]['geometry'].coords[-2]
    ie_endcoord = ie[3]['geometry'].coords[-1]

    # this is intentionally reversed
    ooe_startcoord = other_oe[3]['geometry'].coords[-1]
    ooe_endcoord = other_oe[3]['geometry'].coords[-2]

    iaz = azimuth(ie_startcoord[0], ie_startcoord[1],
                  ie_endcoord[0], ie_endcoord[1], rads=True)
    other_oaz = azimuth(ooe_startcoord[0], ooe_startcoord[1],
                        ooe_endcoord[0], ooe_endcoord[1], rads=True)
    return degrees(iaz - other_oaz)


def add_uturn_restrictions(
        digraph: nx.MultiDiGraph,
        dilanes: LaneConnections
) -> LaneConnections:
    add_dilanes = defaultdict(lambda: defaultdict(list))
    for n in digraph.nodes:
        oes = list(digraph.out_edges(n, keys=True, data=True))  # outedges
        ies = list(digraph.in_edges(n, keys=True, data=True))  # inedges
        out_road_ids = {oe[3]['ROAD_ID'] for oe in oes}
        in_road_ids = {ie[3]['ROAD_ID'] for ie in ies}

        # we are interested in roads that are bidirectional and are not dead ends
        if len(oes) == 2 and len(ies) == 2:
            common = in_road_ids.intersection(out_road_ids)
            if common == out_road_ids:
                for ie in ies:
                    if ie[3]['link_id'] in dilanes:
                        continue
                    oe = [oe for oe in oes if oe[3]['ROAD_ID'] != ie[3]['ROAD_ID']][0]
                    copy_lanes(ie, oe, add_dilanes, digraph, 'uturn')
            elif len(common) == 1:
                common_id = list(common)[0]

                ie = [ie for ie in ies if ie[3]['ROAD_ID'] != common_id][0]
                other_ie = [oie for oie in ies if oie[3]['ROAD_ID'] == common_id][0]
                oe = [oe for oe in oes if oe[3]['ROAD_ID'] == common_id][0]
                other_oe = [ooe for ooe in oes if ooe[3]['ROAD_ID'] != common_id][0]

                potfork = ', '.join(
                    f"'{el[3]['link_id']}'" for el in [ie, other_ie, oe, other_oe]
                )
                if any(el[3]['no_fork'] == 1 for el in [ie, other_ie, oe, other_oe]):
                    logging.info(
                        f'Skipped potential forks makred as no_fork: {potfork}'
                        )
                    continue
                fws = get_fws(ie, oe, other_ie, other_oe)

                if any(fw in [4, 6, 7, 12, 13] for fw in fws) or set(fws) == {3}:
                    continue

                iaz, oaz, other_iaz, other_oaz = get_azimuths(ie, oe, other_ie, other_oe)
                diff = ((degrees(other_oaz) + 360) % 360) - ((degrees(iaz) + 360) % 360)

                passed = False
                if not ie[3]['link_id'] in dilanes:
                    if direct_condition(diff):
                        copy_lanes(ie, oe, add_dilanes, digraph, 'fork')
                        passed = True
                if not other_ie[3]['link_id'] in dilanes:
                    copy_lanes(other_ie, other_oe, add_dilanes, digraph, 'fork')
                    passed = True
                # if passed:
                #     logging.info(f"Added potential forks: {potfork}")
        if len(oes) == 1 and len(ies) == 1 and len(in_road_ids.intersection(out_road_ids)) == 1:
            continue
        for ie in ies:
            if ie[3]['link_id'] in dilanes:
                continue
            opp_oes = [oe for oe in oes if oe[3]['ROAD_ID'] == ie[3]['ROAD_ID']]
            pot_oes = [oe for oe in oes if oe[3]['ROAD_ID'] != ie[3]['ROAD_ID']]
            if opp_oes:  # only if there are opposite links
                for pot_oe in pot_oes:
                    copy_lanes(ie, pot_oe, add_dilanes, digraph, 'iuturn')

    add_dilanes = dict(add_dilanes)
    for fromid in add_dilanes:
        add_dilanes[fromid] = dict(add_dilanes[fromid])
    return add_dilanes


def direct_condition(
        diff: float
) -> bool:
    return diff < -60 or diff > 60


def map_opposite_edges(
        digraph: nx.MultiDiGraph
        ):
    found = {}
    seen = set()
    nx.set_edge_attributes(digraph, None, 'opposite')

    for *e, attrs in digraph.edges(data=True, keys=True):
        rid = attrs['ROAD_ID']
        if rid in seen:
            attrs['opposite'] = tuple(found[rid])
            nx.set_edge_attributes(digraph, {found[rid]: {'opposite': tuple(e)}})
        seen.add(rid)
        found[rid] = tuple(e)


def transform_unsupported_types(
        digraph: nx.MultiDiGraph
        ):
    nx.set_node_attributes(
        digraph,
        {k: str(v) for k, v in nx.get_node_attributes(digraph, 'out').items()},
        'out'
    )
    nx.set_node_attributes(
        digraph,
        {k: str(v) for k, v in nx.get_node_attributes(digraph, 'in').items()},
        'in'
    )
    nx.set_edge_attributes(
        digraph,
        {k: None for k, v in nx.get_edge_attributes(digraph, 'opposite').items()},
        'opposite'
    )


def check_restrictions_integrity(
        digraph: nx.MultiDiGraph,
        restrictions_nds
    ):
    """
    Check all turn restrictions and drop edges that are not accessible.

    This happens by converting a directed street network graph into a
    line graph that represents existing edges as nodes and connections
    between them (turns) as edges. Knowing the restrictions, forbidden
    turns are removed from the line graph, so the nodes (former edges),
    that are not accessible from at least one direction are dropped as well.
    A refined copy of initial graph is returned afterwards.

    Parameters
    ----------
    digraph : nx.MultiDiGraph
        DESCRIPTION.
    restrictions_nds : TYPE
        DESCRIPTION.

    Returns
    -------
    newdigraph : TYPE
        DESCRIPTION.

    """
    linegraph = nx.line_graph(digraph)
    remove_turns = []
    rnds = set(restrictions_nds)

    for e_ekey in linegraph.edges(keys=True):
        e = e_ekey[:2]
        if e in rnds:
            remove_turns.append(e_ekey)
        else:
            # only for linegraph
            origeattrs1 = digraph.edges[e[0][0], e[0][1], e[0][2]]
            try:
                opposattrs1 = digraph.edges[e[0][1], e[0][0], e[0][2]]
            except:
                opposattrs1 = {'link_id': 'None'}
            orige1 = origeattrs1['geometry']
            origeattrs2 = digraph.edges[e[1][0], e[1][1], e[1][2]]
            try:
                opposattrs2 = digraph.edges[e[1][1], e[1][0], e[0][2]]
            except:
                opposattrs2 = {'link_id': 'None'}
            orige2 = origeattrs2['geometry']
            nodegeom1 = orige1.interpolate(orige1.length / 2)
            nodegeom2 = orige2.interpolate(orige2.length / 2)
            nx.set_edge_attributes(
                linegraph, {
                    e_ekey: {
                        'geometry': LineString([nodegeom1, nodegeom2]),
                        'edgename': str(e_ekey),
                        'link_id1': origeattrs1['link_id'],
                        'link_id2': origeattrs2['link_id'],
                    }
                }
            )
            nodeattrs1 = linegraph.nodes[e[0]]
            nodeattrs2 = linegraph.nodes[e[1]]
            if 'geometry' not in nodeattrs1:
                nodeattrs1['link_id'] = origeattrs1['link_id']
                nodeattrs1['link_id_opp'] = opposattrs1['link_id']
                nodeattrs1['geometry'] = nodegeom1
            if 'geometry' not in nodeattrs2:
                nodeattrs2['geometry'] = nodegeom2
                nodeattrs2['link_id'] = origeattrs2['link_id']
                nodeattrs2['link_id_opp'] = opposattrs2['link_id']

    for rfrom, rto, rkey in remove_turns:
        linegraph.remove_edge(rfrom, rto, key=rkey)

    cmps = list(nx.strongly_connected_components(linegraph))
    max_cmp_idx = cmps.index(max(cmps, key=len))
    linegraph = linegraph.subgraph(cmps.pop(max_cmp_idx))
    linegraph = type(linegraph)(linegraph)

    newdigraph = digraph.copy()
    for e_ekey in itertools.chain.from_iterable(cmps):
        newdigraph.remove_edge(*e_ekey)

    new_linegraph = linegraph.copy()
    linenodes_mapping = {}
    for n, ndata in new_linegraph.nodes(data=True):
        ipt = ndata['geometry']
        linenodes_mapping[n] = ipt.x, ipt.y
    turnsgraph = nx.relabel_nodes(new_linegraph, linenodes_mapping)
    return newdigraph, turnsgraph


def prepare_ceda_network(
        shp_path: Union[str, Path],
        net_save_path: Union[str, Path],
        edges_save_path: Union[str, Path],
        nodes_save_path: Union[str, Path],
        lane_connections_path: Union[str, Path] = None,
        lane_definitions_save_path: Union[str, Path] = None,
        ncores: int = 1,
        internal_maneuvers: bool = True,
        common_lane: bool = True
):
    shp = read_and_filter_ceda(shp_path)
    lanes_dbf = None if lane_connections_path is None else read_dbf(lane_connections_path)
    shp = set_attributes_to_ceda(shp)

    shp = shp[(shp['capacity'] != 0) & (shp['speed'] != 0)]

    if lanes_dbf is not None:
        lanes = get_lane_connections(shp, lanes_dbf)
    else:
        lanes = None

    digraph = create_conn_graph(shp)
    dilanes = assign_links_nodes_ids(digraph, lanes)

    if lanes_dbf is not None:
        ptedges = [
            e[:3] for e in digraph.edges(data=True, keys=True)
            if e[-1]['modes'] in PT_MODES
        ]
        ptgraph = copy.deepcopy(nx.edge_subgraph(digraph, ptedges))
        digraph.remove_edges_from(ptedges)
        # map_opposite_edges(digraph)
        uturn_fork_dilanes = add_uturn_restrictions(digraph, dilanes)
        dilanes.update(uturn_fork_dilanes)  # !!!
        restrictions_ids, restrictions_nds, intersections = (
            get_restricted_moves(digraph, dilanes)
            )

        newdigraph, turnsgraph = check_restrictions_integrity(digraph, restrictions_nds)
        # newdigraph = remove_restricted_connections(
        #     digraph, restrictions_ids, restrictions_nds, uturn_fork_dilanes, ncores
        #     )

        newdilanes = correct_lane_definitions(dilanes, newdigraph)
    else:
        newdilanes = {}
        newdigraph = digraph
        ptgraph = None

    if internal_maneuvers and 'node' in shp.columns:
        simplify_intersections(newdilanes, newdigraph)

    if lanes_dbf is not None:
        ld = get_lane_definitions(newdilanes, newdigraph, common_lane=common_lane)
        write_lane_definitions(ld, lane_definitions_save_path)

    if ptgraph is not None:
        newdigraph = nx.compose(newdigraph, ptgraph)

    transform_unsupported_types(newdigraph)
    nodes, edges = momepy.nx_to_gdf(newdigraph, points=True, lines=True)

    write_network(newdigraph, net_save_path)
    edges.to_file(edges_save_path, encoding='utf-8')
    nodes.to_file(nodes_save_path, encoding='utf-8')


def parse_args(
        args_list: List[str] = sys.argv[1:]
        ) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--shp-path')
    parser.add_argument('-l', '--lane-connections-path', help='dbf')
    parser.add_argument('-n', '--net-save-path')
    parser.add_argument('-e', '--edges-save-path')
    parser.add_argument('-N', '--nodes-save-path')
    parser.add_argument('-L', '--lane-definitions-save-path')
    parser.add_argument('-C', '--ncores', type=int, default=1)
    parser.add_argument('-S', '--separate-lanes', action='store_true')
    parser.add_argument('-i', '--internal-maneuvers', action='store_true')
    args = parser.parse_args(args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    prepare_ceda_network(
        shp_path=args.shp_path,
        lane_connections_path=args.lane_connections_path,
        net_save_path=args.net_save_path,
        edges_save_path=args.edges_save_path,
        nodes_save_path=args.nodes_save_path,
        lane_definitions_save_path=args.lane_definitions_save_path,
        ncores=args.ncores,
        internal_maneuvers=args.internal_maneuvers,
        common_lane=not args.separate_lanes
        )
