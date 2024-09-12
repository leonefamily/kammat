# -*- coding: utf-8 -*-
"""
Created on Tue Dec 13 17:10:43 2022

@author: dgrishchuk
"""

import sys
import argparse
from typing import List, Union
from pathlib import Path

from kammat.input.population.agent import Agent


def parse_args(
        args_from: List[str] = sys.argv[1:]
        ) -> argparse.Namespace:

    parser = argparse.ArgumentParser()

    parser.add_argument(
        "-f", "--facilities-path", required=True,
        help="Point shapefile with all facilities used in every helper files"
        )
    parser.add_argument(
        "-clu", "--clusters-path",
        help="Polygon shapefile with info about clusters for activities that are meant to consider cluster preference"
        )
    parser.add_argument(
        "-c", "--categories", required=True,
        help="CSV with soc.-eco categories per selected level of spatial precision"
        )
    parser.add_argument(
        "-m", "--modal-split-path", required=True,
        help="Modal split table"
        )
    parser.add_argument(
        "-di", "--distances-path", required=True,
        help="Commute distances"
        )
    parser.add_argument(
        "-i", "--indices-path",
        help="Indices of activities per selected level of spatial precision"
        )
    parser.add_argument(
        "-ti", "--times-path",
        help="Lastings, starts and ends of acts. Required, if diaries are not strict"
        )
    parser.add_argument(
        "-d", "--diaries-path", required=True,
        help="Population diaries/strategies. Might be usual or strict (with predefined times)"
        )
    parser.add_argument(
        "-s", "--staying-path",
        help="Agents fractions that stay home. Required, if diaries are stict"
        )
    parser.add_argument(
        "-tp", "--transit-points-path",
        help="Transit points matrix"
        )
    parser.add_argument(
        "-cp", "--citylog-points-path",
        help="City logistics bases"
        )
    parser.add_argument(
        "-fp", "--freight-points-path",
        help="Freight points matrix"
        )
    parser.add_argument(
        "-tc", "-time-courses-path",
        help="Transit time distributions. Required, if any transit is used"
        )
    parser.add_argument(
        "-cl", "-city-logistics-path",
        help="Data about city logistics"
        )
    parser.add_argument(
        "-sp", "-spatial-polygons-path",
        help="Zone polygons for analysis"
        )
    parser.add_argument(
        "-g", "-gtfs-folder-path",
        help="GTFS folder"  # !!! this or just stops?
        )
    parser.add_argument(
        "-ac", '--agents-csv-path',
        help="Save CSV"
        )
    parser.add_argument(
        "-ax", '--agents-xml-path',
        help="Save XML")
    parser.add_argument(
        "-t", '--threads', type=int, default=1,
        help="How many threads to use"
        )
    parser.add_argument(
        "-n", '--net-path', help="MATSim network to use routing"
        )
    parser.add_argument(
        "-psr", "--pt-stops-routing", action='store_true',
        help="Find links to closest/frequent stops"
        )  # !!! keep or no?

    args = parser.parse_args(args_from)

    return args


def main(facilities_path: Union[str, Path] = None,
         clusters_path: Union[str, Path] = None,
         citylog_points_path: Union[str, Path] = None,
         freight_points_path: Union[str, Path] = None,
         transit_points_path: Union[str, Path] = None,
         categories_path: Union[str, Path] = None,
         diaries_path: Union[str, Path] = None,
         staying_path: Union[str, Path] = None,
         target_probabilities_path: Union[str, Path] = None,
         distances_path: Union[str, Path] = None,
         time_courses_path: Union[str, Path] = None,
         city_logistics_path: Union[str, Path] = None,
         times_path: Union[str, Path] = None,
         modal_split_path: Union[str, Path] = None,
         index_path: Union[str, Path] = None
         ) -> List[Agent]:
    
    pass


if __name__ == '__main__':
    args = parse_args()
    main(
        
        
        
        )