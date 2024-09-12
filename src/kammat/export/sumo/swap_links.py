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
    edgeids = []
    with open(fpath, mode='r', encoding='utf-8') as f:
        for line in f.readlines():
            type_, edgeid = line.strip().split(':')
            if type_ == 'edge':
                edgeids.append(edgeid)
    if not edgeids:
        raise RuntimeError('There are no edge IDs in -s file')
    return edgeids


def get_unique_startends(fpath):
    startends = set()
    with open(fpath, mode='r', encoding='utf-8') as f:
        for line in f.readlines():
            matched = re.findall(r'from="(.+?)" to="(.+?)"', line.strip())
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


def replace_selected(replacements, fpath):
    with open(fpath, mode='r', encoding='utf-8') as f:
        text = f.read()
    for oldset, newset in replacements.items():
        if newset is None:
            print(f'Route between edges {oldset[0]} and {oldset[1]} is not changed, '
                  'but it is required. Manually delete presons containing string: '
                  f'from="{oldset[0]}" to="{oldset[1]}"')
            continue
        text = text.replace(f'from="{oldset[0]}" to="{oldset[1]}"',
                            f'from="{newset[0]}" to="{newset[1]}"')
        diff0 = oldset[0] != newset[0]
        diff1 = oldset[1] != newset[1]
        if diff0:
            for m in re.finditer(f'lane="{oldset[0]}_\d+".+ actType="from"', text):
                suborig = m.group()
                subnew = suborig.replace(oldset[0], newset[0])
                text = text.replace(suborig, subnew)
        if diff1:
            for m in re.finditer(f'lane="{oldset[1]}_\d+".+ actType="to"', text):
                suborig = m.group()
                subnew = suborig.replace(oldset[1], newset[1])
                text = text.replace(suborig, subnew)
            text = text.replace(f'to="{oldset[1]}"', f'to="{newset[1]}"')
    return text


def keep_influenced_startends(startends: set, edgeids: list) -> set:
    influenced = set()
    for startend in startends:
        if any(se in edgeids for se in startend):
            influenced.add(startend)
    return influenced


def _find_predecessor(edge, edges):
    predecessors = []
    incomings = edge.getIncoming()
    for incoming in incomings.keys():
        if incoming in edges:
            pred = _find_predecessor(incoming, edges)
        else:
            pred = incoming
        if isinstance(pred, list):
            predecessors.extend(pred)
        else:
            predecessors.append(pred)
    return predecessors


def main(args):
    net = sumolib.net.readNet(args.net)
    edgeids = parse_selected(args.selected)
    edges = [net.getEdge(edgeid) for edgeid in edgeids]
    startends = get_unique_startends(args.routes)
    influenced = keep_influenced_startends(startends, edgeids)
    prereplacements = find_predecessors(edges, net)
    replacements = get_valid_replacements(prereplacements, influenced, net)
    newroutes = replace_selected(replacements, args.routes)
    with open(args.output, mode='w', encoding='utf-8') as f:
        f.write(newroutes)


if __name__ == '__main__':
    args = parse_args()
    main(args)
