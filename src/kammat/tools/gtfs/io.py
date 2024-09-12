# -*- coding: utf-8 -*-
"""
Created on Tue Nov  7 15:20:07 2023

@author: dgrishchuk
"""

import zipfile
import pandas as pd
from pathlib import Path
from typing import Union, Dict, List, Tuple, Optional, Literal
from collections import defaultdict
from datetime import datetime as dt, timedelta as td

NAMES = [
    'agency', 'stops', 'routes', 'trips', 'stop_times', 'calendar',
    'calendar_dates', 'fare_attributes', 'fare_rules', 'shapes',
    'frequencies', 'transfers', 'pathways', 'levels', 'feed_info',
    'translations', 'attributions'
]
REQ_NAMES = [
    'agency', 'stops', 'routes', 'trips', 'stop_times', 'calendar'
]
WORKDAYS = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']
WEEKEND = ['saturday', 'sunday']
DAYS = WORKDAYS + WEEKEND


def dttm(
        val: str
) -> dt:
    """Datetime from YYYYMMDD string"""
    return dt.strptime(val, '%Y%m%d')


def tdlt(
        val: str
) -> td:
    """Timedelta from HH:MM:SS string"""
    h, m, s = [int(el) for el in val.split(':')]
    return td(hours=h, minutes=m, seconds=s)


def enum(
        val: str
) -> Optional[int]:
    """Try to make string an integer or return None if failed"""
    try:
        return int(val)
    except ValueError:
        return


def flt(
        val: str
):
    try:
        return float(val)
    except ValueError:
        return


def td2str(
        tdo: td
) -> str:
    rmins, secs = divmod(tdo.total_seconds(), 60)
    hrs, mins = divmod(rmins, 60)
    h = f'{int(hrs)}'.zfill(2)
    m = f'{int(mins)}'.zfill(2)
    s = f'{round(secs)}'.zfill(2)
    return f'{h}:{m}:{s}'


CONVERTERS = {
    'stops': {
        'stop_lat': float,
        'stop_lon': float
    },
    'calendar': {
        **{day: int for day in DAYS},
        'start_date': dttm,
        'end_date': dttm
    },
    'stop_times': {
        'arrival_time': tdlt,
        'departure_time': tdlt,
        'stop_sequence': int,
        'shape_dist_traveled': flt
    },
    'calendar_dates': {
        'date': dttm
    }
}


def load_gtfs(
        path: Union[str, Path],
        id_prefix: str = '',
        id_prefix_col: str = 'alt_',
        only_busiest_day: bool = True,
        busiest_service_id: str = 'busiest',
        remove_unused_stops: bool = True,
        remove_unused_routes: bool = True
) -> Dict[str, pd.DataFrame]:
    gtfs = {}
    for p in Path(path).glob('*.txt'):
        name = p.stem
        if name not in NAMES:
            continue
        table = pd.read_csv(p, dtype=str)
        if name in CONVERTERS:
            for col, call in CONVERTERS[name].items():
                if col in table.columns:
                    table[col] = table[col].apply(call)
        for col in table.columns:
            if id_prefix and col.endswith('_id') and col != 'direction_id':
                table[id_prefix_col + col] = id_prefix + table[col]
        gtfs[name] = table
    for rname in REQ_NAMES:
        if all(rname not in name for name in gtfs):
            raise ValueError(f'Required file "{rname}" is missing')

    if only_busiest_day:
        filter_busiest_day(
            gtfs=gtfs,
            id_prefix=id_prefix,
            busiest_service_id=busiest_service_id,
            remove_unused_stops=remove_unused_stops,
            remove_unused_routes=remove_unused_routes
        )

    return gtfs


