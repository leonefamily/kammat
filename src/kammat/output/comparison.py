# -*- coding: utf-8 -*-
"""
Created on Tue Mar  7 17:28:48 2023

@author: dgrishchuk
"""
import argparse
import logging
import sys

import geopandas as gpd
import pandas as pd
from pathlib import Path
from typing import Union, List, Tuple, Optional

from kammat.output.utils import EVENTS_MODES
from kammat.defaults.constants import CSV_STYLE


def merge_intensities_with_orig_shape(
        orig_net_shp_path: Union[str, Path],
        edge_net_shp_path: Union[str, Path],
        net_counts_shp_path: Union[str, Path]
        ) -> gpd.GeoDataFrame:
    """
    Get GeoDataFrame with original links IDs and model counts for every mode.

    Parameters
    ----------
    orig_net_shp_path : Union[str, Path]
        Original shape network, that was used to create MATSim network
    edge_net_shp_path : Union[str, Path]
        Reformatted shape for MATSim, that contains all attributes from
        original network (and column 'o_link_id' or 'ROAD_ID' with original link ids)
    net_counts_shp_path : Union[str, Path]
        MATSim network shape with counts after analysis

    Returns
    -------
    gpd.GeoDataFrame

    """
    orig_gdf = gpd.read_file(orig_net_shp_path)
    edge_gdf = gpd.read_file(edge_net_shp_path)
    cnts_gdf = gpd.read_file(net_counts_shp_path)

    oid_id = {}

    for oid, oid_ser in edge_gdf.groupby(
            'o_link_id' if 'o_link_id' in edge_gdf.columns else 'ROAD_ID'
            )['link_id']:
        oid_id[oid] = oid_ser.tolist()

    oid_count = {mode: {} for mode in EVENTS_MODES}
    for oid, ids in oid_id.items():
        rows = cnts_gdf[cnts_gdf['link_id'].isin(ids)]
        if len(rows) > 0:
            for mode in oid_count:
                oid_count[mode][oid] = int(rows[mode].sum())

    mrgd_gdf = orig_gdf
    for mode, oids in oid_count.items():
        mser = pd.Series(oids, name=mode)
        if 'link_id' not in mrgd_gdf.columns:
            mrgd_gdf['link_id'] = mrgd_gdf['ROAD_ID']
        mrgd_gdf = mrgd_gdf.merge(
            mser, left_on='link_id', right_on=mser.index
            )
    return mrgd_gdf


def geh(
        orig_count: int,
        model_count: int
        ) -> float:
    """GEH formula."""
    if model_count == orig_count == 0:
        return 0
    geh_val = (
        (2 * (model_count - orig_count)) ** 2 / (model_count + orig_count)
    ) ** 0.5
    return geh_val


def diff(
        orig_count: int,
        model_count: int,
        hanas_condition: bool = True
        ) -> float:
    """
    Get relative difference, compared to original (real-world) count.

    Parameters
    ----------
    orig_count : int
        Real-world count
    model_count : int
        Count from model
    hanas_condition : bool, optional
        Hana's condition, conciders difference less than 1000 to be ok.
        The default is True.

    Returns
    -------
    float

    """
    if hanas_condition:
        if abs(orig_count - model_count) < 1000:
            return 0
    return (orig_count - model_count) / ((orig_count + model_count) / 2)


def calculate_geh_diff(
        merged_gdf: gpd.GeoDataFrame,
        intensities_df: pd.DataFrame,
        ) -> gpd.GeoDataFrame:
    link_ids = intensities_df['link_id'].tolist()
    intensities_gdf = merged_gdf[merged_gdf['link_id'].isin(link_ids)].copy()
    for mode in EVENTS_MODES:
        try:
            intensities_gdf[f'{mode}_c'] = intensities_gdf[['link_id']].merge(
                        intensities_df[['link_id', mode]], how='left'
                        )[mode].tolist()
            intensities_gdf[f'geh_{mode}'] = intensities_gdf.apply(
                lambda r: geh(r[f'{mode}_c'], r[mode]), axis=1
                )
            intensities_gdf[f'dif_{mode}'] = intensities_gdf.apply(
                lambda r: diff(r[f'{mode}_c'], r[mode]), axis=1
                )
        except ValueError as e:
            logging.warning(
                f'{e}: {mode} does not have any links to compare with'
            )
    return intensities_gdf


