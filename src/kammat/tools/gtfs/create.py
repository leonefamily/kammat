# -*- coding: utf-8 -*-
"""
Created on Thu May 11 15:21:59 2023

@author: dgrishchuk
"""
import sys
import copy
import momepy
import zipfile
import logging
import difflib
import warnings
import argparse
import itertools
import numpy as np
import pandas as pd
import networkx as nx
import geopandas as gpd
from pathlib import Path
from datetime import timedelta
from pyproj import Transformer
from operator import itemgetter
from collections import Counter
from datetime import datetime as dt
from collections import defaultdict
from shapely.ops import linemerge, transform
from shapely.geometry import Point, LineString
from typing import Union, List, Dict, Optional, Literal, Tuple, Any

logging.basicConfig(
    format=(
        '%(asctime)s | '
        '%(levelname)s | '
        '%(name)s:%(module)s:%(lineno)d:%(funcName)s() - '
        '%(message)s'
        ),
    level=logging.INFO
)

SEG_TYPES = ['start', 'end', 'startend']
STOP_TIME_S = timedelta(seconds=15)  # seconds
TOLERANCE_M = 0.2  # meters
TELEPORTED_SPEED_KMH = 25
CRS = "EPSG:5514"
PLANAR = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
WGS = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
SERVICE_ID = 'GENERATED'
AGENCY_ID = 'GENERATED'

DIRECTIONS = {
    'inbound': 0,
    'outbound': 1
}

STOPS_COLUMNS = [
    'stop_id',
    'stop_code',
    'stop_name',
    'stop_desc',
    'stop_lat',
    'stop_lon',
    'zone_id',
    'stop_url',
    'location_type',
    'parent_station',
    'stop_timezone',
    'wheelchair_boarding',
    'level_id',
    'platform_code'
]

STOP_TIMES_COLUMNS = [
    'trip_id',
    'arrival_time',
    'departure_time',
    'stop_id',
    'stop_sequence',
    'stop_headsign',
    'pickup_type',
    'drop_off_type',
    'continuous_pickup',
    'continuous_drop_off',
    'shape_dist_traveled',
    'timepoint'
]

ROUTES_COLUMNS = [
    'route_id',
    'agency_id',
    'route_short_name',
    'route_long_name',
    'route_desc',
    'route_type',
    'route_url',
    'route_color',
    'route_text_color',
    'route_sort_order',
    'continuous_pickup',
    'continuous_drop_off'
]

SHAPES_COLUMNS = [
    'shape_id',
    'shape_pt_lat',
    'shape_pt_lon',
    'shape_pt_sequence',
    'shape_dist_traveled'
]

TRIPS_COLUMNS = [
    'route_id',
    'service_id',
    'trip_id',
    'trip_headsign',
    'trip_short_name',
    'direction_id',
    'block_id',
    'shape_id',
    'wheelchair_accessible',
    'bikes_allowed'
]

CALENDAR_COLUMNS = [
    'service_id',
    'monday',
    'tuesday',
    'wednesday',
    'thursday',
    'friday',
    'saturday',
    'sunday',
    'start_date',
    'end_date'
]

AGENCY_COLUMNS = [
    'agency_id',
    'agency_name',
    'agency_url',
    'agency_timezone',
    'agency_lang',
    'agency_phone',
    'agency_fare_url',
    'agency_email'
]

VEHICLE_TYPES = {
    0: 'tram',
    1: 'metro',
    2: 'rail',
    3: 'bus',
    800: 'trolleybus',
    5: 'cable_car'
}

VEHICLE_MODELS_CAPACITY = {
    'TRAM20': 147,
    'TRAM30': 187,
    'TRAM40': 293,
    'CABLE': 8,
    'TRAIN80': 600,
    'TRAIN100': 600,
    'BUS8': 50,
    'BUS12': 80,
    'BUS18': 120,
    'TBUS12': 80,
    'TBUS18': 120,
    'SBUS15': 80
}

DEFAULT_VEHICLE_TYPE_CAPACITY = {
    0: 187,
    1: 1000,
    2: 600,
    3: 100,
    800: 120,
    5: 8
}

DEFAULT_VEHICLE_CAPACITY = 100


class Stop:
    """Class containing stops data and useful methods to work with them."""

    def __init__(self,
                 stop_name: str,
                 stop_lat: float,
                 stop_lon: float,
                 stop_id: str = '',
                 zone_id: str = '',
                 stop_desc: str = '',
                 stop_code: Union[int, str] = '',
                 stop_url: str = '',
                 location_type: int = 0,
                 parent_station: str = '',
                 wheelchair_boarding: int = 0,
                 stop_timezone: str = '',
                 level_id: Union[int, str] = '',
                 platform_code: Union[int, str] = ''
                 ):
        self.stop_id = stop_id
        self.stop_name = stop_name
        self.stop_lat = float(stop_lat)
        self.stop_lon = float(stop_lon)
        self.stop_desc = stop_desc
        self.stop_code = stop_code
        self.stop_url = stop_url
        self.zone_id = zone_id
        self.location_type = int(location_type)
        self.stop_timezone = stop_timezone
        self.parent_station = parent_station
        self.wheelchair_boarding = int(wheelchair_boarding)
        self.level_id = level_id
        self.platform_code = platform_code
        self.geometry = Point(self.stop_lon, self.stop_lat)
        self.geometry_planar = transform(PLANAR.transform, self.geometry)
        self.stop_times = []

    def get_row(
            self,
            as_list: bool = False
            ) -> Union[str, List[Any]]:
        values = []
        for col in STOPS_COLUMNS:
            attr = getattr(self, col, '')
            if isinstance(attr, str) and ',' in attr and not as_list:
                attr = f'"{attr}"'
            values.append(attr if attr is not None else '')
        if as_list:
            return values
        return ','.join(str(v) for v in values)

    def __str__(self):
        return f'Stop {self.stop_id} ({self.stop_name})'

    def __repr__(self):
        return f'Stop {self.stop_id} ({self.stop_name})'


class StopsList(list):

    def assign_ids(
            self
            ):
        sorted_self = sorted(self, key=lambda stop: stop.stop_name)
        groups = itertools.groupby(
            sorted_self, key=lambda stop: stop.stop_name)
        [{'type': k, 'items': [x[0] for x in v]} for k, v in groups]

    def find_stop(
            self,
            stop_id: str
            ) -> Stop:
        for stop in self:
            if stop.stop_id == stop_id:
                return stop
        raise RuntimeError(
            f'No stop with id "{stop_id}" in the list'
            )

    def filter_by_distance(
            self,
            planar_geometry: Union[Point, LineString],
            thresh: float
            ):
        filtered = []
        for stop in self:
            if planar_geometry.distance(stop.geometry_planar) <= thresh:
                filtered.append(stop)
        return StopsList(filtered)


