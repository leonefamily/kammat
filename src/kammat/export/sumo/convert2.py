import copy
import os
import sys
import tempfile
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Union, Dict, List, Set, Tuple, Optional, Sequence

import lxml.etree
import numpy as np
from lxml import etree
import matsim
import pandas as pd
import datetime
import re

from shapely.geometry import Point, LineString, Polygon
from shapely.constructive import offset_curve
from shapely import get_point

from kammat.output.pt import load_pt_schedule, get_transit_stops, PtStops
from kammat.output.road import load_network
import geopandas as gpd

from kammat.output.utils import defaultdict2dict


if 'SUMO_HOME' in os.environ:
    sys.path.append(os.path.join(os.environ['SUMO_HOME'], 'tools'))
    import sumolib  # noqa
else:
    raise ImportError('SUMO_HOME is missing in system environment')


EDGES_VCLASS_MAP = {
    'car': [
        'passenger',
        'private',
        'taxi',
        'delivery',
        'hov',
        'vip',
        'authority',
        'army',
        'evehicle',
        'motorcycle',
        'moped'
    ],
    'truck': [
        'truck',
        'trailer'
    ],
    'artificial': [
        'bus',
        'tram',
        'rail_electric',
        'rail',
        'rail_fast',
        'rail_urban',
        'cable_car',
        'subway',
        'ship'
    ],
    'bus': [
        'bus',
        'coach'
    ],
    'tram': [
        'tram',
        'rail_electric'
    ],
    'rail': [
        'rail_fast',
        'rail_urban',
        'rail_electric',
        'rail'
    ],
    # all whitespaces are replaced with underscores
    'trolleybus_service': [
        'bus'
    ]
}

VEHICLES_VCLASS_MAP = {
    'car': 'passenger',
    'truck': 'truck',
    'bus': 'bus',
    # all whitespaces are replaced with underscores
    'trolleybus_service': 'bus',
    'tram': 'tram',
    'rail': 'rail',
    'ferry': 'ship'
}

VEHICLE_UNRECOGNIZED = 'passenger'
EDGE_UNRECOGNIZED = 'all'


def get_links_to_links(
        lanes_path: Union[str, Path]
) -> Dict[str, Set[str]]:
    lanes_tree = etree.parse(lanes_path)
    lanes_root = lanes_tree.getroot()
    links_to_links = defaultdict(set)
    for elem in lanes_root.getiterator():
        if etree.QName(elem).localname == 'toLink':
            from_link = elem.getparent().getparent().getparent().attrib['linkIdRef']
            to_link = elem.attrib['refId']
            links_to_links[from_link].add(to_link)
    links_to_links = defaultdict2dict(links_to_links)
    return links_to_links


def extract_routes_stops(
        pt_schedule: lxml.etree.ElementTree
) -> Dict[str, Dict[str, Dict[str, Union[List[str], str]]]]:
    drop_namespaces(pt_schedule)
    lines_routes_stops = defaultdict(dict)
    for line_el in pt_schedule.getroot().findall('transitLine'):
        line_id = line_el.attrib['id']
        line_name = line_el.attrib['name'] if 'name' in line_el.attrib else '*'
        routes_dict = defaultdict(dict)
        for route_el in line_el.findall('transitRoute'):
            stops_list = []
            vehs_list = []
            for rprofile_el in route_el.findall('routeProfile'):
                for stop_el in rprofile_el.findall('stop'):
                    stops_list.append(stop_el.attrib['refId'])
            for dep_el in route_el.findall('departures'):
                for veh_el in dep_el.findall('departure'):
                    vehs_list.append(veh_el.attrib['vehicleRefId'])
            routes_dict[route_el.attrib['id']]['stops'] = stops_list
            routes_dict[route_el.attrib['id']]['vehicles'] = vehs_list
        lines_routes_stops[line_id]['name'] = line_name
        lines_routes_stops[line_id]['routes'] = routes_dict
    return defaultdict2dict(lines_routes_stops)


def convert_nodes(
        nodes_cut: gpd.GeoDataFrame
) -> lxml.etree.ElementTree:
    nodes = []
    for nn, nrow in nodes_cut.iterrows():

        nodes.append({
            'id': str(nrow['node_id']),
            'x': str(nrow['x']),
            'y': str(nrow['y']),
            'type': 'priority'  # !!! possibly modify later
        })
    nodes_root = etree.Element("nodes")
    for node in nodes:
        node_el = etree.SubElement(nodes_root, "node")
        for k, v in node.items():
            node_el.attrib[k] = v
    nodes_tree = nodes_root.getroottree()
    return nodes_tree


