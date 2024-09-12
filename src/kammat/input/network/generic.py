# -*- coding: utf-8 -*-
"""
Created on Mon Feb 27 14:41:18 2023

@author: dgrishchuk
"""

import sys
import momepy
import logging
import argparse
import pandas as pd
import networkx as nx
import geopandas as gpd
from io import StringIO
from pathlib import Path
from typing import Union, List, Dict, Tuple, Any
from kammat.defaults.constants import LOGGER_FORMAT

logging.basicConfig(
    format=LOGGER_FORMAT,
    level=logging.INFO
    )


def delete_islands_dir(
        graph: nx.MultiGraph
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


def generate_attrs_string(
        attrs: Dict[str, Any],
        towrite: List[str] = None
) -> str:
    if towrite is None:
        return ''
    s = '      <attributes>\n'
    fails = 0
    for c in towrite:
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
        outf: str,
        node_prefix: str = ''
) -> nx.MultiDiGraph:
    logging.info(f'Writing network {outf}')
    bigstring = StringIO()
    bigstring.write('<?xml version="1.0" encoding="utf-8"?>\n')
    bigstring.write(
        '<!DOCTYPE network SYSTEM '
        '"http://matsim.org/files/dtd/network_v2.dtd">\n')
    bigstring.write('<network name="net">\n')

    bigstring.write('<nodes>\n')
    for i, ((x, y), node) in enumerate(graph.nodes(data=True)):
        num = f"{node_prefix}{i}"
        node['nodenum'] = num
        bigstring.write(f'    <node id="{num}" x="{x}" y="{y}" />\n')
    bigstring.write('</nodes>\n')

    bigstring.write('<links>\n')
    for j, edge in enumerate(graph.edges):
        from_node, to_node, edge_num = edge
        attrs = graph.edges[edge]
        fr = graph.nodes[from_node]['nodenum']
        to = graph.nodes[to_node]['nodenum']
        attrs['link_id'] = f'{fr}_{to}_{j}'
        # geoms = list(attrs['geometry'].coords)
        # if from_node != geoms[0] and to_node != geoms[-1]:
        #     attrs['geometry'] = LineString(geoms[::-1])        
        bigstring.write(generate_link_string(fr, to, attrs))

    bigstring.write('</links>\n')
    bigstring.write('</network>\n')

    with open(outf, mode='w', encoding='utf-8') as wr:
        wr.write(bigstring.getvalue())
    return graph


def generate_link_string(
        fr: Union[str, int],
        to: Union[str, int],
        attrs: Dict[str, Any],
        add_attrs: Tuple[str] = ('geometry',)
):
    l_len = attrs["geometry"].length
    l_id = attrs["link_id"]
    attrstr = generate_attrs_string(attrs, add_attrs)
    return (f'    <link id="{l_id}" from="{fr}" to="{to}" length="{l_len}" '
            f'capacity="{int(attrs["capacity"])}" '
            f'freespeed="{attrs["freespeed"]}" '
            f'modes="{attrs["modes"]}" permlanes="{attrs["permlanes"]}" >\n'
            f'{attrstr}'
            '    </link>\n')


def graph_to_shp(
        graph: nx.MultiGraph,
        shp_nodes_path,
        shp_edges_path
):
    logging.info('Writing graph to edges and nodes shp')
    nodes, edges = momepy.nx_to_gdf(graph, points=True, lines=True)
    nodes.astype(object).infer_objects().to_file(shp_nodes_path)
    edges.astype(object).infer_objects().to_file(shp_edges_path)


def prepare_generic_network(
        shp_path: Union[str, Path],
        net_save_path: Union[str, Path],
        edges_save_path: Union[str, Path],
        nodes_save_path: Union[str, Path],
):
    logging.info('Road network processing started')
    shp = gpd.read_file(shp_path).dropna(subset=['geometry'])
    digraph = momepy.gdf_to_nx(shp, approach="primal", directed=True)
    delete_islands_dir(digraph)
    write_network(digraph, net_save_path, node_prefix='p_')
    graph_to_shp(digraph, nodes_save_path, edges_save_path)
    logging.info('Car network processing finished')


def parse_args(
        args_list: List[str] = sys.argv[1:]
        ) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-s', '--shp-path')
    parser.add_argument('-n', '--net-save-path')
    parser.add_argument('-e', '--edges-save-path')
    parser.add_argument('-N', '--nodes-save-path')
    parser.add_argument('-u', '--restrict-uturns', action='store_true')
    args = parser.parse_args(args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    prepare_generic_network(
        shp_path=args.shp_path,
        net_save_path=args.net_save_path,
        edges_save_path=args.edges_save_path,
        nodes_save_path=args.nodes_save_path
        )