class Shape:

    def __init__(
            self,
            shape_num: int,
            route_id: str,
            direction: Literal['inbound', 'outbound'],
            speed: Union[int, float],
            geometry: LineString,
            stops_list: Optional[StopsList] = None,
            geom_is_planar: bool = False
            ):
        geom_list = list(geometry.coords)
        self.route_id = route_id
        self.direction = direction
        self.shape_num = shape_num
        self.shape_id = f'{route_id}_{direction}'
        self.speed = float(speed)
        self.start = Point(geom_list[0])
        self.start_planar = self.start if geom_is_planar else transform(PLANAR.transform, self.start)
        self.end = Point(geom_list[-1])
        self.end_planar = self.end if geom_is_planar else transform(PLANAR.transform, self.end)
        self.geometry = geometry
        self.geometry_planar = geometry if geom_is_planar else transform(PLANAR.transform, self.geometry)
        self.length = self.geometry_planar.length
        self.travel_time = timedelta(
            hours=self.length / 1000 / self.speed
            )
        self.start_stops = [
            s for s in stops_list if
            s.geometry_planar.distance(self.start_planar) <= TOLERANCE_M
            and s.parent_station is not None
            ] if stops_list is not None else []
        self.start_stop = None if not self.start_stops else self.start_stops[0]
        self.end_stops = [
            s for s in stops_list if
            s.geometry_planar.distance(self.end_planar) <= TOLERANCE_M
            and s.parent_station is not None
            ] if stops_list is not None else []
        self.end_stop = None if not self.end_stops else self.end_stops[0]

    def __str__(self):
        return (
            f'Shape ({self.start_stop.stop_name if self.start_stop else "?"} ->'
            f' {self.end_stop.stop_name if self.end_stop else "?"}, '
            f'{self.speed} km/h, {round(self.length)} m in '
            f'{td2str(self.travel_time)})'
        )

    def __repr__(self):
        return self.__str__()


class Route:

    def __init__(
            self,
            route_id: str,
            direction: Literal['inbound', 'outbound'],
            start_time: timedelta,
            end_time: timedelta,
            route_type: int = 3,  # bus
            is_circle: bool = False,
            spawn_points: int = 1,
            vehicle_model: str = 'vehicle',
            agency_id: str = AGENCY_ID,
            route_short_name: str = None,
            route_long_name: str = None,
            route_desc: str = None,
            route_url: str = '',
            route_color: str = '',
            route_text_color: str = '',
            continuous_pickup: int = 1,  # not allowed
            continuous_drop_off: int = 1,  # not allowed
            route_sort_order: int = 0,  # uniform
            shapes: Optional[List[Shape]] = None,
            intervals: Dict[timedelta, timedelta] = None,
            run: bool = True
            ):
        self.route_id = route_id
        self.direction = direction
        self.start_time = start_time
        self.end_time = end_time
        self.is_circle = is_circle
        self.spawn_points = spawn_points
        self.vehicle_model = vehicle_model
        self.agency_id = agency_id
        self.route_type = route_type
        self.route_short_name = route_short_name
        self.route_long_name = route_long_name
        self.route_desc = route_desc
        self.route_url = route_url
        self.shapes = shapes
        self.intervals = intervals
        self.trips = []
        if run:
            self.update()
            self.validate()
            self.ensure_stops_identity()

    def update(self):
        self.length = self.get_length()
        self.travel_time = self.get_travel_time()
        self.stopping_time = self.get_stopping_time()
        self.origin_name = self.get_origin_name()
        self.destination_name = self.get_destination_name()
        self.route_short_name = self.suggest_route_short_name()
        self.route_long_name = self.suggest_route_long_name()

    def validate(self):
        self.validate_intervals()

    def ensure_stops_identity(self):
        if self.shapes is not None and len(self.shapes) != 0:
            last_stop = self.shapes[0].start_stop
            for i, shape in enumerate(self.shapes):
                if i != 0:
                    if shape.start_stop is None:
                        raise RuntimeError(
                            f'Route {self.route_id} {self.direction} has no '
                            f'nearby stop after {last_stop} (at position {i}).'
                            'Every single link must connect two stops.'
                            )
                    if last_stop.stop_id != shape.start_stop.stop_id:
                        if last_stop.stop_id not in [s.stop_id for s in shape.start_stops]:
                            raise RuntimeError(
                                f'Route {self.route_id} {self.direction}: '
                                f'No common stop at the start of shape {shape}'
                                'and previous shape'
                                )
                        shape.start_stop = last_stop
                last_stop = shape.end_stop

    def validate_intervals(self):
        if self.intervals is None or not self.intervals:
            return
        mint = min(self.intervals)
        mst = self.start_time
        if mint > mst:
            raise ValueError(
                f'Start time is at {td2str(mst)}, '
                f'earliest interval starts at {td2str(mint)} '
                f'({self.route_id} {self.direction})'
                )

    def suggest_route_long_name(
            self
            ) -> str:
        if self.route_long_name is None:
            if self.shapes is not None:
                return f'{self.route_id} {self.shapes[0].start_stop} — {self.shapes[-1].end_stop}'        
            return self.route_id
        return self.route_long_name
    
    def suggest_route_short_name(
            self
            ) -> str:
        if self.route_short_name is None:
            return self.route_id
        return self.route_short_name

    def get_length(
            self
        ) -> Optional[float]:
        """Get route length in meters if shapes are provided, otherwise None."""
        if self.shapes is not None:
            return sum([shape.length for shape in self.shapes])

    def get_stops(
            self
        ) -> StopsList:
        if self.shapes is not None:
            route_stops = StopsList()
            for i, shape in enumerate(self.shapes):
                if i == 0:
                    route_stops.append(shape.start_stop)
                route_stops.append(shape.end_stop)
            return route_stops

    def get_stopping_time(
            self,
            drop_ms: bool = False
            ) -> Optional[timedelta]:
        """
        Get time spent at stops.

        Parameters
        ----------
        drop_ms : bool, optional
            Drop milliseconds? The default is False.

        Returns
        -------
        Optional[timedelta]
            None if self.shapes is None.

        """
        if self.shapes is not None:
            stopping_time = (len(self.shapes) + 1) * STOP_TIME_S
            if drop_ms:
                stopping_time = stopping_time - timedelta(
                    microseconds=stopping_time.microseconds
                    )
            return stopping_time

    def get_origin_name(
            self
            ) -> Optional[str]:
        if self.shapes is not None and len(self.shapes) > 0:
            return self.shapes[0].start_stop.stop_name

    def get_destination_name(
            self
            ) -> Optional[str]:
        if self.shapes is not None and len(self.shapes) > 0:
            return self.shapes[-1].end_stop.stop_name

    def get_travel_time(
            self,
            drop_ms: bool = False
            ) -> Optional[timedelta]:
        """
        Get travel time (without waiting at stops) of the route.

        Parameters
        ----------
        drop_ms : bool, optional
            Drop milliseconds? The default is False.

        Returns
        -------
        Optional[timedelta]
            None if self.shapes is None.

        """
        if self.shapes is not None:
            travel_time = sum(
                [shape.travel_time for shape in self.shapes], timedelta()
                )
            if drop_ms:
                travel_time = travel_time - timedelta(
                    microseconds=travel_time.microseconds
                    )
            return travel_time
        
    def concat_shapes(
            self,
            planar: bool = False
            ) -> Optional[LineString]:
        if self.shapes is not None:
            geoms = [shape.geometry_planar if planar else
                     shape.geometry for shape in self.shapes]
            return linemerge(geoms)

    def get_current_interval(
            self,
            current_time: timedelta
            ) -> timedelta:
        return self.intervals[self.get_current_timestep(current_time)]

    def get_current_timestep(
            self,
            current_time: timedelta
            ) -> timedelta:
        return max(filter(lambda x: x <= current_time, self.intervals))

    def get_next_timestep(
            self,
            current_time: timedelta
            ):
        tss = list(filter(lambda x: x > current_time, self.intervals))
        if not tss:
            return
        return min(filter(lambda x: x > current_time, self.intervals))

    def get_trips(
            self
            ) -> List[Dict[int, str]]:
        trips = []
        trip_num = 0
        trip_start = self.start_time

        while trip_start <= self.end_time:
            trip_id = f'{self.route_id}_{self.direction}_{trip_num}'
            current_time = trip_start
            shape_dist = 0
            stop_times = [
                StopTime(
                    trip_id=trip_id,
                    arrival_time=current_time - STOP_TIME_S,
                    departure_time=current_time,
                    stop=self.shapes[0].start_stop,
                    stop_sequence=1,
                    stop_headsign=self.shapes[-1].end_stop,
                    shape_dist_travelled=shape_dist
                    )
                ]

            for seq, shape in enumerate(self.shapes, 2):
                shape_dist += shape.length
                arrival_time = current_time + shape.travel_time
                departure_time = arrival_time + STOP_TIME_S
                stop_time = StopTime(
                    trip_id=trip_id,
                    arrival_time=arrival_time,
                    departure_time=departure_time,
                    stop=shape.end_stop,
                    stop_sequence=seq,
                    stop_headsign=self.shapes[-1].end_stop,
                    shape_dist_travelled=shape_dist
                    )
                stop_times.append(stop_time)
                current_time = departure_time

            trip = Trip(
                route=self,
                stop_times=stop_times,
                trip_id=trip_id,
                service_id=SERVICE_ID
                )
            trips.append(trip)
            curr_ts = self.get_current_timestep(trip_start)
            curr_interval = self.get_current_interval(trip_start)
            next_ts = self.get_next_timestep(trip_start)

            if (next_ts - curr_ts) < curr_interval:
                trip_start = next_ts
            else:
                trip_start += curr_interval
            trip_num += 1

        if self.spawn_points > 1:
            every_xth = int(np.ceil(len(self.shapes) / self.spawn_points))
            xth = every_xth

            while xth < len(self.shapes):
                trip_id = f'{self.route_id}_{self.direction}_{trip_num}'
                current_time = self.start_time
                shape_dist = 0
                stop_times = [
                    StopTime(
                        trip_id=trip_id,
                        arrival_time=current_time - STOP_TIME_S,
                        departure_time=current_time,
                        stop=self.shapes[xth].start_stop,
                        stop_sequence=1,
                        stop_headsign=self.shapes[-1].end_stop,
                        shape_dist_travelled=shape_dist
                        )
                    ]

                if len(self.shapes[xth]) < 2:
                    logging.warning(
                        f'Too many spawn points for {self.route_id} '
                        f'{self.direction}, skipping inserted trips'
                        )
                    break

                for seq, shape in enumerate(self.shapes[xth], 2):
                    shape_dist += shape.length
                    arrival_time = current_time + shape.travel_time
                    departure_time = arrival_time + STOP_TIME_S
                    stop_time = StopTime(
                        trip_id=trip_id,
                        arrival_time=arrival_time,
                        departure_time=departure_time,
                        stop=shape.end_stop,
                        stop_sequence=seq,
                        stop_headsign=self.shapes[-1].end_stop,
                        shape_dist_travelled=shape_dist
                        )
                    stop_times.append(stop_time)
                    current_time = departure_time

                trip = Trip(
                    route=self,
                    stop_times=stop_times,
                    trip_id=trip_id,
                    service_id=SERVICE_ID
                    )
                trips.append(trip)
                trip_num += 1
                xth += every_xth

        self.trips = trips
        return trips

    def get_shape(
            self,
            as_list: bool = False
            ) -> Union[str, List[List[Any]]]:
        shape_list = []
        cum_len = 0
        cum_order = 0
        prev_point = self.shapes[0].start_planar
        for shape in self.shapes:
            for pnum, (point, point_planar) in enumerate(zip(
                    list(Point(coords) for coords in list(shape.geometry.coords)),
                    list(Point(coords) for coords in list(shape.geometry_planar.coords))
                    )):
                pcoords = list(point.coords)[0]
                shape_name = f"{self.route_id}_{self.direction}"
                row = [
                    shape_name if as_list else '"' + shape_name + '"',
                    pcoords[1], pcoords[0],
                    cum_order, cum_len
                    ]
                if not as_list:
                    shape_list.append(','.join(str(v) for v in row))
                else:
                    shape_list.append(row)
                cum_len += prev_point.distance(point_planar)
                cum_order += 1
                prev_point = point_planar
        return shape_list

    def get_row(
            self,
            as_list: bool = False
            ):
        values = []
        for col in ROUTES_COLUMNS:
            attr = getattr(self, col, '')
            values.append(attr if attr is not None else '')
        if as_list:
            return values
        return ','.join(str(v) for v in values)

    def __repr__(
            self
            ) -> str:
        if self.shapes is None:
            return 'Route (no shapes)'
        return (
            'Route ('
            f'{self.route_id} '
            f'{self.get_origin_name()} -> '
            f'{self.get_destination_name()}, '
            f'{round(self.get_length() / 1000, 2)}km in '
            f'{td2str(self.get_travel_time() + self.get_stopping_time())}'
            ')'
            )

    def __hash__(
            self
            ) -> int:
        return hash((self.route_id) + (self.direction))