def convert_edges(
        net_cut: gpd.GeoDataFrame,
        sidewalk_width: Optional[float] = 1.5
) -> lxml.etree.ElementTree:
    edges = []
    allowed_modes_map = {}
    dup_fromto_net = net_cut[
        net_cut[['from_node', 'to_node']].duplicated(keep=False)
    ]
    dup_geoms = []
    for ftnodes, ftnet in dup_fromto_net.groupby(['from_node', 'to_node']):
        ftmodes = ftnet['modes'].unique()
        if len(ftmodes) > 1 and ('tram' in ftmodes or 'rail' in ftmodes):
            dup_geoms.extend(
                ftnet['link_id'].tolist()
            )
    offsets = net_cut.apply(
        lambda r: 0 if r['link_id'] not in dup_geoms else (
            0 if r['modes'] in ['tram', 'rail'] else -5
        ),
        axis=1
    )

    # if a link is one way, place it at the center of
    # its own axis, not to its left top/bottom corner
    onedir_ids = net_cut[
        ~net_cut.reverse().geometry.isin(net_cut.geometry.tolist())
    ]['link_id'].unique().tolist()

    for en, erow in net_cut.iterrows():
        modes = tuple(set(erow['modes'].split(',')))
        if modes not in allowed_modes_map:
            allowed_modes = set()
            for mode in modes:
                if mode in EDGES_VCLASS_MAP:
                    for edge_mode in EDGES_VCLASS_MAP[mode]:
                        allowed_modes.add(edge_mode)
                else:
                    allowed_modes.add(EDGE_UNRECOGNIZED)
            if 'all' in allowed_modes:
                allowed_modes = {'all'}
            allowed_modes_map[modes] = allowed_modes
        else:
            allowed_modes = allowed_modes_map[modes]

        str_allowed_modes = ' '.join(allowed_modes)

        edge = {
            'id': erow['link_id'],
            'from': erow['from_node'],
            'to': erow['to_node'],
            'numLanes': str(int(erow['permlanes'])),
            'speed': str(float(erow['freespeed'])),
            'allow': str_allowed_modes
        }
        geom = erow.geometry

        if sidewalk_width:
            edge['sidewalkWidth'] = str(sidewalk_width)

        if offsets[en] != 0:
            geom = offset_curve(geom, distance=offsets[en])
        geom_str = ' '.join(
            f'{c[0]},{c[1]}' for c in list(geom.coords)
        )
        edge['shape'] = geom_str
        if erow['link_id'] in onedir_ids:
            edge['spreadType'] = 'center'
        edges.append(edge)

    edges_root = etree.Element("edges")
    for edge in edges:
        edge_el = etree.SubElement(edges_root, "edge")
        for k, v in edge.items():
            edge_el.attrib[k] = v
    edges_tree = edges_root.getroottree()
    return edges_tree


def convert_stops(
        pt_stops: PtStops,
        pt_stops_within: PtStops,
        pt_schedule,
        net_cut: gpd.GeoDataFrame,
        stop_capacity: int = 100,
        stop_length: int = 40,
) -> lxml.etree.ElementTree:
    stops = []
    used_links = set()
    for stop_id, stop_data in pt_stops_within.items():
        closest_dists = net_cut.distance(stop_data['geometry'])
        closest_dist = closest_dists.min()
        closest_link = net_cut.loc[closest_dists.idxmin()]
        if closest_dist > 50:
            warnings.warn(
                f"Stop {stop_id} ({stop_data['name'] if 'name' in stop_data else None}) "
                f"is {closest_dist} m. away from the closest link {closest_link['link_id']}"
            )
        used_links.add(closest_link['link_id'])
        stop = {
            'id': stop_id,
            # first lane after sidewalk, may cause problems
            # if not used with sidewalks (e.g. no such lane)
            'lane': closest_link['link_id'] + '_1',
            'startPos': str(max(np.floor(closest_link.length) - stop_length, 0)),
            'endPos': str(np.floor(closest_link.length)),
            'friendlyPos': 'true',
            'personCapacity': str(stop_capacity),
        }
        if 'name' in stop_data and stop_data['name'] is not None:
            stop['name'] = stop_data['name']
        stops.append(stop)

    random_link_df = net_cut[~net_cut['link_id'].isin(list(used_links))]
    if len(random_link_df) != 0:
        random_link = random_link_df['link_id'].sample(1).iloc[0]
    else:
        random_link = net_cut['link_id'].sample(1).iloc[0]
    dummy_stop = {
        'id': "DO_NOT_REMOVE",
        'lane': random_link + '_1',
        'startPos': str(0),
        'endPos': str(5),
        'friendlyPos': 'true',
        'personCapacity': str(5),
        'name': 'Move me, but do not delete!',
        'lines': 'Move me, but do not delete!'
    }
    stops.append(dummy_stop)

    lines_routes_stops = extract_routes_stops(pt_schedule=pt_schedule)
    additional_root = etree.Element("additional")
    for stop in stops:
        stop_el = etree.SubElement(additional_root, "busStop")
        for k, v in stop.items():
            stop_el.attrib[k] = v
        lines_names = set()
        routes_stops_ids = defaultdict(set)
        for line_id, line_data in lines_routes_stops.items():
            line_name = line_data['name']
            for route_id, route_data in line_data['routes'].items():
                if stop['id'] in route_data['stops']:
                    routes_stops_ids[(line_id, line_name)].add(
                        (route_data['stops'][-1], pt_stops[route_data['stops'][-1]]['name'])
                    )
                    lines_names.add(line_name)
        if lines_names:
            stop_el.attrib['lines'] = ' '.join(lines_names)
            param_count = 0
            for (line_id, line_name), stop_data in routes_stops_ids.items():
                for set_num, (stop_id, stop_name) in enumerate(stop_data):
                    param_el = etree.SubElement(stop_el, 'param')
                    param_el.attrib['key'] = f"{line_name} ({line_id}) [{set_num}]"
                    param_el.attrib['value'] = f'{stop_name} ({stop_id})'
                    param_count += 1
    additional_tree = additional_root.getroottree()
    return additional_tree


