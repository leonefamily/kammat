#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Tue May  7 18:05:36 2024

@author: leonefamily
"""

import json
from pathlib import Path
from typing import Dict, List, Union, Any, Optional
from kammat.defaults.constants import (
    STAGES_ARGUMENTS
)

Config = Dict[str, Dict[str, Union[str, int, float, bool]]]


def load_config(
        p: Union[Path, str]
) -> Dict[str, Any]:
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
        main_net_path = Path(config['network']['net_save_path']).resolve()
        ensure_is_file(
            main_net_path, check_exists=True, expl='newtork/net_save_path'
        )
    if 'pt' in stages:
        pt_net_path = Path(config['pt']['net_path']).resolve()
        ensure_is_file(
            pt_net_path, check_exists=True, expl='pt/net_path'
        )
        if main_net_path is not None and pt_net_path != main_net_path:
            raise RuntimeError(
                'newtork/net_save_path is not equal to pt/net_path'
            )

        out_pt_net_path = Path(config['pt']['output_net_path']).resolve()
        ensure_is_file(
            out_pt_net_path, check_parent_exists=True, expl='pt/output_net_path'
        )
        main_net_path = out_pt_net_path

    # !!! TODO more checks

    return stages

    # # Network
    # net_keys = set(
    #     inspect.getargs(prepare_generic_network.__code__).args +
    #     inspect.getargs(prepare_ceda_network.__code__).args
    # )
    # if values['-USENET-']:
    #     enet = Path(values['-ENETPATH-'])
    #     try:
    #         nvvs = load_run_settings(enet.parent.parent / 'settings.json')
    #         for key, value in nvvs['network'].items():
    #             vvs['network'][key] = value
    #         msgs['info'].append('Using existing network')
    #     except FileNotFoundError:
    #         msgs['warning'].append(
    #             'Using existing network, but the structure of files does not '
    #             'seem to correspond with this framework. Continuing anyways, '
    #             'but some analyses will not be possible - e.g. merging with '
    #             'original shapefile, intensities comparison etc.'
    #         )
    #         for key in net_keys:
    #             vvs['network'][key] = None
    #     vvs['network']['net_save_path'] = enet
    #     vvs['network']['existing'] = True
    # else:
    #     vvs['network']['shp_path'] = Path(values['-NETPATH-'])
    #     vvs['network']['nettype'] = 'generic' if values['-NETGEN-'] else 'ceda'
    #     if vvs['network']['nettype'] == 'generic':
    #         vvs['network']['restrict_uturns'] = values['-UTURNS-']
    #     elif vvs['network']['nettype'] == 'ceda':
    #         vvs['network']['ncores'] = int(values['-THREADS-'])
    #         if values['-LCONPATH-']:
    #             vvs['network']['lane_connections_path'] = values['-LCONPATH-']
    #             vvs['network']['lane_definitions_save_path'] = wd_net / 'lane_definitions.xml'
    #         else:
    #             vvs['network']['lane_connections_path'] = None
    #             vvs['network']['lane_definitions_save_path'] = None
    #         vvs['network']['internal_maneuvers'] = values['-SIMPLEINT-']
    #     vvs['network']['edges_save_path'] = wd_net / 'edges.shp'
    #     vvs['network']['nodes_save_path'] = wd_net / 'nodes.shp'
    #     vvs['network']['net_save_path'] = wd_net / 'net.xml'

    #     vvs['network']['existing'] = False

    # # Public transport, schedules, vehicles
    # if values['-GTFSPATH-'] and not values['-USENET-']:
    #     vvs['pt']['gtfs_folder'] = values['-GTFSPATH-']
    #     vvs['pt']['output_schedule_path'] = wd_net / 'schedule.xml'
    #     vvs['pt']['output_vehicles_path'] = wd_net / 'vehicles.xml'
    # else:
    #     msgs['info'].append('Using existing schedule and vehicles')
    #     vvs['pt']['gtfs_folder'] = None
    #     vvs['pt']['output_schedule_path'] = None
    #     vvs['pt']['output_vehicles_path'] = None
    # vvs['pt']['number_of_threads'] = int(values['-THREADS-'])
    # vvs['pt']['net_path'] = vvs['network']['net_save_path']
    # vvs['pt']['output_net_path'] = vvs['network']['net_save_path']

    # # Population
    # pop_keys = inspect.getargs(handle_population.__code__).args
    # if values['-USEPOP-']:
    #     epop = Path(values['-EPOPPATH-'])
    #     try:
    #         pvvs = load_run_settings(epop.parent.parent / 'settings.json')
    #         for key, value in pvvs['population'].items():
    #             vvs['population'][key] = value
    #         msgs['info'].append('Using existing population')
    #     except FileNotFoundError:
    #         msgs['warning'].append(
    #             'Using existing population, but the structure of files does not '
    #             'seem to correspond with this framework. Continuing anyways, '
    #             'but some analyses will not be possible - e.g. merging with '
    #             'original shapefile, intensities comparison etc.'
    #         )
    #         for key in pop_keys:
    #             vvs['population'][key] = None
    #     vvs['population']['xml_path'] = epop
    #     vvs['population']['existing'] = True
    # else:
    #     vvs['population']['existing'] = False
    #     vvs['population']['include_teleported'] = values['-WRITETP-']
    #     vvs['population']['use_regr'] = values['-USEREGR-']
    #     vvs['population']['xml_path'] = wd_population / 'population.xml'
    #     vvs['population']['csv_path'] = wd_population / 'population.csv'
    #     vvs['population']['pickle_path'] = wd_population / 'population.zx'
    #     vvs['population']['facilities_path'] = values['-POPPATH-']
    #     vvs['population']['categories_path'] = values['-CATPATH-']
    #     vvs['population']['diaries_path'] = values['-DIARPATH-']
    #     vvs['population']['distances_path'] = values['-DISTPATH-']
    #     vvs['population']['clusters_path'] = values['-CLUSTPATH-']
    #     vvs['population']['citylog_points_path'] = values['-CLOGSPATH-']
    #     vvs['population']['freight_points_path'] = values['-FREPATH-']
    #     vvs['population']['transit_points_path'] = values['-TRANPATH-']
    #     vvs['population']['staying_path'] = values['-STAYPATH-']
    #     vvs['population']['target_probabilities_path'] = values['-TARGPATH-']
    #     vvs['population']['time_courses_path'] = values['-TCOURPATH-']
    #     vvs['population']['city_logistics_path'] = values['-CLOGPATH-']
    #     vvs['population']['times_path'] = values['-TIMEPATH-']
    #     vvs['population']['modal_split_path'] = values['-MSPATH-']
    #     vvs['population']['indices_path'] = values['-INDPATH-']
    #     vvs['population']['relations_path'] = values['-RELPATH-']
    #     vvs['population']['stops_path'] = values['-STOPPATH-']
    #     vvs['population']['sample'] = values['-POPFRAC-']
    #     vvs['population']['modal_split_save_path'] = wd_population / 'modal_split.csv'
    #     vvs['population']['facilities_counts_save_path'] = wd_population / 'facilities_counts.shp'
    #     vvs['population']['relational_matrices_save_directory'] = wd_population / 'relations'
    # vvs['population']['ncores'] = int(values['-THREADS-'])

    # # Configuration
    # vvs['config']['net_path'] = vvs['network']['net_save_path']
    # vvs['config']['population_path'] = vvs['population']['xml_path']
    # vvs['config']['number_of_threads'] = int(values['-THREADS-'])
    # vvs['config']['last_iteration'] = int(values['-ITERS-'] - 1)
    # vvs['config']['output_config_path'] = wd / 'config.xml'
    # vvs['config']['matsim_output_directory'] = run_dir
    # vvs['config']['schedule_path'] = vvs['pt']['output_schedule_path']
    # vvs['config']['vehicles_path'] = vvs['pt']['output_vehicles_path']
    # vvs['config']['lane_definitions_path'] = (
    #     vvs['network']['lane_definitions_save_path']
    #     if 'lane_definitions_save_path' in vvs['network'] else None
    # )
    # vvs['config']['write_events_interval'] = vvs['config']['last_iteration']
    # vvs['config']['disable_innovations_after_fraction'] = values['-MUTFRAC-']
    # vvs['config']['mutation_range'] = values['-TIMEMUT-'] * 60

    # # Model
    # vvs['model']['launch'] = values['-RUNMOD-']
    # vvs['model']['executable_path'] = values['-MATSIMPATH-']
    # vvs['model']['config_path'] = vvs['config']['output_config_path']
    # vvs['model']['ram_limit'] = f"{int(values['-MATSIMRAM-'])}m"

    # # Analysis
    # vvs['analysis']['launch'] = values['-ANALYZE-'] if values['-RUNMOD-'] else False
    # vvs['analysis']['events_path'] = vvs['config']['matsim_output_directory'] / 'output_events.xml.gz'
    # vvs['analysis']['net_path'] = vvs['config']['matsim_output_directory'] / 'output_network.xml.gz'
    # vvs['analysis']['output_counts_path'] = an_dir / 'counts.json'
    # vvs['analysis']['output_turns_path'] = an_dir / 'turns.json'
    # vvs['analysis']['output_net_counts_path'] = an_dir / 'counts.shp'
    # vvs['analysis']['schedule_path'] = vvs['config']['schedule_path']
    # vvs['analysis']['output_pt_counts_path'] = an_dir / 'pt.json'
    # vvs['analysis']['output_pt_net_counts_path'] = an_dir / 'pt.shp'
    # vvs['analysis']['output_pt_stops_counts_path'] = an_dir / 'pt_stops.shp'
    # vvs['analysis']['links_nodes_groups'] = values['-LINKGROUPS-'] if values['-LINKGROUPS-'] else None
    # vvs['analysis']['output_ribbon_diagrams_directory'] = rd_dir
    # vvs['analysis']['road_links_ids'] = values['-LINKINTENS-'] if values['-LINKINTENS-'] else None
    # vvs['analysis']['output_road_links_intensities_directory'] = rl_dir
    # vvs['analysis']['pt_links_ids'] = values['-PTLINKINTENS-'] if values['-PTLINKINTENS-'] else None
    # vvs['analysis']['output_pt_links_intensities_directory'] = ptl_dir
    # vvs['analysis']['output_pt_lines_intensities_directory'] = ptl_dir
    # vvs['analysis']['pt_lines_ids'] = values['-PTLINEINTENS-'] if values['-LINKGROUPS-'] else None
    # vvs['analysis']['cordon_poly_path'] = values['-CORDPOLYPATH-'] if values['-CORDPOLYPATH-'] else None
    # vvs['analysis']['output_cordon_stats_path'] = an_dir / 'cordons_stats.shp'
    # vvs['analysis']['volume_poly_path'] = values['-VOLPOLYPATH-'] if values['-VOLPOLYPATH-'] else None
    # vvs['analysis']['output_volume_stats_path'] = an_dir / 'volume_stats.shp'

    # # Comparison
    # vvs['comparison']['launch'] = values['-COMPARE-'] if values['-ANALYZE-'] else False
    # vvs['comparison']['orig_net_path'] = vvs['network']['shp_path']
    # vvs['comparison']['edge_net_path'] = vvs['network']['edges_save_path']
    # vvs['comparison']['net_counts_path'] = vvs['analysis']['output_net_counts_path']
    # vvs['comparison']['network_intensities_path'] = values['-NINTPATH-'] if values['-NINTPATH-'] else None
    # vvs['comparison']['network_differences_save_path'] = comp_dir / 'network_differences.shp'
    # vvs['comparison']['network_differences_stats_save_path'] = comp_dir / 'network_differences.csv'
    # vvs['comparison']['intersection_intensities_path'] = values['-IINTPATH-'] if values['-IINTPATH-'] else None
    # vvs['comparison']['intersection_differences_save_path'] = comp_dir / 'intersection_differences.shp'
    # vvs['comparison']['intersection_differences_stats_save_path'] = comp_dir / 'intersection_differences.csv'
    # vvs['comparison']['difference_thresh'] = 0.25
    # vvs['comparison']['diff_net_counts_save_path'] = comp_dir / 'prev_model_network_differences.shp'
    # vvs['comparison']['diff_pt_net_counts_save_path'] = comp_dir / 'prev_model_pt_network_differences.shp'
    # vvs['comparison']['diff_pt_stops_counts_save_path'] = comp_dir / 'prev_model_pt_stops_differences.shp'
    # pmod = Path(values['-PMODPATH-'])
    # try:
    #     cvvs = load_run_settings(pmod / 'settings.json')
    #     vvs['comparison']['prev_net_counts_path'] = cvvs['analysis']['output_net_counts_path']
    #     vvs['comparison']['prev_pt_net_counts_path'] = cvvs['analysis']['output_pt_net_counts_path']
    #     vvs['comparison']['prev_pt_stops_counts_path'] = cvvs['analysis']['output_pt_stops_counts_path']
    #     vvs['comparison']['pt_net_counts_path'] = vvs['analysis']['output_pt_net_counts_path']
    #     vvs['comparison']['pt_stops_counts_path'] = vvs['analysis']['output_pt_stops_counts_path']
    # except FileNotFoundError:
    #     msgs['warning'].append(
    #         'Using existing population, but the structure of files does not '
    #         'seem to correspond with this framework. Continuing anyways, '
    #         'but some analyses will not be possible - e.g. merging with '
    #         'original shapefile, intensities comparison etc.'
    #     )
    #     vvs['comparison']['prev_net_counts_path'] = None
    #     vvs['comparison']['prev_pt_net_counts_path'] = None
    #     vvs['comparison']['prev_pt_stops_counts_path'] = None
    # vvs['comparison']['pt_net_counts_path'] = vvs['analysis']['output_pt_net_counts_path']
    # vvs['comparison']['pt_stops_counts_path'] = vvs['analysis']['output_pt_stops_counts_path']

    # # GIS project
    # vvs['gis']['launch'] = values['-QGIS-']
    # vvs['gis']['qgis_path'] = values['-QGISPATH-']
    # vvs['gis']['project_path'] = wd / 'view.qgs'
    # vvs['gis']['input_facilities'] = vvs['population']['facilities_counts_save_path']
    # vvs['gis']['input_edges'] = vvs['network']['edges_save_path']
    # vvs['gis']['input_nodes'] = vvs['network']['nodes_save_path']
    # vvs['gis']['output_road_counts'] = vvs['analysis']['output_net_counts_path']
    # vvs['gis']['output_pt_counts'] = vvs['analysis']['output_pt_net_counts_path']
    # vvs['gis']['output_pt_stops'] = vvs['analysis']['output_pt_stops_counts_path']
    # vvs['gis']['output_cordons_stats'] = vvs['analysis']['output_cordon_stats_path']
    # vvs['gis']['output_volumes_stats'] = vvs['analysis']['output_volume_stats_path']
    # vvs['gis']['comparison_rw_road_diffs'] = vvs['comparison']['network_differences_save_path']
    # vvs['gis']['comparison_rw_road_intersection_diffs'] = vvs['comparison']['intersection_differences_save_path']

    # return vvs, msgs

def create_config(
):
    pass