def td2str(
        tdo: timedelta
) -> str:
    """
    Convert timedelta object to a string in HH:MM:SS format.

    Parameters
    ----------
    tdo : td
        Timedelta object.

    Returns
    -------
    str

    """
    rmins, secs = divmod(tdo.total_seconds(), 60)
    hrs, mins = divmod(rmins, 60)
    h = f'{int(hrs)}'.zfill(2)
    m = f'{int(mins)}'.zfill(2)
    s = f'{round(secs)}'.zfill(2)
    return f'{h}:{m}:{s}'


class StopTime:

    def __init__(
            self,
            trip_id: str,
            arrival_time: timedelta,
            departure_time: timedelta,
            stop: Stop,
            stop_sequence: int,
            stop_headsign: str = '',
            pickup_type: int = 0,  # normal
            drop_off_type: int = 0,  # normal
            continuous_pickup: int = 1,  # not allowed
            continuous_drop_off: int = 1,  # not allowed
            shape_dist_travelled: Union[int, float] = None,  # km
            timepoint: int = 1  # exact
            ):
        self.trip_id = trip_id
        self.arrival_time = arrival_time
        self.departure_time = departure_time
        self.stop = stop
        self.stop_id = self.stop.stop_id
        self.stop_sequence = stop_sequence
        self.stop_headsign = stop_headsign
        self.pickup_type = pickup_type
        self.drop_off_type = drop_off_type
        self.continuous_pickup = continuous_pickup
        self.continuous_drop_off = continuous_drop_off
        self.shape_dist_travelled = shape_dist_travelled
        self.timepoint = timepoint

    def get_trip(
            self,
            trips  # List[Trip]
            ):  # trip
        for trip in trips:
            if trip.trip_id == self.trip_id:
                return trip
        raise AttributeError(f'No trip with ID {self.trip_id}')

    def get_row(
            self,
            as_list: bool = False
            ) -> Union[str, List[Any]]:
        values = []
        for col in STOP_TIMES_COLUMNS:
            attr = getattr(self, col, '')
            if isinstance(attr, timedelta):
                attr = td2str(attr)
            elif isinstance(attr, Stop):
                if col == 'stop_headsign':
                    attr = attr.stop_name
                else:
                    attr = attr.stop_id
            values.append(attr if attr is not None else '')
        if as_list:
            return values
        return ','.join(str(v) for v in values)

    def __repr__(self):
        return (
            f'StopTime trip_id {self.trip_id} (departure '
            f'{td2str(self.departure_time)} at {self.stop})'
            )