def get_diff_category(
        val: float,
        thresh: float = 0.25
        ) -> str:
    """
    Get label 'ok', 'model-' or 'model+' depending on difference value.

    Parameters
    ----------
    val : float
        Relative difference value.
    thresh : float, optional
        Absolute threshold of difference to be considered ok. Default is 0.25.

    Returns
    -------
    str

    """
    if -thresh <= val <= thresh:
        return 'ok'
    elif val > thresh:
        return 'model-'
    return 'model+'


def mark_diff_category(
        calculated_gdf: gpd.GeoDataFrame,
        thresh: float = 0.25
        ):
    """
    Put labels 'ok', 'model-' or 'model+' depending on difference values.

    Parameters
    ----------
    calculated_gdf : gpd.GeoDataFrame
        GeoDataFrame with differences already calculated
    thresh : float, optional
        Absolute threshold of difference to be considered ok. Default is 0.25.

    """
    for mode in EVENTS_MODES:
        calculated_gdf[f'dcat_{mode}'] = calculated_gdf[f'dif_{mode}'].apply(
            lambda d: get_diff_category(d, thresh)
            )


def get_diff_stats(
        calculated_gdf: gpd.GeoDataFrame
        ) -> pd.DataFrame:
    """
    Get table with percentages of cases 'ok', 'model-' or 'model+.

    Parameters
    ----------
    calculated_gdf : gpd.GeoDataFrame
        GeoDataFrame with differences already calculated and their labels set.

    """
    length = len(calculated_gdf)
    stats_dfs = []
    for mode in EVENTS_MODES:
        abs_cnt = pd.DataFrame(calculated_gdf).groupby(f'dcat_{mode}').size()
        rel_cnt = abs_cnt / length
        abs_cnt.name = 'absolute'
        rel_cnt.name = 'relative'
        pre_stats_df = pd.DataFrame([abs_cnt, rel_cnt]).transpose()
        pre_stats_df['mode'] = mode
        stats_dfs.append(pre_stats_df)
    stats_df = pd.concat(stats_dfs)
    stats_df.index.name = 'value'
    return stats_df


def handle_real_world_comparison(
        orig_net_shp_path: Union[str, Path],
        edge_net_shp_path: Union[str, Path],
        net_counts_shp_path: Union[str, Path],
        network_intensities_path: Union[str, Path],
        network_differences_save_path: Union[str, Path],
        network_differences_stats_save_path: Union[str, Path],
        intersection_intensities_path: Union[str, Path] = None,
        intersection_differences_save_path: Union[str, Path] = None,
        intersection_differences_stats_save_path: Union[str, Path] = None,
        difference_thresh: float = 0.25
        ):
    """
    Save graphic representation and statistics on intensities comparison.

    Parameters
    ----------
    orig_net_shp_path : Union[str, Path]
        Original shape network, that was used to create MATSim network
    edge_net_shp_path : Union[str, Path]
        Reformatted shape for MATSim, that contains all attributes from
        original network (and column 'o_link_id' with original link ids)
    net_counts_shp_path : Union[str, Path]
        MATSim network shape with counts after analysis
    network_intensities_path : Union[str, Path]
        Table to compare - link id, car count, truck count; long links series,
        mostly between intersections
    network_differences_save_path : Union[str, Path]
        Where to save shape with results.
    network_differences_stats_save_path : Union[str, Path]
        Where to save table with statistics results.
    intersection_intensities_path : Union[str, Path], optional
        Table to compare - link id, car count, truck count; short links series,
        only close to intersections.
    intersection_differences_save_path : Union[str, Path], optional
        Where to save shape with results.
    intersection_differences_stats_save_path : Union[str, Path], optional
        Where to save table with statistics results.
    difference_thresh : float, optional
        Absolute threshold of difference to be considered ok. Default is 0.25.

    """
    paths = [[network_intensities_path,
              network_differences_save_path,
              network_differences_stats_save_path],
             [intersection_intensities_path,
              intersection_differences_save_path,
              intersection_differences_stats_save_path]]
    merged_gdf = merge_intensities_with_orig_shape(
        orig_net_shp_path, edge_net_shp_path, net_counts_shp_path
        )
    for intensities_path, shp_path, csv_path in paths:
        if intensities_path is not None:
            intensities_df = pd.read_csv(intensities_path, **CSV_STYLE)
            calculated_gdf = calculate_geh_diff(merged_gdf, intensities_df)
            if len(calculated_gdf) != 0:
                mark_diff_category(calculated_gdf, difference_thresh)
                calculated_gdf.to_file(shp_path, encoding='utf-8')
                stats_df = get_diff_stats(calculated_gdf)
                stats_df.to_csv(csv_path, **CSV_STYLE)