def get_transit_vehicles_types(
        matsim_transit_vehicles_path: Union[str, Path]
) -> Dict[str, str]:
    transit_vehicles_tree = etree.parse(matsim_transit_vehicles_path)
    drop_namespaces(transit_vehicles_tree)

    transit_vehicles_types = {}
    for veh in transit_vehicles_tree.findall('vehicle'):
        transit_vehicles_types[veh.attrib['id']] = re.sub(r'\s+', '_', veh.attrib['type'])
    return transit_vehicles_types


def get_vehicle_types(
        matsim_vehicles_path: Union[str, Path],
        default_capacity: int = 4,
        transit_vehicles_types: Optional[Dict[str, str]] = None
):
    vehicles_tree = etree.parse(matsim_vehicles_path)
    drop_namespaces(vehicles_tree)

    vehicle_types = {}
    if transit_vehicles_types:
        transit_types = set(transit_vehicles_types.values())
    else:
        transit_types = set()

    for veh_type in vehicles_tree.findall('vehicleType'):
        veh_type_name = re.sub(r'\s+', '_', veh_type.attrib['id'])
        veh_type_lname = veh_type_name.lower()
        capacity = (
            sum(int(float(cap)) for cap_type, cap in veh_type.find('capacity').items())
            if veh_type.findall('capacity') else default_capacity
        )
        vclass = (
                VEHICLES_VCLASS_MAP[veh_type_lname]
                if veh_type_lname in VEHICLES_VCLASS_MAP
                else VEHICLE_UNRECOGNIZED
        )
        vehicle_types[veh_type_name] = {
            'vClass': vclass,
            'personCapacity': capacity,
            'length': veh_type.find('length').attrib['meter'],
            'width': veh_type.find('width').attrib['meter'],
            'isPt': veh_type_name in transit_types
        }
        if veh_type_lname == 'trolleybus_service':
            vehicle_types[veh_type_name]['guiShape'] = 'bus/trolley'
        if float(vehicle_types[veh_type_name]['length']) > 15:
            if veh_type_lname in ['bus', 'trolleybus_service']:
                vehicle_types[veh_type_name]['guiShape'] = 'bus/flexible'

    vehicles = {}
    for veh in vehicles_tree.findall('vehicle'):
        vehicles[veh.attrib['id']] = veh.attrib['type']
    return vehicle_types, vehicles


def drop_namespaces(
        tree: lxml.etree.ElementTree
):
    for elem in tree.getiterator():
        if not (
                isinstance(elem, etree._Comment)
                or isinstance(elem, etree._ProcessingInstruction)
        ):
            elem.tag = etree.QName(elem).localname
    etree.cleanup_namespaces(tree)


def links_to_links_to_connections(
        links_to_links: Dict[str, Set[str]],
        net: gpd.GeoDataFrame,
) -> lxml.etree.ElementTree:
    allowed_links = set(net['link_id'].tolist())
    connections = []
    for link, to_links in links_to_links.items():
        if link not in allowed_links:
            continue
        if not to_links.issubset(allowed_links):
            print(f'Links incomplete {to_links}')
            continue
        for to_link in to_links:
            connections.append({
                'from': link,
                'to': to_link
            })
    connections_root = etree.Element("connections")
    for connection in connections:
        conn_el = etree.SubElement(connections_root, "connection")
        for k, v in connection.items():
            conn_el.attrib[k] = v
    tree = connections_root.getroottree()
    return tree


def cut_net(
        net: gpd.GeoDataFrame,
        cut_polygon: Polygon
) -> gpd.GeoDataFrame:
    net_coords = net.geometry.apply(
        lambda x: [Point(c) for c in list(x.coords)]
    )
    suitable_links = net_coords.apply(
        lambda x: cut_polygon.contains(x[0]) or cut_polygon.contains(x[-1])
    )
    net_cut = net[suitable_links]
    return net_cut


def filter_nodes(
        net: gpd.GeoDataFrame,
        nodes: gpd.GeoDataFrame
):
    nodes_cut = nodes[
        nodes['node_id'].isin(net['from_node'].unique()) |
        nodes['node_id'].isin(net['to_node'].unique())
    ]
    return nodes_cut

def remove_ignored_modes_links(
        net: gpd.GeoDataFrame,
        ignore_link_modes: Set[str]
):
    ignored_links_within = set(
        net[
            net['modes'].str.split(',').apply(
                lambda x: any(mode in x for mode in ignore_link_modes)
            )
        ]['link_id'].tolist()
    )
    # discard links that contain at least one mention of ignored modes
    net.drop(ignored_links_within, inplace=True)


def write_element_tree(
        tree: lxml.etree.ElementTree,
        path: Union[str, Path]
):
    with open(path, 'wb') as xml_file:
        tree.write(
            xml_file,
            pretty_print=True,
            xml_declaration=True,
            encoding='UTF-8'
        )


def int2time(
        itime: int
) -> datetime.time:
    return pd.to_datetime(itime, unit='s').time()


def str2sec(
        td_str: str
) -> float:
    return pd.to_timedelta(td_str).total_seconds()


def get_closest_link_data(
        orig_link_id: str,
        net: gpd.GeoDataFrame,
        net_cut: gpd.GeoDataFrame
) -> pd.Series:
    new_geom = net[net['link_id'] == orig_link_id].iloc[0].geometry.centroid
    new_link_series = net_cut.loc[net_cut.distance(new_geom).idxmin()]
    return new_link_series


