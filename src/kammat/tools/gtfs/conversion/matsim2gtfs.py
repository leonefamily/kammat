#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jun 11 12:48:34 2024

@author: leonefamily
"""

import sys
import copy
import lxml
import logging
import argparse
import pandas as pd
from lxml import etree
import geopandas as gpd
from pathlib import Path
from datetime import datetime as dt
from kammat.tools.gtfs.io import write_gtfs
from typing import List, Dict, Optional, Any, Union


def extract_stop_facility(
        el: lxml.etree._Element
) -> Dict[str, Any]:
    attribs = el.attrib
    sf = {
        'stop_id': attribs['id'],
        'stop_lon': attribs['x'],
        'stop_lat': attribs['y'],
        'parent_station': (
            attribs['stopAreaId'] if 'stopAreaId' in attribs else ''
        ),
        'stop_name': (
            attribs['name'] if 'name' in attribs else 'unnamed'
        ),
        'stop_desc': (
            attribs['linkRefId'] if 'linkRefId' in attribs else ''
        ),
        'location_type': 0
    }
    return sf


def extract_transit_route(
        el: lxml.etree._Element,
        stops_rows: List[Dict[str, Any]],
        last_trip_id: int = 0,
        service_id: str = '1',
        agency_id: str = 'MATSIM2GTFS'
):
    route_id = el.attrib['id']
    stop_times_els = el.xpath('.//stop')
    trips_els = el.xpath('.//departure')

    route_row = {
        'route_id': route_id,
        'agency_id': agency_id,
        'route_short_name': route_id,
        'route_long_name': route_id,
        'route_type': 3  # possibly specify
    }

    base_stop_times_rows = []
    stop_times_rows = []
    trips_rows = []

    last_i = len(stop_times_els) - 1
    for i, stime in enumerate(stop_times_els):
        stime_attrs = stime.attrib
        bst_row = {
            'arrival_time': (
                pd.to_timedelta(stime_attrs['arrivalOffset']) if i != 0 else
                pd.to_timedelta(stime_attrs['departureOffset'])
            ),
            'departure_time': (
                pd.to_timedelta(stime_attrs['arrivalOffset']) if i == last_i else
                pd.to_timedelta(stime_attrs['departureOffset'])
            ),
            'stop_id': stime_attrs['refId'],
            'stop_sequence': i + 1,
            'timepoint': 1 if stime_attrs['awaitDeparture'] == 'true' else 0
        }
        base_stop_times_rows.append(bst_row)

    for tripel in trips_els:
        trip_attrs = tripel.attrib
        headsign_id = base_stop_times_rows[-1]['stop_id']
        headsign = None
        starttime = pd.to_timedelta(trip_attrs['departureTime'])
        for s in stops_rows:
            if headsign_id == s['stop_id']:
                headsign = s['stop_name']
                break
        trip_row = {
            'trip_id': last_trip_id,
            'route_id': route_id,
            'service_id': service_id,
            'trip_headsign': headsign,
            'block_id': trip_attrs['vehicleRefId']
        }
        for bst_row in base_stop_times_rows:
            st_row = copy.deepcopy(bst_row)
            st_row['departure_time'] += starttime
            st_row['arrival_time'] += starttime
            st_row['trip_id'] = last_trip_id
            stop_times_rows.append(st_row)
        trips_rows.append(trip_row)
        last_trip_id += 1

    result = {
        'routes': [route_row],
        'trips': trips_rows,
        'stop_times': stop_times_rows,
        'last_trip_id': last_trip_id
    }
    return result


def get_crs(
        schedule: lxml.etree._ElementTree
) -> Optional[str]:
    crs_els = schedule.xpath(
        '//attribute[@name = "coordinateReferenceSystem"]'
    )
    if crs_els:
        return crs_els[0].text
    return None


def main(
        schedule_path: Union[str, Path],
        out_gtfs_path: Union[str, Path],
        service_id: str = '1',
        agency_id: str = 'MATSIM2GTFS'
):
    schedule = lxml.etree.parse(str(schedule_path))
    crs = get_crs(schedule=schedule)
    if crs:
        logging.info(f'Found CRS: {crs}')
    else:
        logging.info(
            f"Didn't find CRS in coordinateReferenceSystem attribute, "
            "GTFS will have the same coordinates as transitSchedule "
            "without translation to WGS84"
        )

    stops_rows = []
    trips_rows = []
    routes_rows = []
    stop_times_rows = []
    last_trip_id = 0

    for el in schedule.iter():
        if el.tag == 'stopFacility':
            stops_rows.append(extract_stop_facility(el))
        elif el.tag == 'transitRoute':
            troute_dict = extract_transit_route(
                el=el,
                stops_rows=stops_rows,
                last_trip_id=last_trip_id,
                service_id=service_id
            )
            trips_rows.extend(troute_dict['trips'])
            routes_rows.extend(troute_dict['routes'])
            stop_times_rows.extend(troute_dict['stop_times'])
            last_trip_id = troute_dict['last_trip_id']

    stops = pd.DataFrame(stops_rows)
    if crs:
        stops = gpd.GeoDataFrame(
            stops,
            geometry=gpd.points_from_xy(x=stops['stop_lon'], y=stops['stop_lat']),
            crs=crs
        )
        stops.to_crs('epsg:4326', inplace=True)
        stops['stop_lon'] = stops.geometry.x
        stops['stop_lat'] = stops.geometry.y
        stops.drop('geometry', axis=1, inplace=True)

    trips = pd.DataFrame(trips_rows)
    stop_times = pd.DataFrame(stop_times_rows)
    routes = pd.DataFrame(routes_rows)
    agency = pd.DataFrame([{
        'agency_id': agency_id,
        'agency_name': agency_id,
        'agency_url': 'https://www.matsim.org/',
        'agency_timezone': 'Europe/Berlin'
    }])

    day = dt.now().strftime('%Y%m%d')
    calendar = pd.DataFrame([{
        'service_id': service_id,
        'monday': 1,
        'tuesday': 1,
        'wednesday': 1,
        'thursday': 1,
        'friday': 1,
        'saturday': 1,
        'sunday': 1,
        'start_date': day,
        'end_date': day
    }])

    gtfs = {
        'agency': agency,
        'trips': trips,
        'routes': routes,
        'stop_times': stop_times,
        'stops': stops,
        'calendar': calendar
    }

    write_gtfs(
        gtfs=gtfs,
        output_directory_or_zip=out_gtfs_path
    )


def parse_args(
        args_from: Optional[List[str]] = None
) -> argparse.Namespace:
    if args_from is None:
        args_from = sys.argv[1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--schedule-path", required=True,
                        help="Where original transitSchedule.xml is located")
    parser.add_argument("-o", "--out-gtfs-path", required=True,
                        help="Where to save resulting GTFS data")
    parser.add_argument("-s", "--service-id", default='1',
                        help="Reproject from CRS (epsg:xxxx)")
    parser.add_argument("-a", "--agency-id", default='MATSIM2GTFS',
                        help="Reproject to CRS (epsg:xxxx)")
    args = parser.parse_args(args_from)
    return args


if __name__ == '__main__':
    args = parse_args()
    main(
        schedule_path=args.schedule_path,
        out_gtfs_path=args.out_gtfs_path,
        service_id=args.service_id,
        agency_id=args.agency_id,
)
