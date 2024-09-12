# -*- coding: utf-8 -*-
"""
Created on Tue Mar 21 11:51:32 2023

@author: dgrishchuk
"""

import os
import sys
import argparse
from pathlib import Path
from typing import List, Union
from kammat.model.pt2matsim import (
    run_pt2matsim, ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH
    )
from kammat.model.vehicles import (
    load_modify_and_save_vehicles, ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH
    )


def parse_args(
        args_list: List[str] = sys.argv[1:]
        ) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument('-e', '--executable-path',
                        default=ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH)
    parser.add_argument('-g', '--gtfs-folder')
    parser.add_argument('-n', '--net-path')
    parser.add_argument('-N', '--output-net-path')
    parser.add_argument('-S', '--output-schedule-path')
    parser.add_argument('-V', '--output-vehicles-path')
    parser.add_argument('-v', '--default-vehicles-path',
                        default=ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH)
    parser.add_argument('-t', '--number-of-threads', type=int,
                        default=os.cpu_count() - 2)
    args = parser.parse_args(args_list)
    return args


def handle_pt(
        net_path: Union[str, Path],
        gtfs_folder: Union[str, Path],
        output_net_path: Union[str, Path],
        output_schedule_path: Union[str, Path],
        output_vehicles_path: Union[str, Path],
        number_of_threads: int = os.cpu_count() - 2,
        executable_path: Union[str, Path] = ABSOLUTE_PT2MATSIM_EXECUTABLE_PATH,
        default_vehicles_path: Union[str, Path] = ABSOLUTE_EXAMPLE_MATSIM_VEHICLES_PATH
        ):
    run_pt2matsim(
        net_path,
        gtfs_folder,
        output_net_path,
        output_schedule_path,
        output_vehicles_path,
        number_of_threads,
        executable_path
        )
    load_modify_and_save_vehicles(
        existing_vehicles_path=str(output_vehicles_path),
        output_vehicles_path=str(output_vehicles_path),
        default_vehicles_path=str(default_vehicles_path)
        )


if __name__ == '__main__':
    args = parse_args()
    handle_pt(
        net_path=args.net_path,
        gtfs_folder=args.gtfs_folder,
        output_net_path=args.output_net_path,
        output_schedule_path=args.output_schedule_path,
        output_vehicles_path=args.output_vehicles_path,
        executable_path=args.executable_path,
        default_vehicles_path=args.default_vehicles_path
        )
