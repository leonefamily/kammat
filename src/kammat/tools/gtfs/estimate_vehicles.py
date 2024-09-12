# -*- coding: utf-8 -*-
"""
Created on Mon Feb 26 13:41:34 2024

@author: dgrishchuk
"""

from kammat.tools.gtfs.io import load_gtfs
from kammat.tools.gtfs.create import (
    Vehicle, Trip, Route, StopsList, Stop, Shape, PLANAR, transform, StopTime,
    get_stops_timetables, get_timetables_overview, estimate_total_vehicles,
    estimate_total_vehicles_simple
)
from typing import List, Optional, Union
from datetime import timedelta
import geopandas as gpd
from shapely.geometry import LineString
import itertools
from pathlib import Path


def pick_vehicle(
        used_vehicles: List[Vehicle],
        trip: Trip,
        # graphs: Dict[int, nx.MultiDiGraph]
        ) -> Optional[Vehicle]:
    candidates = []
    for used_vehicle in used_vehicles:
        if (used_vehicle.type != trip.route.route_type or
                used_vehicle.model != trip.route.vehicle_model or
                    used_vehicle.current_time > trip.start_arrival):
            continue
        pseudo_trip = used_vehicle.move_to_stop(
            destination=trip.stop_times[0].stop,
            # graphs=graphs,
            delay=timedelta(minutes=5)
            )
        if pseudo_trip.end_departure <= trip.start_arrival:
            candidates.append({'vehicle': used_vehicle, 'trip': pseudo_trip})
    if candidates:
        return min(candidates, key=lambda x: x['trip'].duration)['vehicle']


def assign_vehicles(
        routes: List[Route],
        stock: List[Vehicle] = None
        ) -> List[Vehicle]:
    all_trips = []
    used_vehicles = []
    for route in routes:
        all_trips.extend(route.trips)
    all_trips.sort(key=lambda x: x.end_departure)
    next_id = 1000

    for trip_num, trip in enumerate(all_trips):
        vehicle = pick_vehicle(
            used_vehicles=used_vehicles,
            trip=trip
            )
        if vehicle is None:
            vehicle = Vehicle(
                id=next_id,
                type=trip.route.route_type,
                model=trip.route.vehicle_model,
                initial_stop=trip.stop_times[0].stop,
                initial_time=trip.start_arrival
                )
            next_id += 1
            used_vehicles.append(vehicle)
        vehicle.ride_trip(trip)
        if trip_num % 100 == 0 and trip_num != 0:
            print(f'Vehicles assigned to {trip_num + 1} trips: {trip}')
    return used_vehicles


def get_stops_list(
        stops_df: gpd.GeoDataFrame
        ) -> StopsList:
    stops_list = StopsList()
    stops_df['geometry'] = gpd.points_from_xy(stops_df['stop_lon'], stops_df['stop_lat'], crs='epsg:4326')
    stops_gdf = gpd.GeoDataFrame(stops_df)
    for i, row in stops_gdf.iterrows():
        params = row.drop(['geometry']).to_dict()
        stop = Stop(**params)
        stops_list.append(stop)
    return stops_list


def get_shape_bw_stops(
        sid1: str,
        sid2: str,
        stops_list: StopsList,
        shape_num: int,
        route_id: str,
        direction: str,
        deptime1: timedelta = None,
        arrtime2: timedelta = None
) -> LineString:
    s1 = stops_list.find_stop(sid1)
    s2 = stops_list.find_stop(sid2)
    geom = LineString([s1.geometry, s2.geometry])
    plgeom = transform(PLANAR.transform, geom)
    timediff = (arrtime2 - deptime1).total_seconds()
    if timediff == 0:
        speed = float('inf')
    else:
        speed = plgeom.length / timediff * 3.6
    shape = Shape(
        shape_num=shape_num, route_id=route_id, direction=direction,
        speed=speed, geometry=plgeom, stops_list=StopsList([s1, s2]), geom_is_planar=True
    )
    return shape


# def find_shape(
#         sid1: str,
#         sid2: str,
#         shapes_cache: dict,
#         stops_list: StopsList
# ) -> Shape:
#     in1 = sid1 in shapes_cache
#     in2 = sid2 in shapes_cache[sid1] if in1 else False
#     if not in1 or not in2:
#         shapes_cache[sid1][sid2] = get_shape_bw_stops(sid1, sid2, stops_list)
#     return shapes_cache[sid1][sid2]


