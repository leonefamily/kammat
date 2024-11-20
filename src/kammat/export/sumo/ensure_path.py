# -*- coding: utf-8 -*-
"""
Created on Fri Jan 20 18:51:57 2023

@author: dgrishchuk
"""

from itertools import permutations, combinations
import argparse
import sys
import os
import re

import lxml
from typing import Union, Dict, List, Optional
from pathlib import Path


if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
    import sumolib  # noqa
else:
    raise ImportError('SUMO_HOME is missing in system environment')


def parse_args(
        args_from: Optional[List[str]] = None
) -> argparse.Namespace:
    args_list = sys.argv[1:] if args_from is None else args_from
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--net", help="*.net.xml")
    parser.add_argument("-r", "--routes", help="*.rou.xml")
    parser.add_argument("-o", "--output", help="New *.rou.xml")
    args = parser.parse_args(args_from)
    return args


def find_predecessor(
        edge,
        edges
):
    predecessors = []
    incomings = edge.getIncoming()
    for incoming in incomings.keys():
        if incoming in edges:
            pred = find_predecessor(incoming, edges)
        else:
            pred = incoming
        if isinstance(pred, list):
            predecessors.extend(pred)
        else:
            predecessors.append(pred)
    return predecessors


def remove_invalid_routes(
        routes: lxml.etree.Element,
        net,
        save_valid=None
) -> Dict[str, List[str]]:

    badtrips = []
    cnt = 0

    trips = routes.findall('trip')
    for trip in trips:
        fromedge = net.getEdge(trip.attrib['from'])
        toedge = net.getEdge(trip.attrib['to'])
        path, length = net.getFastestPath(
            fromedge,
            toedge,
            vClass='passenger'
            )
        if not path:
            # !!! fix
            badtrips.append(trip.attrib['id'])
            print(trip.attrib['from'], trip.attrib['to'])
            routes.remove(trip)
        cnt += 1
        

    persons = routes.findall('person')
    for person in persons:
        if person.find('ride').attrib['lines'] in badtrips:
            routes.remove(person)
        # for stop in person.findall('stop'):
        #     stop.attrib['edge'] = re.sub(r'_\d+$', '', stop.attrib['lane'])
        #     del stop.attrib['lane']
    if save_valid:
        lxml.etree.ElementTree(routes).write(save_valid, pretty_print=True)


def main(args):
    net = sumolib.net.readNet(args.net)
    routes = lxml.etree.parse(args.routes).getroot()
    remove_invalid_routes(routes, net, args.output)


if __name__ == '__main__':
    args = parse_args()
    main(args)