def get_person_walk_leg(
        leg_row: pd.Series,
        allowed_links: Set[str],
        net: gpd.GeoDataFrame,
        net_cut: gpd.GeoDataFrame,
        cut_polygon: Polygon,
        mode: str = 'walk'
) -> Optional[Dict[str, Union[str, float]]]:
    if not cut_polygon.intersects(
        LineString([leg_row['start_geom'], leg_row['end_geom']])
    ):
        return
    start_link = leg_row['start_link']
    end_link = leg_row['end_link']
    walk_dict = {
        'mode': mode,
        'leg': leg_row.name
    }
    if start_link in allowed_links:
        walk_dict['depart'] = leg_row['dep_time']
        walk_dict['from'] = start_link
        if end_link in allowed_links:
            walk_dict['to'] = end_link
        else:
            new_end_link_ser = get_closest_link_data(
                orig_link_id=end_link,
                net=net, net_cut=net_cut
            )
            walk_dict['to'] = new_end_link_ser['link_id']
    else:
        new_start_link_ser = get_closest_link_data(
            orig_link_id=start_link,
            net=net, net_cut=net_cut
        )
        orig_speed = leg_row['distance'] / leg_row['trav_time']
        walk_dict['from'] = new_start_link_ser['link_id']
        if end_link in allowed_links:
            new_dist = new_start_link_ser['geometry'].centroid.distance(
                leg_row['end_geom']
            )
            new_dep_time = leg_row['dep_time'] + new_dist / orig_speed
            walk_dict['to'] = end_link
        else:
            new_end_link_ser = get_closest_link_data(
                orig_link_id=end_link,
                net=net, net_cut=net_cut
            )
            new_dist = new_start_link_ser['geometry'].centroid.distance(
                leg_row['end_geom']
            )
            new_dep_time = leg_row['dep_time'] + new_dist / orig_speed
            walk_dict['to'] = new_end_link_ser['link_id']
        walk_dict['depart'] = new_dep_time
    return walk_dict


def get_person_pt_leg(
        leg_row: pd.Series,
        pt_stops_within: PtStops,
        lines_routes_stops: Dict[str, Dict[str, Dict[str, Union[List[str], str]]]],
        mode: str = 'pt'
) -> Optional[Dict[str, Union[str, float]]]:
    if (leg_row['access_stop_id'] not in pt_stops_within and
            leg_row['egress_stop_id'] not in pt_stops_within):
        return
    pt_leg = {
        'mode': mode,
        'leg': leg_row.name,
        'depart': 'triggered'
    }
    if (leg_row['access_stop_id'] not in pt_stops_within and
            leg_row['egress_stop_id'] in pt_stops_within):
        pt_leg['lines'] = leg_row['vehicle_id']
        pt_leg['vehicle'] = leg_row['vehicle_id']
        pt_leg['busStop'] = leg_row['egress_stop_id']
    else:
        pt_leg['depart'] = leg_row['dep_time'] + leg_row['wait_time']
        pt_leg['lines'] = get_vehicle_line_name(
            lines_routes_stops=lines_routes_stops,
            pt_veh_id=leg_row['vehicle_id']
        )
        pt_leg['vehicle'] = leg_row['vehicle_id']
        if leg_row['egress_stop_id'] not in pt_stops_within:
            pt_leg['busStop'] = 'DO_NOT_REMOVE'
        else:
            pt_leg['busStop'] = leg_row['egress_stop_id']
        if leg_row['access_stop_id'] in pt_stops_within:
            pt_leg['fromBusStop'] = leg_row['access_stop_id']
        else:
            pt_leg['fromBusStop'] = None
    return pt_leg


def get_vehicle_line_name(
        lines_routes_stops: Dict[str, Dict[str, Dict[str, Union[List[str], str]]]],
        pt_veh_id: str
) -> Optional[str]:
    for line, line_data in lines_routes_stops.items():
        for route, route_data in line_data['routes'].items():
            if pt_veh_id in route_data['vehicles']:
                line_name = line_data['name']
                return line_name