class Trip:

    def __init__(
            self,
            route: Route,
            stop_times: List[StopTime],
            trip_id: str = None,
            vehicle = None,
            service_id: str = SERVICE_ID,
            block_id: str = None,
            wheelchair_accessible: int = 1,
            bikes_allowed: int = 2
            ):
        self.route = route
        self.trip_id = trip_id
        self.route_id = route.route_id
        self.service_id = service_id
        self.vehicle = vehicle
        self.stop_times = stop_times
        self.block_id = block_id
        self.shape_id = f"{route.route_id}_{route.direction}"
        self.wheelchair_accessible = wheelchair_accessible
        self.bikes_allowed = bikes_allowed
        self.validate_stop_times()
        self.calculate_from_dependencies()

    def validate_stop_times(
            self
            ):
        if len(self.stop_times) < 2:
            raise ValueError('Stop times have to have 2 or more elements')
        # check order

    def get_row(
            self,
            as_list: bool = False
            ) -> Union[str, List[Any]]:
        values = []
        for col in TRIPS_COLUMNS:
            attr = getattr(self, col, '')
            if isinstance(attr, str) and ',' in attr and not as_list:
                attr = f'"{attr}"'
            values.append(attr if attr is not None else '')
        if as_list:
            return values
        return ','.join(str(v) for v in values)

    def __repr__(self):
        return (
            f'Trip {self.trip_id} (route {self.route_id} to '
            f'{self.trip_headsign} at {td2str(self.start_departure)})'
            )
    
    def calculate_from_dependencies(self):
        self.start_arrival = self.stop_times[0].arrival_time
        self.start_departure = self.stop_times[0].departure_time
        self.end_arrival = self.stop_times[-1].arrival_time
        self.end_departure = self.stop_times[-1].departure_time
        self.duration = self.end_arrival - self.start_departure
        self.trip_headsign = self.route.destination_name
        self.trip_short_name = (
            f'{self.route.origin_name} — '
            f'{self.route.destination_name} at '
            f'{self.start_departure}'
            )
        self.direction_id = int(self.route.direction == 'inbound')


class Vehicle:
    def __init__(
            self,
            id: Union[str, int],
            type: int,
            model: str,
            initial_stop: Stop,
            initial_time: timedelta,
            wheelchair_accessible: int = 1,
            ):
        self.id = id
        self.type = type
        self.model = model
        self.initial_stop = initial_stop
        self.current_stop = initial_stop
        self.current_time = initial_time
        self.wheelchair_accessible = wheelchair_accessible
        self.trips = []
        self.trip_num = 0

    def ride_trip(
            self,
            trip: Trip
            ):
        trip.vehicle = self
        trip.block_id = self.id
        self.trips.append(trip)
        self.current_stop = trip.stop_times[-1].stop
        self.trip_num = len(self.trips) + 1
        self.current_time = trip.end_departure

    def move_to_stop(
            self,
            destination: Stop,
            # graphs: Dict[int, nx.MultiDiGraph],
            delay: timedelta = timedelta(minutes=5),
            update_self: bool = False
    ) -> Trip:

        origin_coords = list(self.current_stop.geometry_planar.coords)[0]
        dest_coords = list(destination.geometry_planar.coords)[0]
        # mode_graph = graphs[self.type]
        # try:
        #     origin_node = [
        #         node for node in mode_graph.nodes if dist(
        #             node, origin_coords
        #         ) < TOLERANCE_M
        #     ][0]
        #     dest_node = [
        #         node for node in mode_graph.nodes if dist(
        #             node, dest_coords
        #         ) < TOLERANCE_M
        #     ][0]
        #     nodepath = nx.dijkstra_path(
        #         mode_graph, origin_node, dest_node, weight='cost'
        #     )
        #     edgepath = nx.utils.pairwise(nodepath)
        #     path = list(
        #         (u, v, min(mode_graph[u][v],
        #                    key=lambda k: mode_graph[u][v][k].get('cost', 1)))
        #         for u, v in edgepath
        #     )
        #     attrs = [mode_graph.get_edge_data(u, v, k) for u, v, k in path]
        #     geom = linemerge(a['geometry'] for a in attrs)
        #     speed = (geom.length / 1000) / (sum(a['cost'] for a in attrs) / 3600)
        #     shape = Shape(
        #         shape_num=1,
        #         route_id='MOVE',
        #         direction='outbound',
        #         speed=speed,
        #         geometry=geom,
        #         stops_list=StopsList([self.current_stop, destination]),
        #         geom_is_planar=True
        #         )
        # except (IndexError, nx.NetworkXNoPath):
        #     logging.warning(
        #         f'Vehicle {self.model} {self.id} cannot find origin '
        #         'or destination node, or there is no path. '
        #         'Using teleportation'
        #         )
        geom = LineString([self.current_stop.geometry_planar,
                           destination.geometry_planar])
        shape = Shape(
            shape_num=1,
            route_id='MOVE',
            direction='outbound',
            speed=TELEPORTED_SPEED_KMH,
            geometry=geom,
            stops_list=StopsList([self.current_stop, destination]),
            geom_is_planar=True
            )
        arrival_time = self.current_time + shape.travel_time + delay
        pseudo_route = Route(
            route_id='MOVE',
            direction='outbound',
            start_time=self.current_time,
            end_time=arrival_time,
            vehicle_model=self.model,
            route_type=self.type,
            shapes=[shape]
            )
        self.trip_num = len(self.trips) + 1
        trip_id = f'MOVE_{self.model}_{self.id}_{self.trip_num}'
        stop_times = [
            StopTime(
                trip_id=trip_id,
                arrival_time=self.current_time,
                departure_time=self.current_time,
                stop=self.current_stop,
                stop_headsign=destination,
                stop_sequence=1,
                shape_dist_travelled=0
            ),
            StopTime(
                trip_id=trip_id,
                arrival_time=arrival_time,
                departure_time=arrival_time,
                stop=destination,
                stop_headsign=destination,
                stop_sequence=2,
                shape_dist_travelled=shape.length
            )
            ]
        trip = Trip(
            route=pseudo_route,
            stop_times=stop_times,
            trip_id=trip_id,
            vehicle=self,
            wheelchair_accessible=self.wheelchair_accessible
            )
        self.trip_num += 1
        if update_self:
            self.trips.append(trip)
            self.current_stop = destination
            self.current_time = arrival_time
        return trip

    def __repr__(self):
        return (
            f'Vehicle {self.model} {self.id} (available from '
            f'{td2str(self.current_time)})'
            )


def load_lines_shape(
        lines_path: Union[str, Path]
        ) -> gpd.GeoDataFrame:
    lines_gdf = gpd.read_file(lines_path)
    return lines_gdf


def load_table(
        path: Union[str, Path]
) -> pd.DataFrame:
    if isinstance(path, Path):
        suff = path.suffix
    elif isinstance(path, str):
        suff = '.' + path.split('.')[-1]
    else:
        raise TypeError(f'Unsupported type: {type(path)}')

    if suff == '.xlsx':
        table = pd.read_excel(
            path,
            converters={'route_id': str}
        )
    elif suff == '.csv':
        table = pd.read_csv(
            path,
            sep=';',
            decimal=',',
            converters={'route_id': str}
        )
    else:
        raise TypeError(f'Unsupported suffix: {suff}')
    return table


def load_routes_info(
        routes_path: Union[str, Path]
        ) -> pd.DataFrame:
    routes_table = load_table(routes_path)
    routes_table['start_time'] = pd.to_timedelta(routes_table['start_time'])
    routes_table['end_time'] = pd.to_timedelta(routes_table['end_time'])
    routes_table['is_circle'] = routes_table['is_circle'].replace(
        {'yes': True, 'no': False}
        )
    return routes_table