def handle_spatial_comparison(
        prev_net_path: Union[str, Path],
        curr_net_path: Union[str, Path],
        comparison_columns: Union[List[str], Tuple[str], str],
        diff_net_save_path: Union[str, Path] = None
        ) -> Optional[gpd.GeoDataFrame]:
    prev_net = gpd.read_file(prev_net_path)
    net = gpd.read_file(curr_net_path)
    crss = [crs for crs in (net.crs, prev_net.crs) if crs is not None]
    crs = crss[0].srs if crss else None
    diff_net = net.merge(
        prev_net, suffixes=('_1', '_0'), on='geometry', how='outer'
    )
    if isinstance(comparison_columns, (list, tuple)):
        for col in comparison_columns:
            diff_net[col + '_1'] = diff_net[col + '_1'].fillna(0)
            diff_net[col + '_0'] = diff_net[col + '_0'].fillna(0)
            # ad - absolute difference, rd - relative difference
            diff_net[col + '_ad'] = diff_net[col + '_1'] - diff_net[col + '_0']
            diff_net[col + '_rd'] = diff_net[col + '_ad'] / diff_net[col + '_0']
    elif isinstance(comparison_columns, str):
        col = comparison_columns
        diff_net[col + '_1'] = diff_net[col + '_1'].fillna(0)
        diff_net[col + '_0'] = diff_net[col + '_0'].fillna(0)
        diff_net[col + '_ad'] = diff_net[col + '_1'] - diff_net[col + '_0']
        diff_net[col + '_rd'] = diff_net[col + '_ad'] / diff_net[col + '_0']
    else:
        raise NotImplementedError('{type(comparison_columns)} is unsupported')
    diff_net = gpd.GeoDataFrame(diff_net, crs=crs)
    if diff_net_save_path is None:
        return diff_net
    diff_net.to_file(diff_net_save_path, encoding='utf-8')


def handle_modal_split_change(
        facilities_gdf: gpd.GeoDataFrame,
        agents_stats: pd.DataFrame,
        legs: pd.DataFrame
        ) -> Optional[gpd.GeoDataFrame]:
    # !!!
    pass


def handle_model_comparison(
        prev_net_counts_path: Union[str, Path] = None,
        prev_pt_net_counts_path: Union[str, Path] = None,
        prev_pt_stops_counts_path: Union[str, Path] = None,
        curr_net_counts_path: Union[str, Path] = None,
        curr_pt_net_counts_path: Union[str, Path] = None,
        curr_pt_stops_counts_path: Union[str, Path] = None,
        diff_net_counts_save_path: Union[str, Path] = None,
        diff_pt_net_counts_save_path: Union[str, Path] = None,
        diff_pt_stops_counts_save_path: Union[str, Path] = None
        ):
    if prev_net_counts_path is not None:
        if curr_net_counts_path is not None:
            logging.info('road net comparison has started')
            try:
                handle_spatial_comparison(
                    prev_net_counts_path,
                    curr_net_counts_path,
                    EVENTS_MODES,
                    diff_net_counts_save_path
                    )
            except Exception as e:
                logging.warning(
                    f'road net comparison from previous run failed: {e}'
                    )
    if prev_pt_net_counts_path is not None:
        if curr_pt_net_counts_path is not None:
            logging.info('pt net comparison has started')
            try:
                handle_spatial_comparison(
                    prev_pt_net_counts_path,
                    curr_pt_net_counts_path,
                    'count',
                    diff_pt_net_counts_save_path
                    )
            except Exception as e:
                logging.warning(
                    f'pt net comparison from previous run failed: {e}'
                    )
    if prev_pt_stops_counts_path is not None:
        if curr_pt_stops_counts_path is not None:
            logging.info('pt stops comparison has started')
            try:
                handle_spatial_comparison(
                    prev_pt_stops_counts_path,
                    curr_pt_stops_counts_path,
                    ['entered', 'left', 'passed'],
                    diff_pt_stops_counts_save_path
                    )
            except Exception as e:
                logging.warning(
                    f'pt stops comparison from previous run failed: {e}'
                    )