def main(
        gtfs_path: Union[str, Path],
        output_stats_directories: Union[str, Path],
        human_readable_feed_path: Optional[Union[str, Path]] = None
):
    gtfs = load_gtfs(path=gtfs_path)

    stops_list = get_stops_list(gtfs['stops'])

    gtfs['routes'].drop(
        gtfs['routes'][
            gtfs['routes']['vehicle_type'].isna()
        ].index,
        inplace=True
    )

    gtfs['trips'].drop(
        gtfs['trips'][
            ~gtfs['trips']['route_id'].isin(gtfs['routes']['route_id'].unique())
        ].index,
        inplace=True
    )

    gtfs['stop_times'].drop(
        gtfs['stop_times'][
            ~gtfs['stop_times']['trip_id'].isin(gtfs['trips']['trip_id'].unique())
        ].index,
        inplace=True
    )

    routes = []
    # shapes_cache = defaultdict(dict)
    shapeid = 0

    for i, row in gtfs['routes'].iterrows():
        rid = row['route_id']

        for dir_id in ['0', '1']:

            direction = 'inbound' if dir_id == '1' else 'outbound'
            trips_df = gtfs['trips'][
                (gtfs['trips']['route_id'] == rid) &
                (gtfs['trips']['direction_id'] == dir_id)
            ].reset_index(drop=True)

            if len(trips_df) == 0:
                continue

            route = Route(
                route_id=rid,
                direction=direction,
                start_time=None, end_time=None,
                route_type=row['route_type'], vehicle_model=row['vehicle_type'],
                route_short_name=row['route_short_name'],
                route_long_name=row['route_long_name'],
                run=False
            )

            for j, trow in trips_df.iloc[1:].iterrows():

                headsign = trow['trip_headsign']
                tid = trow['trip_id']
                stimes = gtfs['stop_times'][gtfs['stop_times']['trip_id'] == tid].reset_index(drop=True)

                route.destination_name = headsign

                lstrow = None
                lastk = len(stimes) - 1
                stime_objs = []

                for k, strow in stimes.iterrows():
                    stop = stops_list.find_stop(strow['stop_id'])
                    stime_obj = StopTime(
                        trip_id=tid,
                        arrival_time=strow['arrival_time'] if k != 0 else strow['departure_time'],
                        departure_time=strow['departure_time'] if k < lastk else strow['arrival_time'],
                        stop=stop,
                        stop_sequence=strow['stop_sequence'],
                        stop_headsign=headsign,
                        shape_dist_travelled=0
                    )
                    if k == 0:
                        route.origin_name = stop.stop_name
                    stime_objs.append(stime_obj)
                    # if lstrow is not None:
                    #     shape = get_shape_bw_stops(
                    #         deptime1=lstrow['departure_time'],
                    #         arrtime2=strow['arrival_time'],
                    #         stops_list=stops_list,
                    #         shape_num=shapeid,
                    #         route_id=rid,
                    #         direction=direction,
                    #         sid1=lstrow['stop_id'],
                    #         sid2=strow['stop_id']
                    #     )
                    #     shapeid += 1
                    if k < lastk:
                        lstrow = strow.copy()

                trip = Trip(
                    route=route,
                    stop_times=stime_objs,
                    trip_id=tid,
                    service_id='random'
                )
                route.trips.append(trip)

            nodup_trips = []

            routes.append(route)

    used_vehicles = assign_vehicles(routes)

    basepath = Path(output_stats_directories)

    output_svehs_path = basepath / 'svehs.csv'
    output_vehs_path = basepath / 'vehs.csv'
    output_svehs_lines_path = basepath / 'svehs_lines.csv'
    output_vehs_lines_path = basepath / 'vehs_lines.csv'

    vehmodels_df, vehstats_df = estimate_total_vehicles(used_vehicles, routes)
    svehmodels_df, svehstats_df = estimate_total_vehicles_simple(routes)

    vehmodels_df.to_csv(output_vehs_path, sep=';', decimal=',', index=False)
    vehstats_df.to_csv(output_vehs_lines_path, sep=';', decimal=',', index=False)
    svehmodels_df.to_csv(output_svehs_path, sep=';', decimal=',', index=False)
    svehstats_df.to_csv(output_svehs_lines_path, sep=';', decimal=',', index=False)

    trips = list(itertools.chain.from_iterable(veh.trips for veh in used_vehicles))
    stops_timetables = get_stops_timetables(trips)
    str_timetables = get_timetables_overview(stops_timetables, trips, used_vehicles, routes)

    if human_readable_feed_path:
        with open(human_readable_feed_path, mode='w', encoding='utf-8') as f:
            f.write(str_timetables)
