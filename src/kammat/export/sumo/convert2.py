import warnings
from collections import defaultdict
from email.policy import default
from pathlib import Path
from typing import Union, Dict, List, Set, Tuple, Optional, Sequence

import lxml.etree
import numpy as np
from lxml import etree
import matsim
import pandas as pd
import datetime
import re

from shapely import Point

from kammat.output.pt import load_pt_schedule, get_lines_routes_vehicles_profiles, get_transit_stops, PtStops
from kammat.output.road import load_network
import geopandas as gpd

from kammat.output.utils import defaultdict2dict


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
) -> Dict[str, List[str]]:
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
):
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
        net_cut: gpd.GeoDataFrame
) -> lxml.etree.ElementTree:
    edges = []
    allowed_modes_map = {}
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
            'allow': str_allowed_modes,
            'sidewalkWidth': str(1.5)
        }
        geom = list(erow['geometry'].coords)

        if len(geom) > 2:
            geom_str = ' '.join(
                f'{c[0]},{c[1]}' for c in geom
            )
            edge['shape'] = geom_str
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
    for stop_id, stop_data in pt_stops_within.items():
        closest_dists = net_cut.distance(stop_data['geometry'])
        closest_dist = closest_dists.min()
        closest_link = net_cut.loc[closest_dists.idxmin()]
        if closest_dist > 50:
            warnings.warn(
                f"Stop {stop_id} ({stop_data['name'] if 'name' in stop_data else None}) "
                f"is {closest_dist} m. away from the closest link {closest_link['link_id']}"
            )
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



def main():
    matsim_net_path = r"output_network.xml.gz"
    matsim_lanes_path = r"output_lanes.xml.gz"
    matsim_events_path = r"output_events.xml.gz"
    matsim_schedule_path = r"output_transitSchedule.xml.gz"
    matsim_transit_vehicles_path = r"output_transitVehicles.xml.gz"
    matsim_vehicles_path = r"output_vehicles.xml.gz"
    cut_polygon_path = r"../../../../../shapes/shapes.shp"
    matsim_crs = 'epsg:5514'
    ignore_link_modes_str = 'artificial'
    ignore_activities_str = 'pt interaction'

    ignore_link_modes = set(ignore_link_modes_str.split(','))
    ignore_activities = set(ignore_activities_str.split(','))

    matsim_net, matsim_nodes = load_network(
        path=matsim_net_path,
        include_nodes=True,
        crs=matsim_crs
    )
    cut_polygon = gpd.read_file(cut_polygon_path).iloc[0].geometry

    matsim_net_coords = matsim_net.geometry.apply(
        lambda x: [Point(c) for c in list(x.coords)]
    )
    suitable_links = matsim_net_coords.apply(
        lambda x: cut_polygon.contains(x[0]) or cut_polygon.contains(x[-1])
    )
    cut_matsim_net = matsim_net[suitable_links]

    if ignore_link_modes:
        ignored_links_within = set(
            cut_matsim_net[
                cut_matsim_net['modes'].str.split(',').apply(
                    lambda x: any(mode in x for mode in ignore_link_modes)
                )
            ]['link_id'].tolist()
        )
        # discard links that contain at least one mention of ignored modes
        cut_matsim_net = cut_matsim_net[
            ~cut_matsim_net['link_id'].isin(ignored_links_within)
        ]
    else:
        ignored_links_within = set()

    cut_matsim_nodes = matsim_nodes[
        matsim_nodes['node_id'].isin(cut_matsim_net['from_node'].unique()) |
        matsim_nodes['node_id'].isin(cut_matsim_net['to_node'].unique())
    ]

    net_cut = cut_matsim_net
    nodes_cut = cut_matsim_nodes

    pt_schedule = load_pt_schedule(path=matsim_schedule_path)
    pt_stops = get_transit_stops(pt_schedule=pt_schedule, include_geometries=True)

    lines_routes_stops = extract_routes_stops(pt_schedule=pt_schedule)

    pt_stops_within = {
        stop_id: stop_data for stop_id, stop_data in pt_stops.items()
        if stop_data['geometry'].within(cut_polygon)
    }

    links_to_links = get_links_to_links(lanes_path=matsim_lanes_path)
    connections_tree = links_to_links_to_connections(links_to_links=links_to_links, net=net_cut)
    transit_vehicles_types = get_transit_vehicles_types(
        matsim_transit_vehicles_path=matsim_transit_vehicles_path
    )
    vehicles_types, vehicles = get_vehicle_types(
        matsim_vehicles_path=matsim_vehicles_path,
        transit_vehicles_types=transit_vehicles_types
    )

    edges_tree = convert_edges(net_cut=net_cut)
    nodes_tree = convert_nodes(nodes_cut=nodes_cut)
    additional_tree = convert_stops(
        pt_stops=pt_stops,
        pt_stops_within=pt_stops_within,
        net_cut=net_cut,
        pt_schedule=pt_schedule
    )

    write_element_tree(connections_tree, './sumo/connections.con.xml')
    write_element_tree(nodes_tree, './sumo/nodes.nod.xml')
    write_element_tree(edges_tree, './sumo/edges.edg.xml')
    write_element_tree(additional_tree, './sumo/add.add.xml')

    write_element_tree(pt_vehs_tree, './sumo/pt_vehs.rou.xml')
    write_element_tree(road_vehs_tree, './sumo/road_vehs.rou.xml')

    # graph = momepy.gdf_to_nx(
    #     gdf_network=cut_matsim_net,
    #     directed=True,
    #     approach='primal'
    # )

    proj4_str = gpd.GeoDataFrame({'geometry': [None]}).set_crs(matsim_crs).crs.to_proj4()
    f'netconvert --node-files=nodes.nod.xml --edge-files=edges.edg.xml --connection-files=connections.con.xml --output-file=net.net.xml --crossings.guess=true --crossings.guess.speed-threshold=15.00 --walkingareas=true'
    '--proj="{proj4_str}"'

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


