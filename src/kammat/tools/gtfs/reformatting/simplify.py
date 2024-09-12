import sys
import logging
import argparse
import numpy as np
import pandas as pd
from pathlib import Path
from typing import Union, List
from kammat.tools.gtfs.io import (
    load_gtfs,
    write_gtfs
)


def simplify_stops(
        stops: pd.DataFrame
) -> pd.DataFrame:
    simplified_rows = []
    for parent_id, platforms_df in stops.groupby('parent_station'):
        if not pd.isnull(parent_id):
            parent_row_candidates = stops[stops['stop_id'] == parent_id]
            lons = platforms_df['stop_lon'].tolist()
            lats = platforms_df['stop_lat'].tolist()
            if len(parent_row_candidates) == 0:
                logging.warning(
                    f'There is no parent station row for id {parent_id}. '
                    'The row will be created anyways.'
                )
                parent_row = platforms_df.iloc[0].copy()
                parent_row['stop_id'] = parent_id
                parent_row['location_type'] = 1
                parent_row['parent_station'] = np.nan
            elif len(parent_row_candidates) > 1:
                logging.warning(
                    f'There are more than 1 parent station row for id {parent_id}. '
                    'The first row will be picked.'
                )
                parent_row = parent_row_candidates.iloc[0].copy()
                lons += [parent_row['stop_lon']]
                lats += [parent_row['stop_lat']]
            else:
                parent_row = parent_row_candidates.iloc[0].copy()
                lons += [parent_row['stop_lon']]
                lats += [parent_row['stop_lat']]

            parent_row['stop_lat'] = np.mean(lats)
            parent_row['stop_lon'] = np.mean(lons)

            simplified_rows.append(parent_row)
    simplified_stops = pd.DataFrame(simplified_rows)
    return simplified_stops


def simplify_stop_times(
        stop_times: pd.DataFrame,
        stops: pd.DataFrame
) -> pd.DataFrame:
    simplified_stop_times = replace_stop_id(
        table=stop_times,
        stops=stops,
        on='stop_id'
    )
    return simplified_stop_times


def replace_stop_id(
        table: pd.DataFrame,
        stops: pd.DataFrame,
        on: str,
) -> pd.DataFrame:
    simplified_table = table.copy()
    simplified_table = simplified_table.merge(
        stops[['stop_id', 'parent_station']],
        how='left',
        left_on=on,
        right_on='stop_id'
    )
    simplified_table[on] = simplified_table['parent_station']
    to_drop = ['parent_station']
    if 'stop_id' not in table.columns:
        to_drop.append('stop_id')
    simplified_table.drop(to_drop, axis=1, inplace=True)
    return simplified_table


def simplify_transfers(
        transfers: pd.DataFrame,
        stops: pd.DataFrame
) -> pd.DataFrame:
    simplified_transfers = replace_stop_id(
        table=transfers,
        stops=stops,
        on='from_stop_id'
    )
    simplified_transfers = replace_stop_id(
        table=simplified_transfers,
        stops=stops,
        on='to_stop_id'
    )
    return simplified_transfers


def simplify_gtfs(
        gtfs_path: Union[str, Path],
        output_gtfs_path: Union[str, Path],
        only_busiest_day: bool = False,
        merge_stops: bool = False
):
    gtfs_out = load_gtfs(
        gtfs_path,
        only_busiest_day=only_busiest_day,
        remove_unused_stops=False,
        remove_unused_routes=False
    )
    if merge_stops:
        simpl_stops = simplify_stops(gtfs_out['stops'])
        simpl_stop_times = simplify_stop_times(
            stop_times=gtfs_out['stop_times'],
            stops=gtfs_out['stops']
        )
        if 'transfers' in gtfs_out:
            simpl_transfers = simplify_transfers(
                transfers=gtfs_out['transfers'],
                stops=gtfs_out['stops']
            )
            gtfs_out['transfers'] = simpl_transfers
        gtfs_out['stops'] = simpl_stops
        gtfs_out['stop_times'] = simpl_stop_times
    write_gtfs(
        gtfs=gtfs_out,
        output_directory_or_zip=output_gtfs_path
    )


def parse_args(
        args_list: List[str] = None
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-g', '--gtfs-path', required=True)
    parser.add_argument('-o', '--output-gtfs-path', required=True)
    parser.add_argument('-b', '--only-busiest-day', action='store_true')
    parser.add_argument('-s', '--merge-stops', action='store_true')
    args = parser.parse_args(sys.argv[1:] if args_list is None else args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    simplify_gtfs(
        gtfs_path=args.gtfs_path,
        output_gtfs_path=args.output_gtfs_path,
        only_busiest_day=args.only_busiest_day,
        merge_stops=args.merge_stops
    )
