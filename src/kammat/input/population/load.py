# -*- coding: utf-8 -*-
"""
Created on Wed Mar  1 17:59:02 2023

@author: dgrishchuk
"""

import sys
import argparse
import geopandas as gpd
from pathlib import Path
from typing import Union, Tuple, Dict, List

from kammat.input.data.load import load_data
from kammat.input.data.types import Helpers
from kammat.input.population.agent import (
    csv_header, save_csv, write_agents
    )
from kammat.input.population.prepare import (
    prepare_and_handle_agents, Agent
    )
from kammat.input.population.utils import save_pickle
from kammat.input.population.analysis import (
    analyze_population_basic
    )


def parse_args(
        args_list: List[str] = sys.argv[1:]
        ) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-f', '--facilities-path')
    parser.add_argument('-c', '--categories-path')
    parser.add_argument('-d', '--diaries-path')
    parser.add_argument('-D', '--distances-path')
    parser.add_argument('-X', '--xml-path')
    parser.add_argument('-C', '--csv-path')
    parser.add_argument('-P', '--pickle-path')
    parser.add_argument('-m', '--modal-split-path')
    parser.add_argument('-ms', '--modal-split-save-path')
    parser.add_argument('-fc', '--facilities-counts-save-path')
    parser.add_argument('-rm', '--relational-matrices-save-directory')
    parser.add_argument('-cu', '--clusters-path')
    parser.add_argument('-cp', '--citylog-points-path')
    parser.add_argument('-fp', '--freight-points-path')
    parser.add_argument('-tp', '--transit-points-path')
    parser.add_argument('-s', '--staying-path')
    parser.add_argument('-T', '--target-probabilities-path')
    parser.add_argument('-tc', '--time-courses-path')
    parser.add_argument('-cl', '--city-logistics-path')
    parser.add_argument('-t', '--times-path')
    parser.add_argument('-i', '--indices-path')
    parser.add_argument('-r', '--relations-path')
    parser.add_argument('-st', '--stops-path')
    parser.add_argument('-of', '--oneway-flows-path')
    parser.add_argument('-N', '--ncores', type=int, default=1)
    parser.add_argument('-S', '--sample', type=float, default=1.)
    parser.add_argument('-it', '--include-teleported', action='store_true')
    parser.add_argument('-ur', '--use-regr', action='store_true')
    args = parser.parse_args(args_list)
    return args


def handle_population(
        facilities_path: Union[str, Path],
        categories_path: Union[str, Path],
        diaries_path: Union[str, Path],
        distances_path: Union[str, Path],
        xml_path: Union[str, Path],
        csv_path: Union[str, Path],
        modal_split_save_path: Union[str, Path],
        facilities_counts_save_path: Union[str, Path],
        relational_matrices_save_directory: Union[str, Path],
        clusters_path: Union[str, Path] = None,
        citylog_points_path: Union[str, Path] = None,
        freight_points_path: Union[str, Path] = None,
        transit_points_path: Union[str, Path] = None,
        staying_path: Union[str, Path] = None,
        target_probabilities_path: Union[str, Path] = None,
        time_courses_path: Union[str, Path] = None,
        city_logistics_path: Union[str, Path] = None,
        times_path: Union[str, Path] = None,
        modal_split_path: Union[str, Path] = None,
        indices_path: Union[str, Path] = None,
        relations_path: Union[str, Path] = None,
        stops_path: Union[str, Path] = None,
        oneway_flows_path: Union[str, Path] = None,
        ncores: int = 1,
        sample: float = 1.0,
        pickle_path: Union[str, Path] = None,
        **kwargs
        ) -> Tuple[Dict[str, gpd.GeoDataFrame], Helpers, Dict[str, List[Agent]]]:
    facilities, h = load_data(
        facilities_path, categories_path, diaries_path, distances_path,
        clusters_path, citylog_points_path, freight_points_path,
        transit_points_path, staying_path, target_probabilities_path,
        time_courses_path, city_logistics_path, times_path,
        modal_split_path, indices_path, relations_path, stops_path,
        oneway_flows_path
    )
    population = prepare_and_handle_agents(
        facilities, h, ncores, sample, **kwargs
        )
    if xml_path is not None:
        write_agents(
            population['additional'] + population['regular'],
            file=xml_path,
            including_start_end=True
        )
    if pickle_path is not None:
        save_pickle(population, pickle_path)
    if csv_path is not None:
        maxlen = max(len(a.facilities) for a in population['regular'])
        csv_header(maxlen, csv_path)
        save_csv(population['regular'], csv_path)
    analyze_population_basic(
        population, facilities, modal_split_save_path,
        facilities_counts_save_path, relational_matrices_save_directory
        )
    return facilities, h, population


if __name__ == '__main__':
    args = parse_args()
    handle_population(
        facilities_path=args.facilities_path,
        categories_path=args.categories_path,
        diaries_path=args.diaries_path,
        distances_path=args.distances_path,
        xml_path=args.xml_path,
        csv_path=args.csv_path,
        modal_split_path=args.modal_split_path,
        modal_split_save_path=args.modal_split_save_path,
        facilities_counts_save_path=args.facilities_counts_save_path,
        relational_matrices_save_directory=args.relational_matrices_save_directory,
        clusters_path=args.clusters_path,
        citylog_points_path=args.citylog_points_path,
        freight_points_path=args.freight_points_path,
        transit_points_path=args.transit_points_path,
        staying_path=args.staying_path,
        target_probabilities_path=args.target_probabilities_path,
        time_courses_path=args.time_courses_path,
        city_logistics_path=args.city_logistics_path,
        times_path=args.times_path,
        indices_path=args.indices_path,
        relations_path=args.relations_path,
        stops_path=args.stops_path,
        ncores=args.ncores,
        sample=args.sample,
        include_teleported=args.include_teleported,
        pickle_path=args.pickle_path
        )