def load_intervals_info(
        intervals_path: Union[str, Path]
        ) -> pd.DataFrame:
    intervals_table = load_table(intervals_path)
    intervals_table['time'] = pd.to_timedelta(intervals_table['time'])
    intervals_table['interval'] = pd.to_timedelta(
        intervals_table['interval'], unit='minute'
        )
    return intervals_table


def guess_full_column_names(
        stops_gdf: gpd.GeoDataFrame
        ):
    """
    Restore column names, that were longer than 10 symbols.

    Changes the original column names.

    Parameters
    ----------
    stops_gdf : gpd.GeoDataFrame
        A GTFS table from shapefile.

    """
    full_cnames = []
    for col in stops_gdf.columns:
        if col in STOPS_COLUMNS or col == 'geometry':
            full_cnames.append(col)
        else:
            possible_cnames = [
                scname for scname in STOPS_COLUMNS if scname.startswith(col)
                ]
            if not possible_cnames:
                raise KeyError(
                    f'Column "{col}" does not look like any GTFS stops column'
                    )
            guess = difflib.get_close_matches(col, possible_cnames, 1)[0]
            full_cnames.append(guess)
    stops_gdf.columns = full_cnames


def load_stops_shape(
        stops_path: Union[Path, str]
        ) -> gpd.GeoDataFrame:
    stops_gdf = gpd.read_file(stops_path)
    guess_full_column_names(stops_gdf)
    stops_gdf['stop_lon'] = stops_gdf.geometry.x
    stops_gdf['stop_lat'] = stops_gdf.geometry.y
    stops_gdf['location_type'] = stops_gdf['location_type'].fillna(0)
    dups = stops_gdf['stop_id'][stops_gdf['stop_id'].duplicated()].tolist()
    if len(dups):
        raise RuntimeError(f'These stop IDs are duplicated: {dups}')
    return stops_gdf


def get_stops_list(
        stops_gdf: gpd.GeoDataFrame
        ) -> StopsList:
    stops_list = StopsList()
    for i, row in stops_gdf.iterrows():
        params = row[[c for c in STOPS_COLUMNS if c in row.index]].to_dict()
        stop = Stop(**params)
        stops_list.append(stop)
    return stops_list


def get_ordered_shapes(
        starts: List[Tuple[float, float]],
        ends: List[Tuple[float, float]],
        route_gdf: gpd.GeoDataFrame,
        stops_list: StopsList,
        is_circle: bool = False
        ) -> List[Shape]:
    with warnings.catch_warnings():
        # remove warning about geographic CRS
        warnings.simplefilter('ignore', UserWarning)
        graph = momepy.gdf_to_nx(route_gdf, multigraph=False)

    if is_circle:
        ends_set = set(ends).intersection(starts)
        if not ends_set:
            raise RuntimeError('Circle route has different start/end stop')
        end = list(ends_set)[0]
        pseudo_start = [s for s in starts if s != end][0]
        try:
            start_part = list(
                nx.all_simple_edge_paths(graph, end, pseudo_start, cutoff=1)
                )[0][0]
        except IndexError:
            raise RuntimeError('Circle route is faulty')
        subgraph = copy.deepcopy(graph)
        subgraph.remove_edge(*start_part)
        paths = list(nx.all_simple_edge_paths(subgraph, pseudo_start, end))
        if not paths:
            all_paths = nx.single_source_shortest_path(subgraph, pseudo_start)
            farthest = max(all_paths, key=lambda x: len(all_paths[x]))
            raise RuntimeError(f'Path breakes at {farthest[::-1]}')
        paths = [[start_part] + path for path in paths]
    else:
        paths = []
        for start in starts:
            for end in ends:
                paths.extend(nx.all_simple_edge_paths(graph, start, end))
        if not paths:
            if not paths:
                all_paths = nx.single_source_shortest_path(graph, start)
                farthest = max(all_paths, key=lambda x: len(all_paths[x]))
                raise RuntimeError(f'Path breakes at {farthest[::-1]}')

    shapes = []
    max_path = max(paths, key=len)
    route_geom = linemerge(route_gdf.geometry.to_crs(CRS).tolist())
    stops_list_cropped = stops_list.filter_by_distance(route_geom, TOLERANCE_M)
    for num, edge in enumerate(max_path):
        attrs = graph.edges[edge]
        geom_list = list(attrs['geometry'].coords)
        if geom_list[0] != edge[0]:
            geom_list.reverse()
            attrs['geometry'] = LineString(geom_list)
        shape = Shape(
            shape_num=num,
            route_id=attrs['route_id'],
            direction=attrs['direction'],
            speed=attrs['speed'],
            geometry=attrs['geometry'],
            stops_list=stops_list_cropped
            )
        shapes.append(shape)

    return shapes


def get_routes(
        lines_gdf: gpd.GeoDataFrame,
        intervals_table: pd.DataFrame,
        routes_table: pd.DataFrame,
        stops_list: StopsList
        ) -> List[Route]:
    routes = []
    for (rid, dr), sub_gdf in lines_gdf.groupby(['route_id', 'direction']):
        logging.info(f'Processing line {rid} {dr}')
        gtypes = sub_gdf.geom_type
        if 'MultiLineString' in set(gtypes.tolist()):
            mlstrs = sub_gdf.loc[
                gtypes[gtypes == 'MultiLineString'].index, 'geometry'
            ].tolist()
            mlsgeoms = '; '.join([
                str([itemgetter(0, -1)(list(subg.coords)) for subg in list(g.geoms)])
                for g in mlstrs
            ])
            raise RuntimeError(
                'MultiLineStrings detected! Should be single segments:\n'
                f'{mlsgeoms}'
            )

        route_intervals_df = intervals_table[
            (intervals_table['route_id'] == rid) &
            (intervals_table['direction'] == dr)
        ].sort_values('time')[['time', 'interval']]
        route_intervals = dict(
            zip(route_intervals_df['time'], route_intervals_df['interval'])
        )
        if not route_intervals:
            raise ValueError(f'{rid} {dr} not in routes intervals table')
        try:
            route_info = routes_table[
                (routes_table['route_id'] == rid) &
                (routes_table['direction'] == dr)
            ].iloc[0]
        except IndexError:
            raise ValueError(f'{rid} {dr} not in route info table')

        start_shape_df = sub_gdf[sub_gdf['seg_type'] == 'start']
        end_shape_df = sub_gdf[sub_gdf['seg_type'] == 'end']
        if len(start_shape_df) != 1:
            raise RuntimeError(
                f'There must be exactly one start segment in every route direction ({rid} {dr})'
            )
        if len(end_shape_df) != 1:
            raise RuntimeError(
                f'There must be exactly one end segment in every route direction ({rid} {dr})'
            )
        start_shape = list(start_shape_df.iloc[0].geometry.coords)
        starts = start_shape[0], start_shape[-1]
        end_shape = list(end_shape_df.iloc[0].geometry.coords)
        ends = end_shape[0], end_shape[-1]
        shapes = get_ordered_shapes(
            starts,
            ends,
            sub_gdf,
            stops_list,
            is_circle=route_info['is_circle']
        )
        if not shapes:
            raise RuntimeError(
                f'Start and end segment are disconnected ({rid} {dr})'
            )

        route = Route(
            shapes=shapes,
            intervals=route_intervals,
            **route_info[
                [c for c in route_info.index
                 if c in ROUTES_COLUMNS
                 or c in ['direction', 'start_time', 'end_time', 'vehicle_model']]
            ].to_dict()
            )
        trips = route.get_trips()
        routes.append(route)
    return routes