def process_events(
        events_path: Union[str, Path],
        net_cut: gpd.GeoDataFrame,
        min_time: Union[int, float],
        max_time: Union[int, float],
        pt_stops_within: Optional[PtStops] = None
) -> Tuple[defaultdict, defaultdict]:
    allowed_links = set(net_cut['link_id'].tolist())
    pt_vehicles = defaultdict(list)
    road_vehicles = defaultdict(list)
    seen_pt_vehicles = set()
    pt_drivers = set()

    events = matsim.event_reader(events_path)

    for i, event in enumerate(events):
        if event['type'] == 'TransitDriverStarts':
            pt_drivers.add(event['driverId'])
            seen_pt_vehicles.add(event['vehicleId'])
        if min_time <= event['time'] < max_time:
            if pt_stops_within and event['type'] in ['VehicleArrivesAtFacility',
                                                     'VehicleDepartsAtFacility']:
                if event['facility'] in pt_stops_within and event['vehicle'] in seen_pt_vehicles:
                    pt_vehicles[event['vehicle']].append(event)
                else:
                    if event['vehicle'] in seen_pt_vehicles and len(pt_vehicles[event['vehicle']]) > 0:
                        if pt_vehicles[event['vehicle']][-1]['facility'] is not None:
                            event_new = copy.deepcopy(event)
                            event_new['facility'] = None
                            pt_vehicles[event['vehicle']].append(event_new)
                        else:
                            continue
            elif event['type'] == 'entered link':
                if event['vehicle'] in seen_pt_vehicles:
                    continue
                if event['link'] in allowed_links:
                    if event['vehicle'] not in road_vehicles or not road_vehicles[event['vehicle']]:
                        road_vehicles[event['vehicle']].append({
                            'start_link': event['link'],
                            'start_time': event['time'],
                            'last_link': event['link'],
                            'last_link_allowed': True
                        })
                    else:
                        if 'start_link' in road_vehicles[event['vehicle']][-1]:
                            road_vehicles[event['vehicle']][-1]['last_link'] = event['link']
                            road_vehicles[event['vehicle']][-1]['last_link_allowed'] = True
                        else:
                            road_vehicles[event['vehicle']][-1]['start_link'] = event['link']
                            road_vehicles[event['vehicle']][-1]['start_time'] = event['time']
                            road_vehicles[event['vehicle']][-1]['last_link'] = event['link']
                            road_vehicles[event['vehicle']][-1]['last_link_allowed'] = True
                else:
                    if event['vehicle'] not in road_vehicles or not road_vehicles[event['vehicle']]:
                        continue
                    if road_vehicles[event['vehicle']][-1]['last_link_allowed']:
                        road_vehicles[event['vehicle']][-1]['end_link'] = (
                            road_vehicles[event['vehicle']][-1]['last_link']
                        )
                        road_vehicles[event['vehicle']][-1]['last_link'] = event['link']
                        road_vehicles[event['vehicle']][-1]['last_link_allowed'] = False
                        road_vehicles[event['vehicle']].append({
                            'last_link': event['link'],
                            'last_link_allowed': False,
                        })
        elif event['time'] >= max_time:
            break
        if i % 1000000 == 0:
            tm = int2time(event['time'])
            print(f'Event {i}, time {tm}')
    pt_vehicles = {k: v for k, v in pt_vehicles.items() if v}

    return pt_vehicles, road_vehicles


def convert_pt_vehicles(
        pt_vehicles: Dict[str, List[Dict[str, str]]],
        vehicles: Dict[str, str],
        vehicles_types: Dict[str, Dict[str, str]],
        lines_routes_stops: Dict[str, Dict[str, Dict[str, Union[List[str], str]]]]
) -> lxml.etree.ElementTree:
    pt_veh_routes_root = etree.Element("routes")
    for vehicle_type, vehicle_data in vehicles_types.items():
        if vehicle_data['isPt']:
            vtype = etree.SubElement(pt_veh_routes_root, "vType")
            vtype.attrib['id'] = vehicle_type
            for k, v in vehicle_data.items():
                if k != 'isPt':
                    vtype.attrib[k] = str(v)

    for pt_veh_id, pt_veh_events in pt_vehicles.items():
        if not pt_veh_events:
            continue
        trip_el = etree.SubElement(pt_veh_routes_root, "trip")
        pt_veh_id_us = re.sub(r'\s+', '_', pt_veh_id)
        trip_el.attrib['id'] = pt_veh_id_us
        trip_el.attrib['type'] = re.sub(r'\s+', '_', vehicles[pt_veh_id])

        line_name = get_vehicle_line_name(
            lines_routes_stops=lines_routes_stops,
            pt_veh_id=pt_veh_id
        )
        trip_el.attrib['line'] = line_name

        for pt_veh_event in pt_veh_events:
            if pt_veh_event['facility'] is None:
                jump_el = etree.SubElement(trip_el, "jump")
                continue
            else:
                jump_el = None
            if pt_veh_event['type'] == 'VehicleDepartsAtFacility':
                children = trip_el.xpath('./stop')
                if children and 'until' not in children[-1].attrib:
                    children[-1].attrib['until'] = str(pt_veh_event['time'])
                elif not children:
                    stop_el = etree.SubElement(trip_el, "stop")
                    stop_el.attrib['busStop'] = pt_veh_event['facility']
                    stop_el.attrib['until'] = str(pt_veh_event['time'])
                    stop_el.attrib['duration'] = str(5)
                if 'depart' not in trip_el.attrib:
                    trip_el.attrib['depart'] = str(pt_veh_event['time'])
            else:
                stop_el = etree.SubElement(trip_el, "stop")
                stop_el.attrib['busStop'] = pt_veh_event['facility']
                if len(pt_veh_events) == 1:
                    trip_el.attrib['depart'] = str(pt_veh_event['time'])
                stop_el.attrib['duration'] = str(5)
                if trip_el.findall('jump'):
                    print(pt_veh_id_us, 'jumped')
        # for k, v in connection.items():
        #     conn_el.attrib[k] = v
    pt_veh_routes_root[:] = sorted(
        pt_veh_routes_root,
        key=lambda child: float(child.attrib['depart']) if 'depart' in child.attrib else -1
    )
    pt_vehs_tree = pt_veh_routes_root.getroottree()
    return pt_vehs_tree