def process_events(
        events_path: Union[str, Path],
        net_cut: gpd.GeoDataFrame,
        pt_stops: PtStops,
        pt_stops_within: PtStops,
        min_time: Union[int, float],
        max_time: Union[int, float],
        ignore_activities: Optional[List[str]],
        vehicles_types: Dict[str, str],
        vehicles: Dict[str, str]
):
    min_time: Union[int, float] = 25200  # 25200
    max_time: Union[int, float] = 28800  # 28800

    allowed_links = set(net_cut['link_id'].tolist())
    allowed_facilities = set(
        s for s, sinfo in pt_stops.items()
        if sinfo['linkRefId'] in allowed_links
    )
    pt_vehicles = defaultdict(list)
    road_vehicles = defaultdict(list)

    events = matsim.event_reader(
        events_path,
    )
    for i, event in enumerate(events):
        if min_time <= event['time'] < max_time:
            if (
                event['type'] in ['VehicleArrivesAtFacility',
                                  'VehicleDepartsAtFacility']
                and event['facility'] in pt_stops_within
            ):
                is_pt = vehicles_types[
                    re.sub(r'\s+', '_', vehicles[event['vehicle']])
                ]['isPt']
                if is_pt:
                    pt_vehicles[event['vehicle']].append(event)
            elif event['type'] == 'entered link':
                is_pt = vehicles_types[
                    re.sub(r'\s+', '_', vehicles[event['vehicle']])
                ]['isPt']
                if is_pt:
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
                        road_vehicles[event['vehicle']][-1]['end_link'] = road_vehicles[event['vehicle']][-1]['last_link']
                        road_vehicles[event['vehicle']][-1]['last_link'] = event['link']
                        road_vehicles[event['vehicle']][-1]['last_link_allowed'] = False
                        road_vehicles[event['vehicle']].append({
                            'last_link': event['link'],
                            'last_link_allowed': False,
                        })
            elif event['type'] == '':  # !!!
                pass
        elif event['time'] >= max_time:
            break
        if i % 1000000 == 0:
            tm = int2time(event['time'])
            print(f'Event {i}, time {tm}')


    #####
    pt_veh_routes_root = etree.Element("routes")
    for vehicle_type, vehicle_data in vehicles_types.items():
        if vehicle_data['isPt']:
            vtype = etree.SubElement(pt_veh_routes_root, "vType")
            vtype.attrib['id'] = vehicle_type
            for k, v in vehicle_data.items():
                if k != 'isPt':
                    vtype.attrib[k] = str(v)

    for vnum, (pt_veh_id, pt_veh_events) in enumerate(pt_vehicles.items()):
        trip_el = etree.SubElement(pt_veh_routes_root, "trip")
        pt_veh_id_us = re.sub(r'\s+', '_', pt_veh_id)
        trip_el.attrib['id'] = f'{pt_veh_id_us}_{vnum}'
        trip_el.attrib['type'] = vehicles[pt_veh_id]
        for pt_veh_event in pt_veh_events:
            if pt_veh_event['type'] == 'VehicleDepartsAtFacility':
                children = trip_el.xpath('./*')
                if children and 'until' not in children[-1].attrib:
                    children[-1].attrib['until'] = str(pt_veh_event['time'])
                if 'depart' not in trip_el.attrib:
                    trip_el.attrib['depart'] = str(pt_veh_event['time'])
            else:
                conn_el = etree.SubElement(trip_el, "stop")
                conn_el.attrib['busStop'] = pt_veh_event['facility']
                conn_el.attrib['duration'] = str(5)
        # for k, v in connection.items():
        #     conn_el.attrib[k] = v
    pt_veh_routes_root[:] = sorted(
        pt_veh_routes_root,
        key=lambda child: float(child.attrib['depart']) if 'depart' in child.attrib else -1
    )
    pt_vehs_tree = pt_veh_routes_root.getroottree()

    #######
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
                assert road_veh_trip['last_link_allowed'] == True, 'Last link not allowed?'
            trip_el = etree.SubElement(road_vehs_root, "trip")

            trip_el.attrib['id'] = f'{road_veh_id_us}_{tnum}'
            trip_el.attrib['depart'] = str(road_veh_trip['start_time'])
            trip_el.attrib['from'] = str(road_veh_trip['start_link'])
            trip_el.attrib['to'] = str(road_veh_trip['end_link'])

    road_vehs_root[:] = sorted(
        road_vehs_root,
        key=lambda child: float(child.attrib['depart']) if 'depart' in child.attrib else -1
    )
    road_vehs_tree = road_vehs_root.getroottree()

            #
            # if 'vehicle' in event and 'person' in event:
            #     vehicles_persons[event['person']].append(event)
            # elif 'vehicle' in event:
            #     if 'link' in event and event['link'] not in allowed_links:
            #         continue
            #     # elif 'facility' in event and event['facility'] not in allowed_facilities:
            #     #     continue
            #     entities['vehicle'][event['vehicle']].append(event)
            # elif 'person' in event:
            #     if 'link' in event and event['link'] not in allowed_links:
            #         continue
            #     entities['person'][event['person']].append(event)
            #
            # if event['type'] == 'arrival':
            #     print(event)

        # if min_time <= event['time'] < max_time:
        #     if 'link' in event and event['link'] in allowed_links and 'veh' not in event['vehicle']:
        #         persons[event['vehicle']]['link'].append(event['link'])
        #         persons[event['vehicle']]['type'].append(event['type'])
        #         persons[event['vehicle']]['time'].append(event['time'])