def create_graph(
        routes: List[Route]
        ) -> Dict[int, nx.MultiDiGraph]:
    gdf_rows = []
    middle_shapes = []
    start_shapes = []
    end_shapes = []
    for route in routes:
        for num, shape in enumerate(route.shapes):
            row = {
                'route_id': route.route_id,
                'direction': route.direction,
                'route_type': route.route_type,
                'speed': shape.speed,
                # 'cost': shape.travel_time.total_seconds(),
                'geometry': shape.geometry_planar,
                }
            gdf_rows.append(row)
            if num == 0:
                start_shapes.append(shape)
            elif num < len(route.shapes) - 1:
                middle_shapes.append(shape)
            else:
                end_shapes.append(shape)

    for end_shape in end_shapes:
            start_candidates = [
                start_shape for start_shape in start_shapes if
                start_shape.route_id == end_shape.route_id and
                start_shape.direction != end_shape.direction and
                start_shape.start_stop != end_shape.end_stop and
                start_shape.start_planar.distance(end_shape.end_planar) < 500
            ]
            if start_candidates:
                route = [
                    route for route in routes if
                    route.route_id == end_shape.route_id and
                    route.direction == end_shape.direction
                ][0]
                start_shape = start_candidates[0]
                geom = LineString([
                    end_shape.end_planar,
                    start_shape.start_planar
                ])
                if geom.length > 500:
                    logging.warning(
                        'Distance between {start_shape.end_stop} and '
                        f'{end_shape.start_stop} is too large, skipping'
                    )
                    continue
                row = {
                    'route_id': 'MOVE',
                    'direction': end_shape.direction,
                    'route_type': route.route_type,
                    'speed': end_shape.speed,
                    # 'cost': geom.length / 1000 * end_shape.speed,
                    'geometry': geom
                    }
                gdf_rows.append(row)

    gdf = gpd.GeoDataFrame(gdf_rows, crs=CRS)
    graphs = {}
    for rtype, mode_gdf in gdf.groupby('route_type'):
        mode_gdf.drop_duplicates(
            ['speed', 'route_type', 'geometry'], inplace=True
            )
        unary_geom = mode_gdf.geometry.unary_union
        unary_gdf = gpd.GeoDataFrame(
            [{'id': n, 'geometry': g} for n, g in enumerate(unary_geom.geoms)],
            crs=CRS
            )
        graph_gdf = gpd.tools.sjoin(unary_gdf, mode_gdf)
        graph_gdf.drop_duplicates(
            ['route_id', 'direction', 'route_type', 'speed', 'geometry'],
            inplace=True
            )
        graph_gdf['cost'] = graph_gdf.length / 1000 / graph_gdf['speed'] * 3600
        mode_graph = momepy.gdf_to_nx(graph_gdf, directed=True)
        graphs[rtype] = mode_graph
    return graphs


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
            logging.info(f'Vehicles assigned to {trip_num + 1} trips: {trip}')
    return used_vehicles


def write_tables(
        routes: List[Route],
        trips: List[Trip],
        stops_list: StopsList,
        output_directory_or_zip: Union[str, Path]
):
    out_dir = Path(output_directory_or_zip)
    routes_rows = []
    shapes_rows = []
    for route in routes:
        routes_rows.append(
            route.get_row(as_list=True)
            )
        shapes_rows.extend(
            route.get_shape(as_list=True)
            )
    routes_df = pd.DataFrame(
        routes_rows, columns=ROUTES_COLUMNS
        ).drop_duplicates()

    shapes_df = pd.DataFrame(shapes_rows, columns=SHAPES_COLUMNS)

    stops_rows = []
    for stop in stops_list:
        stops_rows.append(
            stop.get_row(as_list=True)
            )
    stops_df = pd.DataFrame(stops_rows, columns=STOPS_COLUMNS)

    agency_df = pd.DataFrame(
        [{
            'agency_id': AGENCY_ID,
            'agency_name': AGENCY_ID,
            'agency_url': f'https://{AGENCY_ID.lower()}.com',
            'agency_lang': 'en',
            'agency_phone': '',
            'agency_fare_url': f'https://fare.{AGENCY_ID.lower()}.com',
            'agency_email': f'{AGENCY_ID.lower()}@example.com',
            'agency_timezone': 'Europe/Prague'
        }]
        )

    calendar_df = pd.DataFrame(
        [{
            'service_id': SERVICE_ID,
            'monday': 1,
            'tuesday': 1,
            'wednesday': 1,
            'thursday': 1,
            'friday': 1,
            'saturday': 1,
            'sunday': 1,
            'start_date': dt.now().replace(month=1, day=1).strftime('%Y%m%d'),
            'end_date': dt.now().replace(month=12, day=31).strftime('%Y%m%d')
        }]
        )

    trips_rows = []
    stop_times_rows = []
    for trip in trips:
        trips_rows.append(
            trip.get_row(as_list=True)
            )
        for stop_time in trip.stop_times:
            stop_times_rows.append(
                stop_time.get_row(as_list=True)
                )
    trips_df = pd.DataFrame(trips_rows, columns=TRIPS_COLUMNS)
    stop_times_df = pd.DataFrame(stop_times_rows, columns=STOP_TIMES_COLUMNS)

    gtfs_dict = {
        'agency': agency_df,
        'routes': routes_df,
        'shapes': shapes_df,
        'stops': stops_df,
        'calendar': calendar_df,
        'trips': trips_df,
        'stop_times': stop_times_df
        }

    if out_dir.exists() and out_dir.is_dir():
        for stem, table in gtfs_dict.items():
            table.to_csv(out_dir / (stem + '.txt'), index=False)
    elif out_dir.suffix == '.zip':
        with zipfile.ZipFile(
                file=out_dir,
                mode='w',
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=4
                ) as zobj:
            for stem, table in gtfs_dict.items():
                zobj.writestr(
                    stem + '.txt',
                    data=table.to_csv(index=False)
                    )


def get_used_vehicles_stats(
        vehicles: List[Vehicle],
        routes: List[Route],
        as_string: bool = False
) -> Union[str, Tuple[Dict[int, int], Dict[int, int]]]:
    stats = {
        t: 0 for t in set((veh.type, veh.model) for veh in vehicles)
        }
    for vehicle in vehicles:
        stats[(vehicle.type, vehicle.model)] += 1

    linestats = {
        route.route_id: defaultdict(int) for route in routes
    }
    for vehicle in vehicles:
        lasttrip = None
        for trip in vehicle.trips:
            # if trip.route_id == '1':
            #     raise
            if lasttrip is not None and lasttrip.route_id == trip.route_id:
                last_sec = lasttrip.end_departure + timedelta(seconds=1)
                curr_start = trip.start_arrival
                while last_sec < curr_start:
                    linestats[trip.route_id][last_sec] += 1
                    last_sec += timedelta(seconds=10)
            curr_sec = trip.start_arrival
            end_sec = trip.end_departure
            while curr_sec <= end_sec:
                linestats[trip.route_id][curr_sec] += 1
                curr_sec += timedelta(seconds=10)
            lasttrip = trip
    rstats = {}
    for rid, routed in linestats.items():
        maxkey = max(routed, key=routed.get)
        maxval = routed[maxkey]
        rstats[rid] = maxkey, maxval

    routes_stats = {
        route.route_id: 0 for route in routes
        }
    for route in routes:
        routes_stats[route.route_id] += len(route.trips)

    if as_string:
        str_vstats = 'Maximum vehicles on lines (time):\n'
        for rid, (mtime, mveh) in rstats.items():
            str_vstats += f'{rid} - {mveh} ({td2str(mtime)})\n'
        str_vstats += 'Vehicles required for the timetables:\n'
        for (vtype, vmodel), val in stats.items():
            str_vstats += f'{vmodel} - {val}\n'
        str_vstats += '\nTrips performed by routes:\n'
        for rname, val in routes_stats.items():
            str_vstats += f'{rname} - {val}\n'
        return str_vstats + '\n'

    return stats, routes_stats


