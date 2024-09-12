# -*- coding: utf-8 -*-
"""
Created on Mon Jun 13 15:49:53 2022

@author: dgrishchuk
"""

import matsim
import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from collections import defaultdict
from datetime import timedelta as td
import sys
from kammat.input.population.agent import Agent, write_agents, start_pop_writer, end_pop_writer
import networkx as nx
import momepy
import os
from io import StringIO
import argparse
from pathlib import Path

if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
    import sumolib  # noqa
else:
    raise ImportError('SUMO_HOME is missing in system environment')


def parse_args(args_from: list = sys.argv[1:]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("-n", "--net", help="MATSim network")
    parser.add_argument("-nc", "--net-crs", default='epsg:5514',
                        help="CRS for bounding box, default epsg:5514")
    parser.add_argument("-e", "--events", help="MATSim events")
    parser.add_argument("-b", "--bbox", help="bounds: 'xmin,ymin,xmax,ymax' in WGS84")
    parser.add_argument("-bc", "--bbox-crs", default='epsg:4326',
                        help="CRS for bounding box, default epsg:4326")    
    parser.add_argument("-t1", "--time1", default=25200, type=int,
                        help="Start time in seconds")
    parser.add_argument("-t2", "--time2", default=28800, type=int,
                        help="End time in seconds")
    parser.add_argument("-t", "--tolerance", default=0.1, type=float,
                        help="Tolerance for nodes to consider them being at the same point")
    parser.add_argument("-c", "--capacity", default=900, type=int,
                        help="Default capacity for one lane")
    parser.add_argument("-o", "--outdir", default='.',
                        help="Output directory")
    parser.add_argument("-on", "--onlynet", action='store_true',
                        help="Transform only net")
    parser.add_argument("-oe", "--onlyevents", action='store_true',
                        help="Transform only events")

    args = parser.parse_args(args_from)
    if args.onlynet and args.onlyevents:
        raise AttributeError('Check either -on or -oe, not both')
    args.netconvert_capacity = 1800
    return args


def cut_net(netpath, bounds=None, bbox_crs='epsg:4326', net_crs='epsg:5514'):
    net = matsim.read_network(netpath).as_geo(net_crs)
    net = net[~net['link_id'].str.contains('pt')]

    if bounds is None:
        net['center'] = net.centroid
        return net

    bbox = box(*[float(coord) for coord in bounds.split(',')])
    if bbox_crs == net_crs:
        xmin, ymin, xmax, ymax = gpd.GeoSeries(bbox).set_crs(bbox_crs).iloc[0].bounds
    else:
        xmin, ymin, xmax, ymax = gpd.GeoSeries(bbox).set_crs(bbox_crs).to_crs(net_crs).iloc[0].bounds

    net_cut = net.cx[xmin:xmax, ymin:ymax].copy()
    if len(net_cut) == 0:
        raise RuntimeError('bbox is either too small or has incorrect values; '
                           'cut net does not have a single edge')
    net_cut['center'] = net_cut.centroid
    # xys = net_cut['center'].centroid.apply(lambda r: r.coords[0]).tolist()
    # net_cut[['x', 'y']] = pd.DataFrame(xys, index=net_cut.index)
    return net_cut


def process_events(eventspath, net_cut, mintime, maxtime):
    events = matsim.event_reader(eventspath,
                                 types='vehicle leaves traffic,entered link')
    persons = defaultdict(lambda: defaultdict(list))

    allowed_links = set(net_cut['link_id'].tolist())

    for i, event in enumerate(events):
        if mintime <= event['time'] < maxtime:
            if 'link' in event and event['link'] in allowed_links and 'veh' not in event['vehicle']:
                persons[event['vehicle']]['link'].append(event['link'])
                persons[event['vehicle']]['type'].append(event['type'])
                persons[event['vehicle']]['time'].append(event['time'])
        elif event['time'] >= maxtime:
            break
        if i % 1000000 == 0:
            tm = int_to_time(event['time'])
            print(f'Event {i}, time {tm}')
    return persons


def int_to_time(itime):
    return pd.to_datetime(itime, unit='s').time()


def split_agent_plan(r: pd.Series, links_coords: dict, startfrom: int=0):
    agents = {}
    pers = startfrom
    lasttime = 0
    lastev = ''
    for k, evtype in enumerate(r.type):
        if evtype == 'entered link' and pers in agents:
            if r.time[k] - lasttime > 600 and k != 0:
                agents[pers]['link_id1'] = r.link[k - 1]
                agents[pers]['coord1'] = links_coords[r.link[k - 1]] # ['coord']
                # agents[pers]['x1'] = links_coords[r.link[k - 1]]['x']
                # agents[pers]['y1'] = links_coords[r.link[k - 1]]['y']
                # print(f'Row {k - 1}, pers {pers} finished on link {r.link[k - 1]}, time interval, {int_to_time(r.time[k - 1])}')
                pers += 1
                agents[pers] = {'end_time': r.time[k],
                                'link_id0': r.link[k],
                                'person': r.person,
                                'coord0': links_coords[r.link[k]]}  # ['coord'],
                                # 'x0': links_coords[r.link[k]]['x'],
                                # 'y0': links_coords[r.link[k]]['y']}
                # print(f'Row {k}, pers {pers} started on link {r.link[k]}, time {int_to_time(r.time[k])}')
        elif evtype == 'entered link' and pers not in agents:
            # print(f'New keydict invoked for pers {pers}')
            agents[pers] = {'end_time': r.time[k],
                            'link_id0': r.link[k],
                            'person': r.person,
                            'coord0': links_coords[r.link[k]]}  # ['coord'],
                            # 'x0': links_coords[r.link[k]]['x'],
                            # 'y0': links_coords[r.link[k]]['y']}
            # print(f'Row {k}, pers {pers} started on link {r.link[k]}, time {int_to_time(r.time[k])}')
        elif evtype == 'vehicle leaves traffic' and lastev == 'entered link' and pers in agents:
            agents[pers]['link_id1'] = r.link[k]
            agents[pers]['coord1'] = links_coords[r.link[k]]  # ['coord']
            # agents[pers]['x1'] = links_coords[r.link[k]]['x']
            # agents[pers]['y1'] = links_coords[r.link[k]]['y']
            # print(f'Row {k}, pers {pers} finished on link {r.link[k]}, time {int_to_time(r.time[k])}')
            pers += 1
        lasttime = r.time[k]
        lastev = evtype
    if evtype != 'vehicle leaves traffic' and 'x1' not in agents[pers]:
        agents[pers]['link_id1'] = r.link[k]
        agents[pers]['coord1'] = links_coords[r.link[k]]  # ['coord']
        # agents[pers]['x1'] = links_coords[r.link[k]]['x']
        # agents[pers]['y1'] = links_coords[r.link[k]]['y']
        # print(f'Row {k}, pers {pers} finished on link {r.link[k]}, time {int_to_time(r.time[k])}')
    return agents


def modify_plans(net_cut, persons):
    # links_coords = {r.link_id: dict(x=r.x, y=r.y, coord=r.center) for i, r in net_cut.iterrows()}
    links_coords = {r.link_id: tuple(r.center.coords[0]) for i, r in net_cut.iterrows()}
    df = pd.DataFrame(persons).transpose()
    df.index.name = 'person'
    pers = 0
    agents = {}
    for j, r in df.reset_index().iterrows():
        oneagent = split_agent_plan(r, links_coords, pers)
        pers = max(oneagent) + 1 if oneagent else pers + 1
        agents.update(oneagent)
    return agents


def validate_plans(graph):
    for e in graph.edges:
        pass


def dist(c1, c2):
    x1, y1 = c1
    x2, y2 = c2
    return ((x1 - x2)**2 + (y1 - y2)**2)**0.5


def write_plans(agents, graph, path):
    edgeids = {attrs['link_id']: (u, v)
               for u, v, attrs in graph.edges(data=True)}
    agents_list = []
    skipped = {
        'single': 0,
        'no_path': 0
        }

    for num, ag in agents.items():
        if ag['link_id0'] == ag['link_id1']:
            skipped['single'] += 1
            continue
        coords1, coords2 = edgeids[ag['link_id0']][0], edgeids[ag['link_id1']][0]
        if not nx.has_path(graph, coords1, coords2):
            skipped['no_path'] += 1
            continue
        agobj = Agent(activities=['from', 'to'])
        agobj.modes = ['truck' if 'f_' in ag['person'] else 'car']
        agobj.endtimes = [td(seconds=ag['end_time'])]
        agobj.links = [ag['link_id0'], ag['link_id1']]
        agobj.coords = [ag['coord0'], ag['coord1']]
        agobj.prepare_xml_block(num)
        agents_list.append(agobj)

    befc = len(agents)
    nowc = len(agents_list)
    diff = round(nowc * 100 / befc, 2)
    print(f"Skipped {skipped['single']} single road segment plans "
          f"and {skipped['no_path']} invalid plans. "
          f"Plans count before: {befc}, now: {nowc} - {diff}% of total")

    start_pop_writer(path)
    write_agents(agents_list, path)
    end_pop_writer(path)


def reshape_net(net_cut, tolerance=0.1) -> nx.MultiDiGraph:
    graph = momepy.gdf_to_nx(net_cut, directed=True)
    # net_cut.plot()
    deadends = {n: None for n in graph.nodes if graph.out_degree(n) == 0}
    nodes = [n for n in graph.nodes if n not in deadends]
    maxdist = 2**0.5 * tolerance * 1.05

    for n in deadends:
        dists = [dist(n, x) for x in nodes]
        candidates = [i for i, d in enumerate(dists) if d < maxdist]
        if not candidates:
            continue
        least = min([s for i, s in enumerate(nodes) if i in candidates],
                    key=lambda x: dist(x, n))
        deadends[n] = least

    for endn, startn in deadends.items():
        if startn is None:
            continue
        ende = list(graph.in_edges(endn))[0]
        newende = (ende[0], startn)
        endeattrs = list(graph.get_edge_data(*ende).values())[0]
        graph.remove_node(endn)
        graph.add_edge(*newende, **endeattrs)

    return graph


def create_link_string(fr, to, attrs, lanecap=900, deflanecap=1800):
    permlanes = max(round(attrs['capacity'] / lanecap), 1)
    return (f'    <link id="{attrs["link_id"]}" '
            f'from="{fr}" to="{to}" '
            f'length="{attrs["length"]}" '
            f'capacity="{deflanecap * permlanes}" '
            f'permlanes="{permlanes}" '
            f'freespeed="{round(attrs["freespeed"])}" '
            f'modes="{attrs["modes"]}"/>\n')



def write_net(graph, outf):

    bigstring = StringIO()
    bigstring.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    bigstring.write(
        '<!DOCTYPE network SYSTEM "http://www.matsim.org/files/dtd/network_v2.dtd">\n')
    bigstring.write('<network name="net">\n')

    bigstring.write('<nodes>\n')
    for i, node in enumerate(graph.nodes):
        graph.nodes[node]['nodenum'] = i
        bigstring.write(f'    <node id="{i}" x="{node[0]}" y="{node[1]}" />\n')
    bigstring.write('</nodes>\n')

    bigstring.write('<links>\n')
    for j, edge in enumerate(graph.edges):
        from_node, to_node, edge_num = edge
        attrs = graph.edges[edge]
        fr = graph.nodes[from_node]['nodenum']
        to = graph.nodes[to_node]['nodenum']
        bigstring.write(create_link_string(fr, to, attrs))

    bigstring.write('</links>\n')
    bigstring.write('</network>\n')

    with open(outf, mode='w', encoding='utf-8') as wr:
        wr.write(bigstring.getvalue())


def call_netconvert(origpath, convpath):
    os.system(f'netconvert --matsim "{origpath}" -o "{convpath}" --xml-validation never')


def create_sumocfg(cfgpath, netpath, routepath, t1):
    with open(cfgpath, mode='w', encoding='utf-8') as cfg:
        cfg.write(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<configuration xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="http://sumo.dlr.de/xsd/sumoConfiguration.xsd">\n\n'
            )
        cfg.write('\t<input>\n'
                  f'\t\t<net-file value="{netpath}"/>\n'
                  f'\t\t<route-files value="{routepath}"/>\n'
                  '\t</input>\n\n')
        cfg.write('\t<time>\n'
                  f'\t\t<begin value="{t1}"/>\n'
                  '\t</time>\n\n')
        cfg.write('</configuration>')


def get_paths(args):
    paths = {}
    basedir = Path(args.outdir)
    basenet = Path(args.net).stem.split(".")[0]
    paths['tempnet'] = basedir / f'{basenet}.xml'
    paths['outnet'] = basedir / f'{basenet}.net.xml'
    if not args.onlynet:
        baseevents = Path(args.events).stem.split(".")[0]
        paths['tempplans'] = basedir / f'{baseevents}.xml'
        paths['outroutes'] = basedir / f'{baseevents}.rou.xml'
        paths['sumocfg'] = basedir / 'scenario.sumocfg'
    return paths


def call_plans_converter(planspath, routespath, t1):
    scriptpath = Path(os.environ['SUMO_HOME']) / 'tools/import/matsim/matsim_importPlans.py'
    os.system(f'python "{scriptpath}" --plan-file "{planspath}" -o "{routespath}" '
              f'--default-start "{int_to_time(t1)}" --default-end="30:00:00"')


def main(args):
    paths = get_paths(args)

    net_cut = cut_net(args.net, args.bbox)
    graph = reshape_net(net_cut, args.tolerance)

    write_net(graph, paths['tempnet'])
    call_netconvert(paths['tempnet'], paths['outnet'])

    if not args.onlynet:
        persons = process_events(args.events, net_cut, args.time1, args.time2)
        agents = modify_plans(net_cut, persons)

        write_plans(agents, graph, paths['tempplans'])
        call_plans_converter(paths['tempplans'], paths['outroutes'], args.time1)
        create_sumocfg(paths['sumocfg'], paths['outnet'].name,
                       paths['outroutes'].name, args.time1)


def get_full_trips_number(
        trips_path: str,
        include_modes: tuple = ('car',)
        ) -> int:
    trips = pd.read_csv(trips_path, sep=';', decimal=',')
    return len(trips[trips['modes'].isin(include_modes)])


if __name__ == '__main__':
    args = parse_args()
    main(args)