def convert_road_vehicles(
        road_vehicles: Dict[str, List[Dict[str, str]]],
        vehicles: Dict[str, str],
        vehicles_types: Dict[str, Dict[str, str]],
        use_coords: bool = False,
        links_start_end: Optional[Dict[str, List[Tuple[float, float]]]] = None
) -> lxml.etree.ElementTree:
    road_vehs_root = etree.Element("routes")
    for vehicle_type, vehicle_data in vehicles_types.items():
        if not vehicle_data['isPt']:
            vtype = etree.SubElement(road_vehs_root, "vType")
            vtype.attrib['id'] = vehicle_type
            for k, v in vehicle_data.items():
                if k != 'isPt':
                    vtype.attrib[k] = str(v)

    for road_veh_id, road_veh_trips in road_vehicles.items():
        road_veh_id_us = re.sub(r'\s+', '_', road_veh_id)
        for tnum, road_veh_trip in enumerate(road_veh_trips):
            if 'start_link' not in road_veh_trip:
                continue
            if 'end_link' not in road_veh_trip:
                road_veh_trip['end_link'] = road_veh_trip['last_link']
                assert road_veh_trip['last_link_allowed'] is True, f'Last link not allowed? {road_veh_id}'
            trip_el = etree.SubElement(road_vehs_root, "trip")
            trip_el.attrib['type'] = vehicles[road_veh_id]
            trip_el.attrib['id'] = f'{road_veh_id_us}_{tnum}'
            trip_el.attrib['depart'] = str(road_veh_trip['start_time'])
            if use_coords:
                trip_el.attrib['fromXY'] = ','.join(
                    str(c) for c in links_start_end[road_veh_trip['start_link']][0]
                )
                trip_el.attrib['toXY'] = ','.join(
                    str(c) for c in links_start_end[road_veh_trip['end_link']][-1]
                )
            else:
                trip_el.attrib['from'] = str(road_veh_trip['start_link'])
                trip_el.attrib['to'] = str(road_veh_trip['end_link'])

    road_vehs_root[:] = sorted(
        road_vehs_root,
        key=lambda child: float(child.attrib['depart']) if 'depart' in child.attrib else -1
    )
    road_vehs_tree = road_vehs_root.getroottree()
    return road_vehs_tree


def convert_persons(
        legs_path: Union[str, Path],
        net: gpd.GeoDataFrame,
        net_cut: gpd.GeoDataFrame,
        pt_vehicles: Dict[str, List[Dict[str, str]]],
        min_time: Union[float, int],
        max_time: Union[float, int],
        cut_polygon: Polygon,
        pt_stops_within: PtStops,
        lines_routes_stops: Dict[str, Dict[str, Dict[str, Union[List[str], str]]]],
        use_coords: bool = False,
        links_start_end: Optional[Dict[str, List[Tuple[float, float]]]] = None
) -> lxml.etree.ElementTree:
    allowed_links = set(net['link_id'].tolist())
    legs_df = pd.read_csv(
            legs_path,
            sep=';',
            decimal=',',
            converters={
                'person': str,
                'vehicle_id': str,
                'access_stop': str,
                'egress_stop': str,
                'start_link': str,
                'end_link': str,
                'mode': str,
                'transit_line': str,
                'transit_route': str,
                'dep_time': str2sec,
                'wait_time': str2sec,
                'trav_time': str2sec
            }
    )
    legs_df = legs_df[
        legs_df['mode'].isin(['pt', 'walk', 'bike']) &
        (legs_df['dep_time'] < max_time) &
        ((legs_df['dep_time'] + legs_df['trav_time']) > min_time)
    ]

    legs_df['start_geom'] = gpd.points_from_xy(x=legs_df['start_x'], y=legs_df['start_y'])
    legs_df['end_geom'] = gpd.points_from_xy(x=legs_df['end_x'], y=legs_df['end_y'])

    persons_root = etree.Element("routes")
    for trip_id, trip_df in legs_df.groupby('trip_id'):
        modes = trip_df['mode'].unique().tolist()
        if 'pt' in modes or 'walk' in modes:
            pre_person_legs = [[]]
            for lid, leg_row in trip_df.reset_index(drop=True).iterrows():
                if leg_row['dep_time'] > max_time:
                    break
                if leg_row['mode'] == 'walk':
                    person_leg = get_person_walk_leg(
                        leg_row=leg_row,
                        allowed_links=allowed_links,
                        net=net,
                        net_cut=net_cut,
                        cut_polygon=cut_polygon
                    )
                    # if person_leg is not None and (
                    #         person_leg['depart'] < min_time or
                    #         person_leg['depart'] > max_time
                    #     ):
                    #     continue
                elif leg_row['mode'] == 'pt':
                    if leg_row['vehicle_id'] not in pt_vehicles:
                        continue
                    person_leg = get_person_pt_leg(
                        leg_row=leg_row,
                        pt_stops_within=pt_stops_within,
                        lines_routes_stops=lines_routes_stops
                    )
                    if person_leg is not None and person_leg['depart'] == 'triggered' and pre_person_legs[-1]:
                        pre_person_legs.append([])
                else:
                    person_leg = None
                if person_leg is not None:
                    pre_person_legs[-1].append(person_leg)

            for j, pre_person_sublegs in enumerate(pre_person_legs):
                while (
                        len(pre_person_sublegs) > 0 and
                        pre_person_sublegs[0]['mode'] == 'pt' and
                        pre_person_sublegs[0]['busStop'] == 'DO_NOT_REMOVE'
                ):
                    pre_person_sublegs.pop(0)
                if pre_person_sublegs:
                    person_el = etree.SubElement(persons_root, "person")
                    person_el.attrib['id'] = trip_id + f'_{j}'
                    person_el.attrib['depart'] = str(pre_person_sublegs[0]['depart'])
                    for i, person_leg in enumerate(pre_person_sublegs):
                        if person_leg['mode'] == 'pt':
                            tag = 'ride'
                        elif person_leg['mode'] == 'walk':
                            tag = 'walk'
                        else:
                            raise ValueError(f"Unsupported mode {person_leg['mode']}")
                        leg_el = etree.SubElement(person_el, tag)
                        if i == 0 and person_leg['mode'] != 'pt':
                            if use_coords:
                                leg_el.attrib['fromXY'] = ','.join(
                                    str(c) for c in links_start_end[person_leg['from']][0]
                                )
                            else:
                                leg_el.attrib['from'] = person_leg['from']
                        if i != 0 and pre_person_sublegs[i - 1]['mode'] == 'walk' and person_leg['mode'] == 'pt':
                            last_walk_el = person_el.xpath('./walk')[-1]
                            if 'to' in last_walk_el.attrib:
                                del last_walk_el.attrib['to']
                            if 'toXY' in last_walk_el.attrib:
                                del last_walk_el.attrib['toXY']
                            last_walk_el.attrib['busStop'] = person_leg['fromBusStop']
                        if person_leg['mode'] == 'pt':
                            if i == 0:
                                person_el.attrib['depart'] = 'triggered'
                                leg_el.attrib['lines'] = person_leg['vehicle']
                            else:
                                leg_el.attrib['lines'] = person_leg['lines']
                            leg_el.attrib['busStop'] = person_leg['busStop']
                        if person_leg['mode'] == 'walk':
                            if use_coords:
                                leg_el.attrib['toXY'] = ','.join(
                                    str(c) for c in links_start_end[person_leg['to']][-1]
                                )
                            else:
                                leg_el.attrib['to'] = person_leg['to']

    persons_root[:] = sorted(
        persons_root,
        key=lambda child: str_to_float(child.attrib['depart']) if 'depart' in child.attrib else -1
    )
    persons_tree = persons_root.getroottree()
    return persons_tree


