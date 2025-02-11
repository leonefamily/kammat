# -*- coding: utf-8 -*-
"""
Created on Wed Jun 15 11:18:35 2022

@author: dgrishchuk, KAM Brno
"""

from itertools import permutations, combinations
import argparse
import sys
import os
import re


if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
    import sumolib  # noqa
else:
    raise ImportError('SUMO_HOME is missing in system environment')


def parse_args(args_from: list = sys.argv[1:]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--net", help="*.net.xml")
    parser.add_argument("-r", "--routes", help="*.rou.xml")
    parser.add_argument("-o", "--output", help="New *.rou.xml")
    parser.add_argument("-s", "--selected", help="*.txt of selected edges")
    parser.add_argument("-oto", "--one-to-one", action='store_true',
                        help="Swap -f with -t")
    parser.add_argument("-f", "--fromid", help="Original edge ID")
    parser.add_argument("-t", "--toid", help="New edge ID")
    args = parser.parse_args(args_from)
    if args.one_to_one:
        if args.fromid is None or args.toid is None:
            raise AttributeError('Both -f and -t required if -oto selected')
    elif args.selected is None:
        raise AttributeError('-s is required if -oto not selected')
    return args


def parse_selected(fpath):
    nodeids = []
    with open(fpath, mode='r', encoding='utf-8') as f:
        for line in f.readlines():
            type_, edgeid = line.strip().split(':')
            if type_ == 'junction':
                nodeids.append(edgeid)
    if not nodeids:
        raise RuntimeError('There are no edge IDs in -s file')
    return nodeids


def get_unique_startends(fpath):
    startends = set()
    with open(fpath, mode='r', encoding='utf-8') as f:
        for line in f.readlines():
            matched = re.findall(r'fromJunction="(.+?)" toJunction="(.+?)"', line.strip())
            if matched:
                startends.add(matched[0])
    return startends


def find_predecessors(edges: list, net: sumolib.net.Net) -> dict:
    prereplacements = {}
    for edge in edges:
        # if edge.getID() == '17794_16689_13315':
        #     break
        prereplacements[edge] = _find_predecessor(edge, edges)
    return prereplacements


def get_valid_replacements(prereplacements: dict,
                           influenced: set, net: sumolib.net.Net) -> dict:
    # !!! TODO prefer paths after intersection if the replaced edge is second
    replacements = {}
    prerep_keys = {k.getID() for k in prereplacements.keys()}
    for old, candidates in prereplacements.items():
        oldid = old.getID()
        # startends with this edge:
        ses = {se for se in influenced if oldid in se}
        for se in ses:
            if all(e in prerep_keys for e in se):
                fredges = prereplacements[net.getEdge(se[0])]
                toedges = prereplacements[net.getEdge(se[1])]
                found = False
                for fr in fredges:
                    for to in toedges:
                        haspath = net.getShortestPath(fr, to)
                        if haspath[0]:
                            replacements[se] = (fr.getID(), to.getID())
                            break
                if se not in replacements:
                    replacements[se] = None
                continue
            orig_pos = se.index(oldid)
            # there can only be values 1 or 0, so cheating with boolean,
            # which is subclass of int, to get another node position
            tested = net.getEdge(se[int(not orig_pos)])
            for candidate in candidates:
                if orig_pos == 1:
                    fromto = tested, candidate
                else:
                    fromto = candidate, tested
                haspath = net.getShortestPath(*fromto)
                if haspath[0]:
                    replacements[se] = tuple(ft.getID() for ft in fromto)
                    break
            if se not in replacements:
                replacements[se] = None
    return replacements


def replace_selected(replacements, routes_path):
    from lxml import etree
    tree = etree.parse(routes_path)
    root = tree.getroot()
    
    junction_map = {k.getID(): v[0].getID() for k, v in replacements.items()}

    # Iterate through all elements in the XML
    for element in root.iter():
        # Replace 'fromJunction' if it exists in the mapping
        if 'fromJunction' in element.attrib:
            from_junction = element.attrib['fromJunction']
            if from_junction in junction_map:
                element.attrib['fromJunction'] = junction_map[from_junction]
                print('replaced', from_junction)

        # Replace 'toJunction' if it exists in the mapping
        if 'toJunction' in element.attrib:
            to_junction = element.attrib['toJunction']
            if to_junction in junction_map:
                element.attrib['toJunction'] = junction_map[to_junction]
                print('replaced', to_junction)
    return tree


def keep_influenced_startends(startends: set, nodeids: list) -> set:
    influenced = set()
    for startend in startends:
        if any(se in nodeids for se in startend):
            influenced.add(startend)
    return influenced


def _find_predecessor(node, nodes, try_n=0, max_try_n=20):
    predecessors = []
    incoming_edges = node.getIncoming()
    incomings_nodes = [edge.getFromNode() for edge in incoming_edges][:1]
    
    for incoming in incomings_nodes:
        if incoming in nodes:
            if try_n > max_try_n:
                return predecessors
            try_n += 1
            pred = _find_predecessor(incoming, nodes, try_n, max_try_n)
        else:
            pred = incoming
        if isinstance(pred, list):
            predecessors.extend(pred)
        else:
            predecessors.append(pred)
    return predecessors


def main(
        net_path,
        routes_path,
        output_path,
        selected_path
):
    # removes mentioned nodes by finding other path
    net = sumolib.net.readNet(net_path)
    nodeids = parse_selected(selected_path)
    nodes = [net.getNode(nodeid) for nodeid in nodeids]
    startends = get_unique_startends(routes_path)
    influenced = keep_influenced_startends(startends, nodeids)
    replacements = find_predecessors(nodes, net)
    # replacements = get_valid_replacements(prereplacements, influenced, net)
    tree = replace_selected(replacements, routes_path)
    tree.write(output_path, pretty_print=True, xml_declaration=True, encoding='UTF-8')


if __name__ == '__main__':
    args = parse_args()
    main(args)
