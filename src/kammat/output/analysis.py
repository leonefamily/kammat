# -*- coding: utf-8 -*-
"""
Created on Thu Feb  2 10:16:41 2023

@author: dgrishchuk
"""
import argparse
import logging
import sys
import traceback
import pandas as pd
import geopandas as gpd
from pathlib import Path
from typing import Union, List, Optional, Dict

from kammat.defaults.constants import CSV_STYLE
from kammat.output.counts import (
    get_events_counts, write_link_counts, write_link_turns, write_pt_counts
    )
from kammat.output.road import (
    load_network, merge_net_counts, get_ribbon_diagram, get_link_count_stats,
    link_stats_to_df, get_link_stats_plot
)
from kammat.output.utils import EVENTS_MODES
from kammat.output.pt import (
    merge_net_pt_counts, pt_net_to_plot_gdf, get_pt_stats, add_stop_name_columns, add_lines_column,
    get_pt_links_time_stats, get_pt_link_time_plot, get_pt_link_time_plot_df,
    get_line_route_plot, handle_pt, load_pt_schedule, get_pt_transfers,
    get_transit_stops
)


def get_original_link_id(
        link_id: str
        ) -> Optional[int]:
    try:
        return int(link_id.split('_')[2])
    except (IndexError, TypeError, ValueError):
        return None


def save_node_data(
        net: gpd.GeoDataFrame,
        turns,
        links_nodes_groups: List[List[int]],
        ribbon_diagrams_directory: Union[str, Path]
        ):
    sdir = Path(ribbon_diagrams_directory)
    for group in links_nodes_groups:
        try:
            o_link_ids = net['link_id'].apply(get_original_link_id)
            node_id = net.loc[o_link_ids.isin(group), 'from_node'].mode().item()
            for mode in EVENTS_MODES:
                fig, tables = get_ribbon_diagram(net, turns, node_id, mode=mode)
                fig.savefig(
                    sdir / f'node_{node_id}_{mode}_ribbon.png', dpi=200, bbox_inches='tight'
                    )
                tables['turns'].to_csv(
                    sdir / f'node_{node_id}_{mode}_turns.csv', **CSV_STYLE, index=False
                    )
                tables['groups'].to_csv(
                    sdir / f'node_{node_id}_{mode}_groups.csv', **CSV_STYLE, index=False
                    )
        except Exception:
            print(traceback.format_exc())


def save_road_link_data(
        net: gpd.GeoDataFrame,
        counts: Dict[str, Dict[float, Dict[str, int]]],
        link_ids: List[int],
        road_links_intensities_directory: Union[str, Path]
        ):
    o_link_ids = net['link_id'].apply(get_original_link_id)
    nlink_ids = net.loc[o_link_ids.isin(link_ids), 'link_id'].tolist()
    rdir = Path(road_links_intensities_directory)
    for link_id in nlink_ids:
        try:
            link_stats = get_link_count_stats(counts, link_id)
            link_stats_df = link_stats_to_df(link_stats)
            fig = get_link_stats_plot(link_stats, net)
            fig.savefig(rdir / f'link_{link_id}.png', dpi=200, bbox_inches="tight")
            link_stats_df.to_csv(rdir / f'link_{link_id}.csv', **CSV_STYLE, index=False)
        except Exception:
            logging.error(link_id, traceback.format_exc())


def save_pt_link_line_data(
        net: gpd.GeoDataFrame,
        pt_counts,
        schedule_path: Union[str, Path],
        pt_links_ids: List[str] = None,
        pt_lines_ids: List[str] = None,
        output_pt_links_intensities_directory: Union[str, Path] = None,
        output_pt_lines_intensities_directory: Union[str, Path] = None
        ):
    pt_schedule = load_pt_schedule(schedule_path)
    pt_stops = get_transit_stops(pt_schedule)
    if pt_links_ids:
        for pt_link_id in pt_links_ids:
            pt_links_stats, stops_stats = get_pt_stats(
                pt_counts, pt_schedule, pt_stops,
                lines=None, link_id=pt_link_id
                )
            pt_net = merge_net_pt_counts(net, pt_links_stats)
            pt_net = add_stop_name_columns(pt_net, pt_stops)
            pt_net = add_lines_column(pt_net, pt_schedule)
            pt_net = pt_net_to_plot_gdf(pt_net, lines=None)
            pt_links_time_stats = get_pt_links_time_stats(
                pt_counts, pt_schedule, pt_stops, lines=None,
                link_ids=[pt_link_id],
                aggregate_by=1800
                )
            table = get_pt_link_time_plot_df(
                pt_links_time_stats, pt_net, link_id=pt_link_id
                )
            fig = get_pt_link_time_plot(
                table, pt_net, link_id=pt_link_id
                )
            parent_links = Path(output_pt_links_intensities_directory)
            table.to_csv(
                parent_links / f'link_{pt_link_id}.csv',
                **CSV_STYLE, index=False
            )
            fig.savefig(parent_links / f'link_{pt_link_id}.png', dpi=200)
    if pt_lines_ids:
        for pt_line_id in pt_lines_ids:
            pt_links_stats, stops_stats = get_pt_stats(
                pt_counts, pt_schedule, pt_stops,
                lines=[pt_line_id], link_id=None
                )
            pt_net = merge_net_pt_counts(net, pt_links_stats)
            pt_net = add_stop_name_columns(pt_net, pt_stops)
            pt_net = add_lines_column(pt_net, pt_schedule)
            pt_net = pt_net_to_plot_gdf(pt_net, lines=None)
            parent_lines = Path(output_pt_lines_intensities_directory)
            table = pt_net_to_plot_gdf(pt_net, [pt_line_id])
            fig = get_line_route_plot(table, [pt_line_id])
            table.to_csv(
                parent_lines / f'line_{pt_line_id}.csv',
                **CSV_STYLE, index=False
            )
            fig.savefig(parent_lines / f'line_{pt_line_id}.png', dpi=200)


