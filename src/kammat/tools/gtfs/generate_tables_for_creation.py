# -*- coding: utf-8 -*-
"""
Created on Thu Mar 14 13:05:50 2024

@author: dgrishchuk
"""
import pandas as pd
from pathlib import Path
from datetime import timedelta as td
from typing import Union, Optional, List
from kammat.tools.gtfs.io import load_gtfs

TIME_STEPS = [
    td(seconds=ts) for ts in range(0, 86400, 3600)
]


def main(
        gtfs_path: Union[str, Path],
        intervals_save_path: Union[str, Path],
        routes_save_path: Union[str, Path],
        keep_routes: Optional[List[str]] = None
):
    gtfs = load_gtfs(gtfs_path)

    if keep_routes:
        routes = gtfs['routes'][gtfs['routes']['route_id'].isin(keep_routes)].copy()
    else:
        routes = gtfs['routes'].copy()

    route_ids = routes['route_id'].tolist()
    trips = gtfs['trips'][gtfs['trips']['route_id'].isin(route_ids)].copy()
    stop_times = gtfs['stop_times'].sort_values('departure_time')
    intervals_rows = []
    routes_rows = []

    for rnum, rrow in routes.iterrows():
        route_id = rrow['route_id']
        route_name = rrow['route_short_name']
        route_trips = trips[trips['route_id'] == route_id]
        directions = route_trips['direction_id'].unique().tolist()
        for direction in directions:
            dirname = 'outbound' if direction == '0' else 'inbound'
            route_trips_dir = route_trips[route_trips['direction_id'] == direction]
            route_trips_dir_ids = route_trips_dir['trip_id'].unique().tolist()
            route_dir_stop_times = stop_times[
                stop_times['trip_id'].isin(route_trips_dir_ids)
            ]
            route_row = {
                'route_id': route_name,
                'direction': dirname,
                'is_circle': 'no' if len(directions) > 1 else 'yes',
                'start_time': str(
                    route_dir_stop_times['departure_time'].min()
                ).split(' days ')[-1],
                'end_time': str(
                    route_dir_stop_times[
                        (route_dir_stop_times['departure_time'] < td(1)) &
                        (route_dir_stop_times['stop_sequence'] == 1)
                    ]['arrival_time'].max()
                ).split(' days ')[-1]
            }
            routes_rows.append(route_row)
            for i, ts in enumerate(TIME_STEPS[:-1]):
                ts_next = TIME_STEPS[i + 1]
                ts_stimes = route_dir_stop_times[
                    (route_dir_stop_times['arrival_time'] >= ts) &
                    (route_dir_stop_times['arrival_time'] <= ts_next) &
                    (route_dir_stop_times['stop_sequence'] > 1)
                ]
                if len(ts_stimes) == 0:
                    continue

                maxstop = ts_stimes['stop_id'].value_counts().idxmax()
                stop_ts_stimes = ts_stimes[
                    ts_stimes['stop_id'] == maxstop
                ].drop_duplicates('arrival_time')
                interval = stop_ts_stimes['departure_time'].diff().median(skipna=True)
                if pd.isnull(interval):
                    interval = int(86399 / 60)
                else:
                    interval = int(interval.total_seconds() / 60)

                if intervals_rows:
                    samedir = intervals_rows[-1]['direction'] == dirname
                    sameroute = intervals_rows[-1]['route_id'] == route_name
                    sameint = interval == intervals_rows[-1]['interval']
                    if sameroute and samedir and sameint:
                        continue
                intervals_rows.append({
                    'route_id': route_name,
                    'direction': dirname,
                    'time': str(ts).split(' days ')[-1],
                    'interval': interval
                })

    intervals = pd.DataFrame(intervals_rows)
    routes_df = pd.DataFrame(routes_rows)

    if str(intervals_save_path).endswith('.xlsx'):
        intervals.to_excel(intervals_save_path, index=False)
    else:
        intervals.to_csv(intervals_save_path, index=False)

    if str(routes_save_path).endswith('.xlsx'):
        routes_df.to_excel(routes_save_path, index=False)
    else:
        routes_df.to_csv(routes_save_path, index=False)