def compare_rw_model(
        orig_net_path: Union[str, Path],
        edge_net_path: Union[str, Path],
        net_counts_path: Union[str, Path],
        network_intensities_path: Union[str, Path],
        network_differences_save_path: Union[str, Path],
        network_differences_stats_save_path: Union[str, Path],
        intersection_intensities_path: Union[str, Path] = None,
        intersection_differences_save_path: Union[str, Path] = None,
        intersection_differences_stats_save_path: Union[str, Path] = None,
        difference_thresh: float = 0.25,
        prev_net_counts_path: Union[str, Path] = None,
        prev_pt_net_counts_path: Union[str, Path] = None,
        prev_pt_stops_counts_path: Union[str, Path] = None,
        pt_net_counts_path: Union[str, Path] = None,
        pt_stops_counts_path: Union[str, Path] = None,
        diff_net_counts_save_path: Union[str, Path] = None,
        diff_pt_net_counts_save_path: Union[str, Path] = None,
        diff_pt_stops_counts_save_path: Union[str, Path] = None
        ):
    handle_real_world_comparison(
        orig_net_path,
        edge_net_path,
        net_counts_path,
        network_intensities_path,
        network_differences_save_path,
        network_differences_stats_save_path,
        intersection_intensities_path,
        intersection_differences_save_path,
        intersection_differences_stats_save_path,
        difference_thresh
        )
    handle_model_comparison(
        prev_net_counts_path,
        prev_pt_net_counts_path,
        prev_pt_stops_counts_path,
        net_counts_path,
        pt_net_counts_path,
        pt_stops_counts_path,
        diff_net_counts_save_path,
        diff_pt_net_counts_save_path,
        diff_pt_stops_counts_save_path
        )


def parse_args(
        args_list: List[str] = None
        ) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-o', '--orig-net-path')
    parser.add_argument('-e', '--edge-net-path')
    parser.add_argument('-c', '--net-counts-path')
    parser.add_argument('-i', '--network-intensities-path')
    parser.add_argument('-d', '--network-differences-save-path')
    parser.add_argument('-D', '--network-differences-stats-save-path')
    parser.add_argument('-I', '--intersection-intensities-path')
    parser.add_argument('-y', '--intersection-differences-save-path')
    parser.add_argument('-Y', '--intersection-differences-stats-save-path')
    parser.add_argument('-t', '--difference-thresh', type=float, default=.25)
    parser.add_argument('-pc', '--prev-net-counts-path')
    parser.add_argument('-pp', '--prev-pt-net-counts-path')
    parser.add_argument('-ps', '--prev-pt-stops-counts-path')
    parser.add_argument('-p', '--pt-net-counts-path')
    parser.add_argument('-s', '--pt-stops-counts-path')
    parser.add_argument('-dc', '--diff-net-counts-save-path')
    parser.add_argument('-dp', '--diff-pt-net-counts-save-path')
    parser.add_argument('-ds', '--diff-pt-stops-counts-save-path')
    args = parser.parse_args(sys.argv[1:] if args_list is None else args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    compare_rw_model(
        orig_net_path=args.orig_net_path,
        edge_net_path=args.edge_net_path,
        net_counts_path=args.net_counts_path,
        network_intensities_path=args.network_intensities_path,
        network_differences_save_path=args.network_differences_save_path,
        network_differences_stats_save_path=args.network_differences_stats_save_path,
        intersection_intensities_path=args.intersection_intensities_path,
        intersection_differences_save_path=args.intersection_differences_save_path,
        intersection_differences_stats_save_path=args.intersection_differences_stats_save_path,
        difference_thresh=args.difference_thresh,
        prev_net_counts_path=args.prev_net_counts_path,
        prev_pt_net_counts_path=args.prev_pt_net_counts_path,
        prev_pt_stops_counts_path=args.prev_pt_stops_counts_path,
        pt_net_counts_path=args.pt_net_counts_path,
        pt_stops_counts_path=args.pt_stops_counts_path,
        diff_net_counts_save_path=args.diff_net_counts_save_path,
        diff_pt_net_counts_save_path=args.diff_pt_net_counts_save_path,
        diff_pt_stops_counts_save_path=args.diff_pt_stops_counts_save_path
    )
