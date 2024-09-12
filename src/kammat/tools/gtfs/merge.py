# -*- coding: utf-8 -*-
"""
Created on Tue Nov  7 11:02:48 2023

@author: dgrishchuk
"""

import sys
import argparse
import pandas as pd
from pathlib import Path
from typing import Union, Dict, List, Literal
from kammat.tools.gtfs.io import load_gtfs, write_gtfs


def prepend_string(
        string: str,
        col: str,
        df: pd.DataFrame
):
    df[col] = string + df[col]


def replace_entities(
        host_feed: Dict[str, pd.DataFrame],
        add_feed: Dict[str, pd.DataFrame],
        table_name: str,
        id_col: str
):
    add_entities = add_feed[table_name]
    overlap_entities = host_feed[table_name][
        host_feed[table_name][id_col].isin(
            add_entities[id_col].unique().tolist()
        )
    ]
    replace_entities = add_entities[
        add_entities[id_col].isin(overlap_entities[id_col].tolist())
    ]
    host_feed[table_name].drop(overlap_entities.index, inplace=True)
    host_feed[table_name] = pd.concat(
        [host_feed[table_name], replace_entities]
    ).reset_index(drop=True)


def add_unique_entities(
        host_feed: Dict[str, pd.DataFrame],
        add_feed: Dict[str, pd.DataFrame],
        table_name: str,
        id_col: str
):
    add_entities = add_feed[table_name][
        ~add_feed[table_name][id_col].isin(
             host_feed[table_name][id_col].unique().tolist()
        )
    ]
    host_feed[table_name] = pd.concat(
        [host_feed[table_name], add_entities]
    ).reset_index(drop=True)


def merge_gtfs(
        host_feed_path: Union[Path, str],
        add_feed_path: Union[Path, str],
        save_feed_path: Union[Path, str],
        replace_routes_by: Literal['route_short_name', 'route_id'] = 'route_short_name',
        remove_route_ids: List[str] = None,
        host_prefix: str = 'h_',
        add_prefix: str = 'a_'
):
    host_feed = load_gtfs(
        host_feed_path, id_prefix=host_prefix, only_busiest_day=True,
        remove_unused_stops=False, remove_unused_routes=False
    )
    add_feed = load_gtfs(
        add_feed_path, id_prefix=add_prefix, only_busiest_day=True,
        remove_unused_stops=False, remove_unused_routes=True
    )

    if remove_route_ids is not None:
        host_feed['routes'] = host_feed['routes'][
            ~host_feed['routes'][replace_routes_by].isin(remove_route_ids)
        ]
    replace_entities(host_feed, add_feed, 'stops', 'stop_id')
    add_unique_entities(host_feed, add_feed, 'stops', 'stop_id')

    replace_entities(host_feed, add_feed, 'routes', replace_routes_by)
    add_unique_entities(host_feed, add_feed, 'routes', replace_routes_by)

    host_feed['agency'] = pd.concat(
        [host_feed['agency'], add_feed['agency']]
    ).reset_index(drop=True)

    host_feed['calendar'] = pd.concat(
        [host_feed['calendar'], add_feed['calendar']]
    ).reset_index(drop=True)

    # remove trips not present in routes after manipulations
    host_feed['trips'] = host_feed['trips'][
        host_feed['trips']['alt_route_id'].isin(
            host_feed['routes']['alt_route_id'].unique().tolist()
        )
    ]
    host_feed['trips'] = pd.concat(
        [host_feed['trips'], add_feed['trips']]
    ).reset_index(drop=True)

    # remove stop times not associated with trips that are kept
    host_feed['stop_times'] = host_feed['stop_times'][
        host_feed['stop_times']['alt_trip_id'].isin(
            host_feed['trips']['alt_trip_id'].unique().tolist()
        )
    ]
    host_feed['stop_times'] = pd.concat(
        [host_feed['stop_times'], add_feed['stop_times']]
    ).reset_index(drop=True)

    host_feed['calendar'].loc[:, 'service_id'] = 'busiest'

    # create new calendar
    for table_name in host_feed:
        alt_orig_cols = [
            (c, c.replace('alt_', '')) for c in host_feed[table_name].columns
            if c.startswith('alt_')
        ]
        for alt, orig in alt_orig_cols:
            if orig != 'stop_id':
                host_feed[table_name][orig] = host_feed[table_name][alt]
            host_feed[table_name].drop(alt, axis=1, inplace=True)

    # we don't need it for a single day
    if 'calendar_dates' in host_feed:
        del host_feed['calendar_dates']
    # transfers will not be necessary
    if 'transfers' in host_feed:
        del host_feed['transfers']

    host_feed['calendar'] = host_feed['calendar'].loc[
        [host_feed['calendar']['end_date'].idxmax()]
    ]
    host_feed['trips']['service_id'] = host_feed['calendar']['service_id'].iloc[0]

    write_gtfs(host_feed, save_feed_path)


def parse_args(
        args_list: List[str] = None
) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--host-feed-path', required=True)
    parser.add_argument('-a', '--add-feed-path', required=True)
    parser.add_argument('-s', '--save-feed-path', required=True)
    parser.add_argument(
        '-r', '--replace-routes-by',
        help=(
            'Replace routes from host feed by '
            '`route_short_name` or `route_id`, '
            'if there are any identical in the added feed.'
            'Added feed replaces those instances in host routes'
        ),
        default='route_short_name'
    )
    parser.add_argument(
        '-R', '--remove-route-ids',
        help=(
            'Remove specified routes from host feed. '
            'Column that is used for search is `replace-routes-by`. '
            'Separate multiple IDs by semicolon (;)'
        )
    )
    parser.add_argument('-F', '--host-prefix', default='h_')
    parser.add_argument('-A', '--add-prefix', default='a_')
    args = parser.parse_args(sys.argv[1:] if args_list is None else args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    merge_gtfs(
        host_feed_path=args.host_feed_path,
        add_feed_path=args.add_feed_path,
        save_feed_path=args.save_feed_path,
        replace_routes_by=args.replace_routes_by,
        remove_route_ids=args.remove_route_ids,
        host_prefix=args.host_prefix,
        add_prefix=args.add_prefix
    )