def get_traffic_volume(
        road_net: gpd.GeoDataFrame,
        volume_polys: gpd.GeoDataFrame
        ) -> gpd.GeoDataFrame:
    nrows = []
    for n, row in volume_polys.iterrows():
        cropped = road_net[road_net.intersects(row.geometry)]
        for mode in EVENTS_MODES:
            row[mode] = round(
                (cropped.geometry.length * cropped[mode]).sum()
                )
        nrows.append(row)
    npolys = gpd.GeoDataFrame(nrows, crs=volume_polys.crs)
    return npolys


def get_cordons_crossings(
        road_net: gpd.GeoDataFrame,
        cordon_polys: gpd.GeoDataFrame
        ) -> gpd.GeoDataFrame:
    nrows = []
    for n, row in cordon_polys.iterrows():
        cropped = road_net[road_net.intersects(row.geometry.exterior)]
        for mode in EVENTS_MODES:
            row[mode] = cropped[mode].sum()
        nrows.append(row)
    npolys = gpd.GeoDataFrame(nrows, crs=cordon_polys.crs)
    return npolys


def get_legs_stats(
        legs: pd.DataFrame
        ) -> pd.DataFrame:
    # !!!
    QUANTILE = [0.01, 0.1, .25, .5, .75, .9, .99, 1]
    one_legs_stats = {}

    cond = legs['mode'] == 'car'
    one_legs_stats['mean'] = legs.loc[cond, 'distance'].mean()
    one_legs_stats['car_legs_count'] = len(legs[cond])
    one_legs_stats['car_pers_count'] = len(legs.loc[cond, 'person'].unique())
    one_legs_stats.update(legs.loc[cond, 'distance'].quantile(QUANTILE).to_dict())


def analyze_output_basic(
        events_path: Union[str, Path],
        net_path: Union[str, Path],
        output_counts_path: Union[str, Path],
        output_turns_path: Union[str, Path],
        output_net_counts_path: Union[str, Path],
        schedule_path: Union[str, Path] = None,
        output_pt_counts_path: Union[str, Path] = None,
        output_pt_net_counts_path: Union[str, Path] = None,
        output_pt_stops_counts_path: Union[str, Path] = None,
        crs: str = None,
        links_nodes_groups: List[List[int]] = None,
        output_ribbon_diagrams_directory: Union[str, Path] = None,
        road_links_ids: List[int] = None,
        output_road_links_intensities_directory: Union[str, Path] = None,
        pt_links_ids: List[str] = None,
        pt_lines_ids: List[str] = None,
        output_pt_links_intensities_directory: Union[str, Path] = None,
        output_pt_lines_intensities_directory: Union[str, Path] = None,
        cordon_poly_path: Union[str, Path] = None,
        output_cordon_stats_path: Union[str, Path] = None,
        volume_poly_path: Union[str, Path] = None,
        output_volume_stats_path: Union[str, Path] = None,
        legs_path: Union[str, Path] = None,
        output_transfers_path: Union[str, Path] = None
):
    if output_transfers_path is not None and legs_path is None:
        raise ValueError(
            '`legs_path` is necessary to process `output_transfers_path`'
        )
    net, nodes = load_network(net_path, crs, include_nodes=True)
    counts, pt_counts, turns = get_events_counts(
        events_path
        )
    if counts:
        road_net = merge_net_counts(net, counts)
        road_net.to_file(output_net_counts_path)
        write_link_counts(counts, output_counts_path)
        write_link_turns(turns, output_turns_path)
    if pt_counts:
        write_pt_counts(pt_counts, output_pt_counts_path)
        if schedule_path:
            pt_schedule = load_pt_schedule(schedule_path)
            pt_net_counts, pt_stops_counts = handle_pt(pt_counts, pt_schedule, net)
            pt_net_counts.to_file(output_pt_net_counts_path, encoding='utf-8')
            pt_stops_counts.to_file(output_pt_stops_counts_path, encoding='utf-8')
            if pt_links_ids or pt_lines_ids:
                save_pt_link_line_data(
                    net, pt_counts, schedule_path, pt_links_ids, pt_lines_ids,
                    output_pt_links_intensities_directory,
                    output_pt_lines_intensities_directory
                )
        if output_transfers_path:
            legs_df = pd.read_csv(legs_path, **CSV_STYLE)
            pt_stops = get_transit_stops(pt_schedule)
            # will not return transfers themselves, but flushes them to file
            get_pt_transfers(
                pt_schedule=pt_schedule,
                pt_stops=pt_stops,
                legs_df=legs_df,
                flush_to=output_transfers_path
            )
    if links_nodes_groups is not None:
        try:
            save_node_data(
                net, turns, links_nodes_groups, output_ribbon_diagrams_directory
                )
        except Exception as e:
            print(e)
    if road_links_ids is not None:
        try:
            save_road_link_data(
                net, counts, road_links_ids, output_road_links_intensities_directory
                )
        except Exception as e:
            print(e)
    if cordon_poly_path is not None:
        cordon_polys = gpd.read_file(cordon_poly_path)
        cordon_polys_done = get_cordons_crossings(road_net, cordon_polys)
        cordon_polys_done.to_file(output_cordon_stats_path, encoding='utf-8')
    if volume_poly_path is not None:
        volume_polys = gpd.read_file(volume_poly_path)
        volume_polys_done = get_traffic_volume(road_net, volume_polys)
        volume_polys_done.to_file(output_volume_stats_path, encoding='utf-8')