def get_stops_timetables(
        trips: List[Trip],
        stops_list: StopsList = None
        ) -> Dict[Stop, List[StopTime]]:
    stop_timetable = defaultdict(list)
    for trip in trips:
        for stop_time in trip.stop_times:
            if stops_list is not None and stop_time.stop not in stops_list:
                continue
            stop_timetable[stop_time.stop].append(stop_time)

    sorted_stops_timetables = {
        s: list(sorted(tts, key=lambda x: x.departure_time))
        for s, tts in stop_timetable.items()
        }
    return sorted_stops_timetables


def enclose_route_name(
        route_name: str,
        max_width: int = 8,
        left_symbol: str = '<',
        right_symbol: str = '>'
        ) -> str:
    origl = len(route_name)
    if origl > max_width:
        new_rname = route_name[:max_width - 3] + '...'
    else:
        new_rname = route_name
    return left_symbol + new_rname + right_symbol


def get_timetables_overview(
        stops_timetables: Dict[Stop, List[StopTime]],
        trips: List[Trip],
        vehicles: List[Vehicle],
        routes: List[Route],
        stops_list: StopsList = None,
        entries_per_row: int = 5
) -> str:
    str_timetables = f'Schedule overview (created {dt.now()})\n'
    for stop, stop_times in stops_timetables.items():
        stop_timetable = '\n'
        if stops_list is not None and stop not in stops_list:
            continue
        for entryn, stop_time in enumerate(stop_times):
            if entryn % entries_per_row == 0 and entryn != 0:
                stop_timetable += '\n'
            elif entryn != 0:
                stop_timetable += ' '
            try:
                rt = stop_time.get_trip(trips).route
            except AttributeError:
                continue
            route_text = enclose_route_name(rt.route_id + '|' + rt.direction[0])
            stime = f'{td2str(stop_time.departure_time)} {route_text.ljust(10)}'
            stop_timetable += stime
        str_timetables += f'\n\n{stop}:\n{stop_timetable}'

    return str_timetables


def get_vehicles_count(
        route: Route,
        time_reserve: float = 5,
        travel_time_mean: bool = True
) -> tuple[int, Union[float, timedelta], int, float]:
    hr, deps = Counter(
        [round(int(tr.start_departure.total_seconds() / 3600)) for tr in route.trips]
    ).most_common(1)[0]
    ivl = 60 / deps
    sttime = route.get_stopping_time(True)
    trtime = route.get_travel_time(True)
    if not sttime or not trtime:
        if travel_time_mean:
            total_time = Counter([tr.duration for tr in route.trips]).most_common(1)[0][0]
        else:
            total_time = sum([tr.duration for tr in route.trips]) / len(route.trips)
    else:
        total_time = sttime + trtime    
    trfx = time_reserve + round(total_time.total_seconds()) / 60
    qv = int(2 * trfx / ivl + 1)
    return qv, total_time, deps, ivl