def filter_busiest_day(
        gtfs: Dict[str, pd.DataFrame],
        id_prefix: str = '',
        id_prefix_col: str = 'alt_',
        busiest_service_id: str = 'busiest',
        remove_unused_stops: bool = True,
        remove_unused_routes: bool = True
):
    ids, day = get_busiest_service_ids_day(gtfs)
    gtfs['trips'] = gtfs['trips'][
        gtfs['trips']['service_id'].isin(ids)
    ]
    gtfs['stop_times'] = gtfs['stop_times'][
        gtfs['stop_times']['trip_id'].isin(
            gtfs['trips']['trip_id'].tolist()
        )
    ]

    # we don't need dates for 1-day calendar
    if 'calendar_dates' in gtfs:
        del gtfs['calendar_dates']

    # create new calendar
    cal_row = {c: '0' for c in gtfs['calendar'].columns}
    cal_row[DAYS[day.dayofweek]] = '1'
    cal_row['service_id'] = busiest_service_id
    cal_row['start_date'] = day
    cal_row['end_date'] = day
    gtfs['calendar'] = pd.DataFrame(cal_row, index=[0])

    # apply custom prefix
    gtfs['trips'].loc[:, 'service_id'] = busiest_service_id
    if id_prefix:
        gtfs['trips'].loc[:, id_prefix_col + 'service_id'] = id_prefix + busiest_service_id

    if remove_unused_stops:
        remove_unused(gtfs=gtfs, table_name='stops')
    if remove_unused_routes:
        remove_unused(gtfs=gtfs, table_name='routes')


def remove_unused(
        gtfs: Dict[str, pd.DataFrame],
        table_name: Literal['stops', 'routes']
):
    if table_name == 'stops':
        # remove unused stops, that are regular platforms
        gtfs['stops'].drop(
            gtfs['stops'][
                ~gtfs['stops']['stop_id'].isin(
                    gtfs['stop_times']['stop_id'].tolist()
                ) &
                (gtfs['stops']['location_type'].isna() |
                 gtfs['stops']['location_type'].isin(['0', '']))
            ].index,
            inplace=True
        )
    elif table_name == 'routes':
        gtfs['routes'].drop(
            gtfs['routes'][
                ~gtfs['routes']['route_id'].isin(
                    gtfs['trips']['route_id'].tolist()
                )
            ].index,
            inplace=True
        )
    else:
        raise ValueError('Wrong `table_name`')


def get_busiest_service_ids_day(
        gtfs: Dict[str, pd.DataFrame]
) -> Tuple[List[str], dt]:
    mostday = defaultdict(int)
    servday = defaultdict(list)

    for service_id, service_df in gtfs['trips'].groupby('service_id'):

        cal_df = gtfs['calendar'][gtfs['calendar']['service_id'] == service_id]
        sd, ed = cal_df[['start_date', 'end_date']].iloc[0]
        allowed_wdays = cal_df[DAYS].iloc[0].to_dict()
        drange = pd.date_range(sd, ed)
        allowed_days = []

        for awd in drange:
            d_name = awd.day_name().lower()

            if 'calendar_dates' in gtfs:
                cdates = gtfs['calendar_dates'][
                     (gtfs['calendar_dates']['date'].dt.date == awd.date()) &
                     (gtfs['calendar_dates']['service_id'] == service_id)
                ]
                exctypes = cdates['exception_type'].tolist()
                excluded = '1' in exctypes
                included = '2' in exctypes
            else:
                excluded = False
                included = False

            if allowed_wdays[d_name] and not excluded:
                allowed_days.append(awd)
            elif included:
                allowed_days.append(awd)

        for ald in allowed_days:
            mostday[ald] += len(service_df)
            servday[ald].append(service_id)

    mk = max(mostday, key=mostday.get)
    return servday[mk], mk


def write_gtfs(
        gtfs: Dict[str, pd.DataFrame],
        output_directory_or_zip: Union[str, Path]
):
    out_dir = Path(output_directory_or_zip)
    if out_dir.exists() and out_dir.is_dir():
        for stem, table in gtfs.items():
            if stem == 'stop_times':
                table = table.copy()
                table['arrival_time'] = table['arrival_time'].apply(td2str)
                table['departure_time'] = table['departure_time'].apply(td2str)
            table.to_csv(out_dir / (stem + '.txt'), index=False, date_format='%Y%m%d')
    elif out_dir.suffix == '.zip':
        with zipfile.ZipFile(
                file=out_dir,
                mode='w',
                compression=zipfile.ZIP_DEFLATED,
                compresslevel=4
                ) as zobj:
            for stem, table in gtfs.items():
                if stem == 'stop_times':
                    table = table.copy()
                    table['arrival_time'] = table['arrival_time'].apply(td2str)
                    table['departure_time'] = table['departure_time'].apply(td2str)
                zobj.writestr(
                    stem + '.txt',
                    data=table.to_csv(index=False, date_format='%Y%m%d')
                )
    else:
        raise RuntimeError('Saving went wrong')
