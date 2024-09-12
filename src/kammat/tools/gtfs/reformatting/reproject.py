#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue Jun  4 22:29:24 2024

@author: leonefamily
"""

import sys
import logging
import argparse
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Union, Dict, Optional, Any, Callable, List

DEFAULT_GTFS_CRS = 'epsg:4326'
TARGET_GTFS_CRS = 'epsg:5514'


def parse_args(
        args_from: Optional[List[str]] = None
) -> argparse.Namespace:
    if args_from is None:
        args_from = sys.argv[1:]

    parser = argparse.ArgumentParser()
    parser.add_argument("-g", "--gtfs-dir",
                        help="Where original gtfs is located (not zip)")
    parser.add_argument("-o", "--output-dir",
                        help="Where to save changed data")
    parser.add_argument("-f", "--from-crs", default=DEFAULT_GTFS_CRS,
                        help="Reproject from CRS (epsg:xxxx)")
    parser.add_argument("-t", "--to-crs", default=TARGET_GTFS_CRS,
                        help="Reproject to CRS (epsg:xxxx)")
    args = parser.parse_args(args_from)
    return args


def load_gtfs(
        gtfs_dir: Union[Path, str]
) -> Dict[str, pd.DataFrame]:
    files = list(Path(gtfs_dir).rglob('*.txt'))
    gtfs = {}
    for file in files:
        gtfs[file.stem] = pd.read_csv(file)
    try:
        gtfs['calendar'].start_date = pd.to_datetime(
            gtfs['calendar'].start_date, format='%Y%m%d')
        gtfs['calendar'].end_date = pd.to_datetime(
            gtfs['calendar'].end_date, format='%Y%m%d')
    except KeyError:
        logging.info('No calendar.txt, skipping')
    try:
        gtfs['calendar_dates'].date = pd.to_datetime(
            gtfs['calendar_dates'].date, format='%Y%m%d')
    except KeyError:
        logging.info('No calendar_dates.txt, skipping')
    return gtfs


def write_gtfs(
        gtfs: Dict[str, pd.DataFrame],
        path: Union[str, Path]
):
    p = Path(path)
    p.mkdir(exist_ok=True)
    for table, contents in gtfs.items():
        if table == 'calendar':
            contents.start_date = contents.start_date.dt.strftime('%Y%m%d')
            contents.end_date = contents.end_date.dt.strftime('%Y%m%d')
        if table == 'calendar_dates':
            contents['date'] = contents['date'].dt.strftime('%Y%m%d')
        contents.convert_dtypes().to_csv(p / f'{table}.txt', index=False)


def reproject_stops(
        stops: pd.DataFrame,
        from_crs: str,
        to_crs: str
) -> pd.DataFrame:
    gstops = gpd.GeoDataFrame(
        stops, crs=from_crs,
        geometry=gpd.points_from_xy(x=stops['stop_lon'], y=stops['stop_lat'])
    ).to_crs(to_crs)
    gstops['stop_lon'] = [point.x for point in gstops.geometry]
    gstops['stop_lat'] = [point.y for point in gstops.geometry]
    return pd.DataFrame(gstops.drop('geometry', axis=1))


def main(
        gtfs_dir: Union[str, Path],
        output_dir: Union[str, Path],
        to_crs: str,
        from_crs: str = DEFAULT_GTFS_CRS
):
    gtfs = load_gtfs(gtfs_dir)
    gtfs['stops'] = reproject_stops(
        stops=gtfs['stops'],
        from_crs=from_crs,
        to_crs=to_crs
    )
    write_gtfs(gtfs=gtfs, path=output_dir)


if __name__ == '__main__':
    args = parse_args()
    main(
        gtfs_dir=args.gtfs_dir,
        output_dir=args.output_dir,
        to_crs=args.to_crs,
        from_crs=args.from_crs
    )