def estimate_total_vehicles_simple(
        routes: List[Route],
        travel_time_mean: bool = True
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    visited = set()
    vehmodels = defaultdict(int)
    routes_stats = []
    for route in routes:
        if route.route_short_name in visited:
            continue
        qv, total_time, deps, ivl = get_vehicles_count(
            route=route,
            travel_time_mean=travel_time_mean
        )
        vehmodels[route.vehicle_model] += qv
        routes_stats.append({
            'route': str(route.route_short_name),
            'travel_time': td2str(total_time),
            'max_hourly_departures': deps,
            'approximate_interval': td2str(timedelta(minutes=ivl)),
            'vehicle_type': route.vehicle_model,
            'vehicles_count': qv,
            'total_departures': len(route.trips) * 2
        })
        visited.add(route.route_short_name)
    routes_stats_df = pd.DataFrame(routes_stats).sort_values('route')
    add_vehhours(routes_stats_df)
    vehmodels_df = pd.DataFrame(
        vehmodels, index=pd.Index(['count'], name='model')
    ).transpose().reset_index().rename({'index': 'model'}, axis=1).sort_values('model')
    vehhours_df = routes_stats_df.groupby('vehicle_type').sum()['total_vehhours'].to_frame().reset_index().rename(
        {'vehicle_type': 'model'}, axis=1
    )
    vehmodels_df = vehmodels_df.merge(vehhours_df)
    return vehmodels_df, routes_stats_df


def estimate_total_vehicles(
        vehicles: List[Vehicle],
        routes: List[Route],
        travel_time_mean: bool = True
):
    vehmodels_rows = defaultdict(int)
    vehstats = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for vehicle in vehicles:
        for trip in vehicle.trips:
            trange = pd.timedelta_range(
                trip.start_arrival, trip.end_departure, freq='min'
            )
            for tm in trange:
                vehstats[trip.route.route_short_name][vehicle.model][tm] += 1
        vehmodels_rows[vehicle.model] += 1

    vehstats_rows = []
    for rt_nm, models_dict in vehstats.items():
        for veh_model, model_dict in models_dict.items():
            routes_pick = [r for r in routes if r.route_short_name == rt_nm]
            if not routes_pick:
                raise RuntimeError(f'Route {rt_nm} is not found while estimating vehicle counts')
            route = routes_pick[0]
            hr, deps = Counter(
                [round(int(tr.start_departure.total_seconds() / 3600)) for tr in route.trips]
            ).most_common(1)[0]
            ivl = 60 / deps
            sttime = route.get_stopping_time(True)
            trtime = route.get_travel_time(True)
            if not sttime or not trtime:
                if travel_time_mean:
                    total_time = Counter([tr.duration for tr in route.trips]).most_common(1)[0][0]
                else:
                    total_time = sum([tr.duration for tr in route.trips]) / len(route.trips)
            else:
                total_time = sttime + trtime
            maxtime = max(model_dict, key=model_dict.get)
            maxcnt = model_dict[maxtime]
            row = {
                'route': str(rt_nm),
                'travel_time': td2str(total_time),
                'max_hourly_departures': deps,
                'approximate_interval': td2str(timedelta(minutes=ivl)),
                'vehicle_type': veh_model,
                'vehicle_count': maxcnt,
                'total_departures': len(route.trips) * 2
            }
            vehstats_rows.append(row)
    vehstats_df = pd.DataFrame(vehstats_rows).sort_values('route')
    add_vehhours(vehstats_df)
    vehmodels_df = pd.DataFrame(
        vehmodels_rows, index=pd.Index(['count'])
    ).transpose().reset_index().rename({'index': 'model'}, axis=1).sort_values('model')
    vehhours_df = vehstats_df.groupby('vehicle_type').sum()['total_vehhours'].to_frame().reset_index().rename(
        {'vehicle_type': 'model'}, axis=1
    )
    vehmodels_df = vehmodels_df.merge(vehhours_df)
    return vehmodels_df, vehstats_df


def add_vehhours(
        vehstats_df: pd.DataFrame
):
    total_vehicle_hours = (
        pd.to_timedelta(vehstats_df['travel_time']).dt.total_seconds() / 60 / 60 *
        vehstats_df['total_departures']
    )
    vehstats_df['total_vehhours'] = total_vehicle_hours


def calculate_route_vehicle_stats(
        vehicles: List[Vehicle],
        routes: List[Route]
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    vehmodels_rows = defaultdict(int)
    vehkm_stats = defaultdict(
        lambda: {
            'departures_count': 0,
            'vehkm': 0.0,
            'vehhours': 0.0,
        }
    )
    for vehicle in vehicles:
        vehmodels_rows[vehicle.model] += 1
        for trip in vehicle.trips:
            rname = trip.route.route_short_name, trip.route.direction
            vehkm_stats[rname]['departures_count'] += 1
            vehkm_stats[rname]['vehhours'] += (
                trip.end_departure - trip.start_arrival
            ).total_seconds() / 3600
            triplen = trip.route.get_length()
            if triplen:
                vehkm_stats[rname]['vehkm'] += triplen / 1000               

    for route in routes:
        rname = route.route_short_name, route.direction
        hr, deps = Counter([
            round(int(tr.start_departure.total_seconds() / 3600))
            for tr in route.trips
        ]).most_common(1)[0]
        ivl = 60 / deps
        cap = (
            VEHICLE_MODELS_CAPACITY[route.vehicle_model]
            if route.vehicle_model in VEHICLE_MODELS_CAPACITY
            else DEFAULT_VEHICLE_CAPACITY
        )
        vehkm_stats[rname]['passengerkm'] = (
            vehkm_stats[rname]['vehkm'] * cap
        )
        vehkm_stats[rname]['passengerhours'] = (
            vehkm_stats[rname]['vehhours'] * cap
        )
        vehkm_stats[rname]['route'] = str(route.route_short_name)
        vehkm_stats[rname]['from_stop'] = route.origin_name
        vehkm_stats[rname]['to_stop'] = route.destination_name
        vehkm_stats[rname]['approximate_interval'] = td2str(
            timedelta(minutes=ivl)
        )
        vehkm_stats[rname]['vehicle_type'] = route.vehicle_model
        vehkm_stats[rname]['vehicle_capacity'] = cap

    vehstats_df = pd.DataFrame(vehkm_stats).transpose().sort_values('route').infer_objects()
    vehmodels_df = pd.DataFrame(
        vehmodels_rows, index=pd.Index(['count'])
    ).transpose().reset_index().rename({'index': 'model'}, axis=1).sort_values('model')
    vehhours_df = vehstats_df.groupby(
        'vehicle_type'
        ).sum()[
            ['vehhours', 'vehkm', 'passengerkm']
        ].reset_index().rename(
            {'vehicle_type': 'model'},
        axis=1
    )
    vehmodels_df = vehmodels_df.merge(vehhours_df)
    return vehmodels_df, vehstats_df


def create_gtfs(
        lines_path: Union[str, Path],
        stops_path: Union[str, Path],
        intervals_path: Union[str, Path],
        routes_path: Union[str, Path],
        output_directory_or_zip: Union[str, Path],
        output_svehs_path: Optional[Union[str, Path]] = None,
        output_vehs_path: Optional[Union[str, Path]] = None,
        output_svehs_lines_path: Optional[Union[str, Path]] = None,
        output_vehs_lines_path: Optional[Union[str, Path]] = None,
        human_readable_feed_path: Optional[Union[str, Path]] = None,
        remove_unused_stops: bool = False,
        vehicle_counts_path: Optional[Union[str, Path]] = None
):
    lines_gdf = load_lines_shape(lines_path)
    routes_table = load_routes_info(routes_path)
    intervals_table = load_intervals_info(intervals_path)
    stops_gdf = load_stops_shape(stops_path)
    stops_list = get_stops_list(stops_gdf)
    routes = get_routes(lines_gdf, intervals_table, routes_table, stops_list)    
    vehicles = assign_vehicles(routes)

    if output_vehs_path or output_vehs_lines_path:
        vehmodels_df, vehstats_df = calculate_route_vehicle_stats(vehicles, routes)
        if output_vehs_path:
            vehmodels_df.to_csv(
                output_vehs_path,
                sep=';',
                decimal=',',
                index=False,
                encoding='utf-8-sig'
            )
        if output_vehs_lines_path:
            vehstats_df.to_csv(
                output_vehs_lines_path,
                sep=';',
                decimal=',',
                index=False,
                encoding='utf-8-sig'
            )

    if output_svehs_path or output_svehs_lines_path:
        svehmodels_df, svehstats_df = estimate_total_vehicles_simple(routes)
        if output_svehs_path:
            svehmodels_df.to_csv(
                output_svehs_path,
                sep=';',
                decimal=',',
                index=False,
                encoding='utf-8-sig'
            )
        if output_svehs_lines_path:
            svehstats_df.to_csv(
                output_svehs_lines_path,
                sep=';',
                decimal=',',
                index=False,
                encoding='utf-8-sig'
            )

    trips = list(itertools.chain.from_iterable(veh.trips for veh in vehicles))
    stops_timetables = get_stops_timetables(trips)

    if human_readable_feed_path:
        str_timetables = get_timetables_overview(
            stops_timetables, trips, vehicles, routes
        )
        with open(human_readable_feed_path, mode='w', encoding='utf-8') as f:
            f.write(str_timetables)

    if vehicle_counts_path:
        str_vehicles = f'Vehicles overview (created {dt.now()})\n'
        str_vehicles += get_used_vehicles_stats(vehicles, routes, as_string=True)
        with open(vehicle_counts_path, mode='w', encoding='utf-8') as f:
            f.write(str_vehicles)

    if remove_unused_stops:
        stops_used = StopsList(stops_timetables.keys())
        for stop in stops_used:
            pstation_id = stop.parent_station
            if pstation_id is None:
                continue
            pstation = stops_list.find_stop(pstation_id)
            if pstation not in stops_used:
                stops_used.append(pstation)
    else:
        stops_used = stops_list

    write_tables(routes, trips, stops_used, output_directory_or_zip)


def parse_args(
        args_list: List[str] = None
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-l', '--lines-path', required=True)
    parser.add_argument('-s', '--stops-path', required=True)
    parser.add_argument('-i', '--intervals-path', required=True)
    parser.add_argument('-r', '--routes-path', required=True)
    parser.add_argument('-o', '--output-directory-or-zip', required=True)
    parser.add_argument('-v', '--output-vehs-path')
    parser.add_argument('-V', '--output-svehs-path')
    parser.add_argument('-m', '--output-vehs-lines-path')
    parser.add_argument('-M', '--output-svehs-lines-path')
    parser.add_argument('-R', '--human-readable-feed-path')
    parser.add_argument('-u', '--remove-unused-stops', action='store_true')
    parser.add_argument('-C', '--vehicle-counts-path')
    args = parser.parse_args(sys.argv[1:] if args_list is None else args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    create_gtfs(
        lines_path=args.lines_path,
        stops_path=args.stops_path,
        intervals_path=args.intervals_path,
        routes_path=args.routes_path,
        output_directory_or_zip=args.output_directory_or_zip,
        output_svehs_path=args.output_svehs_path,
        output_vehs_path=args.output_vehs_path,
        output_svehs_lines_path=args.output_svehs_lines_path,
        output_vehs_lines_path=args.output_vehs_lines_path,
        human_readable_feed_path=args.human_readable_feed_path,
        remove_unused_stops=args.remove_unused_stops,
        vehicle_counts_path=args.vehicle_counts_path
    )