def str_to_float(
        string: str,
        if_failed: float = -1.0
) -> float:
    try:
        return float(string)
    except:
        return if_failed


def create_sumo_configuration(
        sumo_net_save_path: Union[str, Path],
        sumo_road_vehs_save_path: Union[str, Path],
        sumo_additionals_save_path: Optional[Union[str, Path]] = None,
        sumo_pt_vehs_save_path: Optional[Union[str, Path]] = None,
        sumo_persons_save_path: Optional[Union[str, Path]] = None,
        min_time: Union[int, float] = 25200,
        max_time: Union[int, float] = 28800,
        snapping_distance: Union[str, float] = 1000
) -> lxml.etree.ElementTree:
    sumocfg_root = etree.Element("configuration", nsmap={
        None: "http://example.com",
        'xsi': "http://www.w3.org/2001/XMLSchema-instance"
    })
    sumocfg_root.set(
        "{http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation",
        "http://sumo.dlr.de/xsd/sumoConfiguration.xsd"
    )

    input_el = etree.SubElement(sumocfg_root, 'input')
    netfile_el = etree.SubElement(input_el, 'net-file')
    netfile_el.attrib['value'] = str(sumo_net_save_path)
    roufiles_el = etree.SubElement(input_el, 'net-file')
    roufiles_el.attrib['value'] = ','.join([
        str(p) for p in [
            sumo_road_vehs_save_path,
            sumo_pt_vehs_save_path,
            sumo_persons_save_path
        ] if p is not None
    ])

    time_el = etree.SubElement(sumocfg_root, 'time')
    begin_el = etree.SubElement(input_el, 'begin')
    begin_el.attrib['value'] = str(min_time)

    processing_el = etree.SubElement(sumocfg_root, 'processing')
    mapmatch_distance_el = etree.SubElement(processing_el, 'mapmatch.distance')
    mapmatch_distance_el.attrib['value'] = str(snapping_distance)