def parse_args(
        args_list: List[str] = sys.argv[1:]
        ) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--events-path')
    parser.add_argument('-n', '--net-path')
    parser.add_argument('-l', '--legs-path')
    parser.add_argument('-T', '--output-transfers-path')
    parser.add_argument('-c', '--output-counts-path')
    parser.add_argument('-t', '--output-turns-path')
    parser.add_argument('-nc', '--output-net-counts-path')
    parser.add_argument('-s', '--schedule-path')
    parser.add_argument('-p', '--output-pt-counts-path')
    parser.add_argument('-pn', '--output-pt-net-counts-path')
    parser.add_argument('-ps', '--output-pt-stops-counts-path')
    parser.add_argument('--crs')
    parser.add_argument('-ng', '--links-nodes-groups')
    parser.add_argument('-rd', '--output-ribbon-diagrams-directory')
    parser.add_argument('-rl', '--road-links-ids')
    parser.add_argument('-ld', '--output-road-links-intensities-directory')
    parser.add_argument('-pl', '--pt-links-ids')
    parser.add_argument('-pr', '--pt-lines-ids')
    parser.add_argument('-pld', '--output-pt-links-intensities-directory')
    parser.add_argument('-prd', '--output-pt-lines-intensities-directory')
    parser.add_argument('-C', '--cordon-poly-path')
    parser.add_argument('-cs', '--output-cordon-stats-path')
    parser.add_argument('-V', '--volume-poly-path')
    parser.add_argument('-vs', '--output-volume-stats-path')
    args = parser.parse_args(args_list)
    return args


if __name__ == '__main__':
    args = parse_args()
    if args.links_nodes_groups is not None:
        links_nodes_groups = [
            [int(subel.strip()) for subel in el.split(',')]
            for el in args.links_nodes_groups.split(';')
            ]
    else:
        links_nodes_groups = None
    if args.road_links_ids is not None:
        road_links_ids = [
            int(el.strip()) for el in args.road_links_ids.split(',')
            if el.isnumeric()
        ]
    else:
        road_links_ids = None
    if args.pt_links_ids is not None:
        pt_links_ids = [
            el.strip() for el in args.pt_links_ids.split(',')
            if len(el) > 0
        ]
    else:
        pt_links_ids = None
    if args.pt_lines_ids is not None:
        pt_lines_ids = [
            el.strip() for el in args.pt_lines_ids.split(',')
            if len(el) > 0
        ]
    else:
        pt_lines_ids = None

    analyze_output_basic(
        events_path=args.events_path,
        net_path=args.net_path,
        output_counts_path=args.output_counts_path,
        output_turns_path=args.output_turns_path,
        output_net_counts_path=args.output_net_counts_path,
        schedule_path=args.schedule_path,
        output_pt_counts_path=args.output_pt_counts_path,
        output_pt_net_counts_path=args.output_pt_net_counts_path,
        output_pt_stops_counts_path=args.output_pt_stops_counts_path,
        crs=args.crs,
        links_nodes_groups=links_nodes_groups,
        output_ribbon_diagrams_directory=args.output_ribbon_diagrams_directory,
        road_links_ids=road_links_ids,
        output_road_links_intensities_directory=args.output_road_links_intensities_directory,
        pt_links_ids=pt_links_ids,
        pt_lines_ids=pt_lines_ids,
        output_pt_links_intensities_directory=args.output_pt_links_intensities_directory,
        output_pt_lines_intensities_directory=args.output_pt_lines_intensities_directory,
        cordon_poly_path=args.cordon_poly_path,
        output_cordon_stats_path=args.output_cordon_stats_path,
        volume_poly_path=args.volume_poly_path,
        output_volume_stats_path=args.output_volume_stats_path,
        legs_path=args.legs_path,
        output_transfers_path=args.output_transfers_path
    )
