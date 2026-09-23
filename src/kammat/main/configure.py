#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May  7 18:05:36 2024

@author: leonefamily
"""

import json
import os
import sys
from pathlib import Path
from dataclasses import fields
from typing import Dict, Union, List, Optional, Any
from kammat.defaults.constants import DEFAULT_DIRECTORIES, STAGES_ARGUMENTS, C, PurePath


Config = Dict[str, Dict[str, Union[str, Path, int, float, bool]]]


def load_config(
        p: Union[Path, str]
) -> Config:
    """
    Load JSON configuration for this framework.

    Does not (yet) guarantee that the structure is correct.

    Parameters
    ----------
    p : Union[Path, str]
        Path to the JSON file.

    Returns
    -------
    Dict[str, Any]

    """
    with open(p, mode='r', encoding='utf-8') as fp:
        config = json.load(fp)
    return config


def save_config(
        config: Config,
        p: Union[Path, str]
):
    """
    Load JSON configuration for this framework.

    Does not (yet) guarantee that the structure is correct.

    Parameters
    ----------
    config : Dict[str, Any]
        Config dictionary
    p : Union[Path, str]
        Path to save the JSON file.

    """
    with open(p, mode='w', encoding='utf-8') as fp:
        json.dump(config, fp=fp, indent=4, default=str)  # if Path or other non-standard class, saves as str


def ensure_is_file(
        p: Union[Path, str],
        check_exists: bool = False,
        check_parent_exists: bool = False,
        expl: Optional[str] = ''
):
    """
    Make sure that the passed path corresponds to file name and nothing other.
    
    Raises an exception if something is wrong.

    Parameters
    ----------
    p : Union[Path, str]
        Path to check.
    check_exists : bool, optional
        Whether the file existence needs to be checked. The default is False.
    check_parent_exists : bool, optional
        Whether the file's parent directory existence needs to be checked.
        The default is False.
    expl : Optional[str], optional
        Explanation that is shown if check is failed. The default is ''.
        Appears as a string ``, (<expl>)`` when non empty <expl> used.

    Raises
    ------
    FileNotFoundError
        If parent directory of the file or the file itself is missing.
    RuntimeError
        If the path is not file (e.g. directory)

    """
    pp = Path(p).resolve()
    expl_braces = f', ({expl})' if expl else ''
    if check_exists and not pp.exists():
        raise FileNotFoundError(f'{p} file does not exist{expl_braces}')
    if check_parent_exists and not pp.parent.exists():
        raise FileNotFoundError(
            f'Parent folder of {p} does not exist{expl_braces}'
        )
    if not pp.is_file() and pp.suffix == '':
        raise RuntimeError(f'{p} was supposed to be a file{expl_braces}')


def ensure_is_directory(
        p: Union[Path, str],
        check_exists: bool = False,
        expl: Optional[str] = ''
):
    """
    Make sure that the passed path corresponds to directory name.

    Raises an exception if something is wrong.

    Parameters
    ----------
    p : Union[Path, str]
        Path to check.
    check_exists : bool, optional
        Whether the directory existence needs to be checked.
        The default is False.
    expl : Optional[str], optional
        Explanation that is shown if check is failed. The default is ''.
        Appears as a string ``, (<expl>)`` when non empty <expl> used.

    Raises
    ------
    FileNotFoundError
        If parent directory of the file or the file itself is missing.
    RuntimeError
        If the path is not directory (e.g. is file)

    """
    pp = Path(p).resolve()
    expl_braces = f', ({expl})' if expl else ''
    if check_exists and not pp.exists():
        raise FileNotFoundError(f'{p} directory does not exist{expl_braces}')
    if not pp.is_directory() and pp.suffix != '':
        raise RuntimeError(f'{p} was supposed to be a directory{expl_braces}')


def validate_config(
        config: Config
) -> Config:
    """
    Try to ensure that framework doesn't fail due to a wrong argument.

    Parameters
    ----------
    config : Config
        Configuration dictionary

    Raises
    ------
    RuntimeError
        Fail if something is wrong.

    Returns
    -------
    List[str]
        List of stages to run.

    """
    stages = [
       stage for stage in STAGES_ARGUMENTS if
       stage in config and
       'launch' in config[stage] and
       config[stage]['launch'] is True
    ]

    main_net_path = None
    if 'network' in stages:
        if config['network']['existing']:
            main_net_path = Path(config['network']['net_save_path']).resolve()
            ensure_is_file(
                main_net_path, check_exists=True, expl='newtork/net_save_path'
            )

    # !!! TODO more checks
    return stages


def default_run_directories(
        parent: Union[str, Path],
        create: bool = False,
        exist_ok: bool = False
) -> Dict[str, Path]:
    parent_path = Path(parent).resolve()
    # subfolders must be placed after respective parents
    # so they are created after parents already exist
    dirs = {
        'root': parent_path,
        'network': parent_path / DEFAULT_DIRECTORIES['network'],
        'population': parent_path / DEFAULT_DIRECTORIES['population'],
        'model': parent_path / DEFAULT_DIRECTORIES['model'],
        'analysis': parent_path / DEFAULT_DIRECTORIES['analysis'],
        'comparison': parent_path / DEFAULT_DIRECTORIES['comparison'],
        'nodes': parent_path / DEFAULT_DIRECTORIES['nodes'],
        'links': parent_path / DEFAULT_DIRECTORIES['links'],
        'road_links': parent_path / DEFAULT_DIRECTORIES['road_links'],
        'pt_links': parent_path / DEFAULT_DIRECTORIES['pt_links']
    }
    if create:
        parent_path.mkdir(exist_ok=exist_ok)
        for name, path in dirs.items():
            path.mkdir(exist_ok=exist_ok)
    return dirs


def validate_path(
        p: Optional[Union[str, Path, PurePath]]
) -> Optional[Path]:
    if p is None:
        return None
    if not Path(PurePath(p)).exists():
        raise ValueError('File/directory does not exist')
    return Path(p)


def default_run_config(
        parent: Union[str, Path] = os.path.curdir
) -> Dict[str, Dict[str, Optional[Union[str, Path, int, float, bool]]]]:
    parent_path = Path(parent).resolve()

    config: Dict[str, Any] = {
        'wd': default_run_directories(parent=parent_path, create=False)
    }

    for stage in STAGES_ARGUMENTS:
        config[stage] = {}
        class_name = stage if stage not in ('config', 'model') else 'matsim'
        if hasattr(C, class_name):
            dc_class = getattr(C, class_name)
            dc_fields = {f.name for f in fields(dc_class)}
            for param in STAGES_ARGUMENTS[stage]:
                if param in dc_fields:
                    val = getattr(dc_class, param)
                    if isinstance(val, PurePath):
                        config[stage][param] = parent_path / val
                    else:
                        config[stage][param] = val
                elif param == 'launch':
                    config[stage][param] = True
                elif param == 'existing':
                    config[stage][param] = False
                else:
                    config[stage][param] = None  # not in C -> None
    config['pt']['net_path'] = config['network']['net_save_path']
    config['pt']['output_net_path'] = config['network']['net_save_path']  # it'll save changed file at the same place
    config['population']['ncores'] = C.kammat.cpu_threads
    config['config']['net_path'] = config['network']['net_save_path']
    config['config']['lane_definitions_path'] = config['network']['lane_definitions_save_path']
    config['config']['population_path'] = config['population']['xml_path']
    config['config']['schedule_path'] = config['pt']['output_schedule_path']
    config['config']['vehicles_path'] = config['pt']['output_vehicles_path']
    config['config']['output_config_path'] = config['model']['config_path']
    config['model']['ram_limit'] = C.matsim.ram_limit_str
    config['comparison']['edge_net_path'] = config['network']['edges_save_path']
    config['comparison']['net_counts_path'] = config['analysis']['output_net_counts_path']
    config['comparison']['pt_net_counts_path'] = config['analysis']['output_pt_net_counts_path']
    config['comparison']['pt_stops_counts_path'] = config['analysis']['output_pt_stops_counts_path']
    config['gis']['input_facilities'] = config['population']['facilities_counts_save_path']
    config['gis']['input_edges'] = config['network']['edges_save_path']
    config['gis']['input_nodes'] = config['network']['nodes_save_path']
    config['gis']['output_road_counts'] = config['analysis']['output_net_counts_path']
    config['gis']['output_pt_counts'] = config['analysis']['output_pt_net_counts_path']
    config['gis']['output_pt_stops'] = config['analysis']['output_pt_stops_counts_path']
    config['gis']['output_cordons_stats'] = config['analysis']['output_cordon_stats_path']
    config['gis']['output_volumes_stats'] = config['analysis']['output_volume_stats_path']
    config['gis']['comparison_rw_road_diffs'] = config['comparison']['network_differences_save_path']
    config['gis']['comparison_rw_road_intersection_diffs'] = config['comparison']['intersection_differences_save_path']
    config['gis']['comparison_model_road_diffs'] = config['comparison']['diff_net_counts_save_path']
    config['gis']['comparison_model_pt_diffs'] = config['comparison']['diff_pt_net_counts_save_path']
    config['gis']['comparison_model_pt_stops_diffs'] = config['comparison']['diff_pt_stops_counts_save_path']
    return config


def populate_default_config(
        parent: Union[str, Path] = os.path.curdir,
        net_shp_path: Optional[Union[str, Path]] = None,
        net_lane_connections_path: Optional[Union[str, Path]] = None,
        net_type: str = C.network.nettype,
        net_restrict_uturns: bool = True,
        net_internal_maneuvers: bool = True,
        existing_pt_schedule_path: Optional[Union[str, Path]] = None,
        existing_pt_vehicles_path: Optional[Union[str, Path]] = None,
        existing_net_save_path: Optional[Union[str, Path]] = None,
        existing_lane_definitions_save_path: Optional[Union[str, Path]] = None,
        gtfs_path: Optional[Union[str, Path]] = None,
        kammat_number_of_threads: int = C.kammat.cpu_threads,
        pop_variables_path: Optional[Union[str, Path]] = None,
        pop_include_teleported: bool = C.population.include_teleported,
        pop_facilities_path: Optional[Union[str, Path]] = None,
        pop_categories_path: Optional[Union[str, Path]] = None,
        pop_diaries_path: Optional[Union[str, Path]] = None,
        pop_distances_path: Optional[Union[str, Path]] = None,
        pop_clusters_path: Optional[Union[str, Path]] = None,
        pop_citylog_points_path: Optional[Union[str, Path]] = None,
        pop_freight_points_path: Optional[Union[str, Path]] = None,
        pop_transit_points_path: Optional[Union[str, Path]] = None,
        pop_staying_path: Optional[Union[str, Path]] = None,
        pop_target_probabilities_path: Optional[Union[str, Path]] = None,
        pop_time_courses_path: Optional[Union[str, Path]] = None,
        pop_city_logistics_path: Optional[Union[str, Path]] = None,
        pop_times_path: Optional[Union[str, Path]] = None,
        pop_modal_split_path: Optional[Union[str, Path]] = None,
        pop_indices_path: Optional[Union[str, Path]] = None,
        pop_relations_path: Optional[Union[str, Path]] = None,
        pop_stops_path: Optional[Union[str, Path]] = None,
        pop_oneway_flows_path: Optional[Union[str, Path]] = None,
        pop_sample: Union[int, float] = C.population.sample,
        pop_incremental_capacity_allocation_parts: int = C.population.incremental_capacity_allocation_parts,
        existing_pop_xml_path: Optional[Union[str, Path]] = None,
        matsim_number_of_threads: int = C.matsim.number_of_threads,
        matsim_last_iteration: int = C.matsim.last_iteration,
        matsim_scoring_parameters_path: Optional[Union[str, Path]] = None,
        matsim_minibus_parameters_path: Optional[Union[str, Path]] = None,
        matsim_launch: bool = False,
        matsim_executable_path: Optional[Union[str, Path]] = None,
        matsim_ram_limit: str = C.matsim.ram_limit,
        qgis_path: Optional[Union[str, Path]] = None,
        previous_run_config_path: Optional[Union[str, Path]] = None,
) -> Dict[str, Dict[str, Optional[Union[str, Path, int, float]]]]:
    parent_path = Path(parent).resolve()
    config = default_run_config(parent=parent_path)
    if existing_net_save_path is not None:
        config['network']['net_save_path'] = validate_path(existing_net_save_path)
        config['network']['lane_definitions_save_path'] = validate_path(
            existing_lane_definitions_save_path
        )
        config['network']['existing'] = True
        config['network']['launch'] = False
    else:
        config['network']['shp_path'] = validate_path(net_shp_path)
        config['network']['lane_connections_path'] = validate_path(net_lane_connections_path)
        config['network']['nettype'] = net_type
        config['network']['restrict_uturns'] = bool(net_restrict_uturns)
        config['network']['internal_maneuvers'] = net_internal_maneuvers
    if gtfs_path is not None:
        config['pt']['gtfs_folder'] = validate_path(gtfs_path)
        config['pt']['number_of_threads'] = int(kammat_number_of_threads)
    else:
        config['pt']['output_schedule_path'] = validate_path(existing_pt_schedule_path)
        config['pt']['output_vehicles_path'] = validate_path(existing_pt_vehicles_path)

    if existing_pop_xml_path is None:
        config['population']['variables_path'] = validate_path(pop_variables_path)
        config['population']['include_teleported'] = pop_include_teleported
        config['population']['facilities_path'] = validate_path(pop_facilities_path)
        config['population']['categories_path'] = validate_path(pop_categories_path)
        config['population']['diaries_path'] = validate_path(pop_diaries_path)
        config['population']['distances_path'] = validate_path(pop_distances_path)
        config['population']['clusters_path'] = validate_path(pop_clusters_path)
        config['population']['citylog_points_path'] = validate_path(pop_citylog_points_path)
        config['population']['freight_points_path'] = validate_path(pop_freight_points_path)
        config['population']['transit_points_path'] = validate_path(pop_transit_points_path)
        config['population']['staying_path'] = validate_path(pop_staying_path)
        config['population']['target_probabilities_path'] = validate_path(pop_target_probabilities_path)
        config['population']['time_courses_path'] = validate_path(pop_time_courses_path)
        config['population']['city_logistics_path'] = validate_path(pop_city_logistics_path)
        config['population']['times_path'] = validate_path(pop_times_path)
        config['population']['modal_split_path'] = validate_path(pop_modal_split_path)
        config['population']['indices_path'] = validate_path(pop_indices_path)
        config['population']['relations_path'] = validate_path(pop_relations_path)
        config['population']['stops_path'] = validate_path(pop_stops_path)
        config['population']['oneway_flows_path'] = validate_path(pop_oneway_flows_path)
        config['population']['sample'] = float(pop_sample)
        config['population']['incremental_capacity_allocation_parts'] = int(pop_incremental_capacity_allocation_parts)
        config['population']['ncores'] = int(kammat_number_of_threads)
    else:
        config['population']['xml_path'] = validate_path(existing_pop_xml_path)
        config['population']['launch'] = False
        config['population']['existing'] = True
    config['config']['number_of_threads'] = int(matsim_number_of_threads)
    config['config']['last_iteration'] = int(matsim_last_iteration)
    config['config']['scoring_parameters_path'] = validate_path(matsim_scoring_parameters_path)
    config['config']['minibus_parameters_path'] = validate_path(matsim_minibus_parameters_path)
    config['model']['launch'] = matsim_launch
    if matsim_launch and matsim_executable_path is None:
        raise ValueError('MATSim executable path is necessary when run requested')
    config['model']['executable_path'] = validate_path(matsim_executable_path)
    config['model']['ram_limit'] = matsim_ram_limit

    if previous_run_config_path is not None:
        prev_config = load_config(previous_run_config_path)
        config['comparison']['prev_net_counts_path'] = validate_path(
            prev_config['analysis']['output_net_counts_path']
        )
        config['comparison']['prev_pt_net_counts_path'] = validate_path(
            prev_config['analysis']['output_pt_net_counts_path']
        )
        config['comparison']['prev_pt_stops_counts_path'] = validate_path(
            prev_config['analysis']['output_pt_stops_counts_path']
        )
        config['comparison']['pt_net_counts_path'] = validate_path(
            prev_config['analysis']['output_pt_net_counts_path']
        )
        config['comparison']['pt_stops_counts_path'] = validate_path(
            prev_config['analysis']['output_pt_stops_counts_path']
        )
    if not matsim_launch:
        config['analysis']['launch'] = matsim_launch
        config['comparison']['launch'] = matsim_launch
        config['gis']['launch'] = matsim_launch
    else:
        if not sys.platform.lower().startswith('win'):
            config['gis']['qgis_path'] = validate_path(qgis_path)
    return config