def main(
        net_path: Union[str, Path],
        events_path: Union[str, Path],
        vehicles_path: Union[str, Path],
        sumo_net_save_path: Union[str, Path],
        sumo_road_vehs_save_path: Union[str, Path],
        sumo_additionals_save_path: Optional[Union[str, Path]] = None,
        sumo_pt_vehs_save_path: Optional[Union[str, Path]] = None,
        sumo_persons_save_path: Optional[Union[str, Path]] = None,
        crs: Optional[str] = None,
        min_time: Union[float, int] = 25200,
        max_time: Union[float, int] = 28800,
        legs_path: Optional[Union[str, Path]] = None,
        lanes_path: Optional[Union[str, Path]] = None,
        schedule_path: Optional[Union[str, Path]] = None,
        transit_vehicles_path: Optional[Union[str, Path]] = None,
        cut_polygon_path: Optional[Union[str, Path]] = None,
        ignore_link_modes_str: Optional[str] = 'artificial',
        use_coords: bool = True,
        sidewalk_width: Union[int, float] = 1.5
):
    net_path = r"output_network.xml.gz"
    lanes_path = r"output_lanes.xml.gz"
    legs_path = r"output_legs.csv.gz"

    events_path = r"output_events.xml.gz"
    schedule_path = r"output_transitSchedule.xml.gz"
    transit_vehicles_path = r"output_transitVehicles.xml.gz"
    vehicles_path = r"output_vehicles.xml.gz"
    cut_polygon_path = r"./shapes/shapes.shp"
    crs = 'epsg:5514'
    ignore_link_modes_str = 'artificial'

    min_time = 25200
    max_time = 28800
    use_coords = True
    sidewalk_width = 1.5

    if ignore_link_modes_str:
        ignore_link_modes = set(ignore_link_modes_str.split(','))
    else:
        ignore_link_modes = set()

    if cut_polygon_path:
        cut_polygon = gpd.read_file(cut_polygon_path).iloc[0].geometry
    else:
        cut_polygon = None

    net, nodes = load_network(
        path=net_path,
        include_nodes=True,
        crs=crs
    )
    if ignore_link_modes:
        remove_ignored_modes_links(
            net=net,
            ignore_link_modes=ignore_link_modes
        )
    net_cut = cut_net(
        net=net,
        cut_polygon=cut_polygon
    )
    nodes_cut = filter_nodes(
        nodes=nodes,
        net=net
    )

    consider_pt = (
        transit_vehicles_path and
        schedule_path and
        sumo_pt_vehs_save_path and
        sumo_additionals_save_path
    )
    if not consider_pt:
        warnings.warn(
            'PT vehicles and stops will not be considered, '
            'because one or more of the required paths was '
            'not set: transit_vehicles_path, '
            'schedule_path, sumo_pt_vehs_save_path, '
            'sumo_additionals_save_path'
        )
    else:
        pt_schedule = load_pt_schedule(path=schedule_path)
        pt_stops = get_transit_stops(pt_schedule=pt_schedule, include_geometries=True)
        if cut_polygon:
            pt_stops_within = {
                stop_id: stop_data for stop_id, stop_data in pt_stops.items()
                if stop_data['geometry'].within(cut_polygon)
            }
        else:
            pt_stops_within = pt_stops
        additional_tree = convert_stops(
            pt_stops=pt_stops,
            pt_stops_within=pt_stops_within,
            net_cut=net_cut,
            pt_schedule=pt_schedule
        )
        write_element_tree(additional_tree, './sumo/add.add.xml')
    if lanes_path:
        links_to_links = get_links_to_links(lanes_path=lanes_path)
        connections_tree = links_to_links_to_connections(links_to_links=links_to_links, net=net_cut)
        write_element_tree(connections_tree, './sumo/connections.con.xml')

    transit_vehicles_types = get_transit_vehicles_types(
        matsim_transit_vehicles_path=transit_vehicles_path
    )
    vehicles_types, vehicles = get_vehicle_types(
        matsim_vehicles_path=vehicles_path,
        transit_vehicles_types=transit_vehicles_types
    )

    edges_tree = convert_edges(net_cut=net_cut, sidewalk_width=sidewalk_width)
    nodes_tree = convert_nodes(nodes_cut=nodes_cut)

    write_element_tree(nodes_tree, './sumo/nodes.nod.xml')
    write_element_tree(edges_tree, './sumo/edges.edg.xml')

    links_start_end = {
        row['link_id']: [
            list(get_point(row.geometry, 0).coords)[0],
            list(get_point(row.geometry, -1).coords)[0]
        ] for i, row in net_cut.iterrows()
    }
    lines_routes_stops = extract_routes_stops(pt_schedule=pt_schedule)

    pt_vehicles, road_vehicles = process_events(
        events_path=events_path,
        net_cut=net_cut,
        pt_stops_within=pt_stops_within,
        min_time=min_time,
        max_time=max_time
    )
    road_vehs_tree = convert_road_vehicles(
        road_vehicles=road_vehicles,
        vehicles=vehicles,
        vehicles_types=vehicles_types,
        links_start_end=links_start_end
    )
    write_element_tree(road_vehs_tree, './sumo/road_vehs.rou.xml')
    if consider_pt:
        pt_vehs_tree = convert_pt_vehicles(
            pt_vehicles=pt_vehicles,
            vehicles=vehicles,
            vehicles_types=vehicles_types,
            lines_routes_stops=lines_routes_stops
        )
        write_element_tree(pt_vehs_tree, './sumo/pt_vehs.rou.xml')

    if legs_path and sumo_persons_save_path:
        persons_tree = convert_persons(
            legs_path=legs_path,
            net=net,
            net_cut=net_cut,
            pt_vehicles=pt_vehicles,
            min_time=min_time,
            max_time=max_time,
            cut_polygon=cut_polygon,
            pt_stops_within=pt_stops_within,
            lines_routes_stops=lines_routes_stops,
            use_coords=use_coords,
            links_start_end=links_start_end
        )
        write_element_tree(persons_tree, './sumo/persons.rou.xml')
    else:
        warnings.warn(
            'Persons will not be considered, '
            'because one or more of the required paths was '
            'not set: sumo_persons_save_path, legs_path'
        )

    # graph = momepy.gdf_to_nx(
    #     gdf_network=cut_matsim_net,
    #     directed=True,
    #     approach='primal'
    # )

    proj4_str = gpd.GeoDataFrame({'geometry': [None]}).set_crs(crs).crs.to_proj4()
    f'netconvert --node-files=nodes.nod.xml --edge-files=edges.edg.xml --connection-files=connections.con.xml --output-file=net.net.xml --offset.disable-normalization --crossings.guess=true --walkingareas=true'
    '--proj="{proj4_str}"'
