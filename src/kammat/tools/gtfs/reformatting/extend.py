import sys
import argparse
import pandas as pd
from pathlib import Path
from typing import Dict, Union, List
from datetime import timedelta as td
from kammat.tools.gtfs.io import (
    load_gtfs,
    write_gtfs
)


def prolong_service(
        gtfs: Dict[str, pd.DataFrame],
        until: float = 30.0
) -> Dict[str, pd.DataFrame]:
    timelimit = td(hours=until)
    stimes = gtfs['stop_times']

    addtrips = stimes[
            stimes['arrival_time'] <= (timelimit - td(1))
    ]['trip_id'].tolist()

    newstimes = stimes[
        stimes['trip_id'].isin(addtrips)
    ].copy()
    newstimes[['arrival_time', 'departure_time']] += td(1)
    newstimes.sort_values(['trip_id', 'stop_sequence'], inplace=True)
    newstimes['trip_id'] = newstimes['trip_id'].astype(str) + '_ext'
    gtfs['stop_times'] = stimes.append(newstimes)

    trips = gtfs['trips']
    newtrips = trips[trips['trip_id'].isin(addtrips)].copy()
    newtrips['trip_id'] = newtrips['trip_id'].astype(str) + '_ext'
    gtfs['trips'] = trips.append(newtrips)
    gtfs['trips'] = gtfs['trips'].astype({'trip_id': str})
    return gtfs


def extend_gtfs(
        gtfs_path: Union[str, Path],
        output_gtfs_path: Union[str, Path],
        until: Union[int, float]
):
    gtfs = load_gtfs(
        gtfs_path,
        only_busiest_day=False,
        remove_unused_stops=False,
        remove_unused_routes=False
    )
    prolong_service(
        gtfs=gtfs,
        until=until
    )
    write_gtfs(
        gtfs=gtfs,
        output_directory_or_zip=output_gtfs_path
    )


def parse_args(
        args_list: List[str] = None
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-g', '--gtfs-path', required=True)
    parser.add_argument('-o', '--output-gtfs-path', required=True)
    parser.add_argument('-u', '--until', required=True, type=float)
    args = parser.parse_args(sys.argv[1:] if args_list is None else args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    extend_gtfs(
        gtfs_path=args.gtfs_path,
        output_gtfs_path=args.output_gtfs_path,
        until=args.until
    )
