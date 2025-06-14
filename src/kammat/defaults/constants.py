# -*- coding: utf-8 -*-
"""
Created on Tue Dec 13 18:17:02 2022

@author: dgrishchuk
"""

from typing import Tuple, List, Dict, Set, Callable, Union
from pathlib import Path
import pandas as pd 

def str_to_float(
        string: str
        ) -> float:
    try:
        return float(string)
    except ValueError:
        return float(string.replace(',', '.'))


# def str_with_nones(
#         string: str
# ) -> Union[str, None]:
#     if isinstance(string, str):
#         return string
#     elif pd.isnull(string):
#         return None
#     raise ValueError(
#         '`string` is supposed to be str, None or numpy.nan'
#     )

CSV_STYLE: Dict[str, str] = {'sep': ';', 'decimal': ','}
# csv files separator and decimal symbol convention

CATEGORIES: Tuple[str] = ('e', 'mss', 'ess', 'rh', 'us', 'pc', 'ue', 't')
# employed, middle school students, elementary school students
# retired and household people, university students, parent care,
# unemployed, toddlers

MODES: Tuple[str] = ('car', 'pt', 'walk', 'carpool', 'bike', 'truck')
# all supported modes

MODAL_SPLIT_MODES: Set[str] = {'car', 'pt', 'walk', 'carpool', 'bike'}
# modes to use in modal split table lookup

TRANSIT_MODES: Tuple[str] = ('car', 'pt', 'truck')
# transit supported modes

TIME_COURSES_MODES: Tuple[str] = ('car', 'truck')
# modes that are available in transit private plans

PRIVATE_MODES: Tuple[str] = ('car')
# all private modes out of supported

SPATIAL_LEVELS: Tuple[str] = ('zone', 'district', 'area', 'region')
# from smallest to largest

SPATIAL_LEVELS_LIST: List[str] = list(SPATIAL_LEVELS)

REGIONS: Tuple[str] = ('city', 'suburb', 'outside')
# from smallest to largest

SPATIAL_LEVELS_SCHEMA: Dict[str, Callable] = {
    sl: str for sl in SPATIAL_LEVELS
    }
# all levels must be strings


# %% DIARIES

DIARIES_COLS: Tuple[str] = ('activities', *SPATIAL_LEVELS)
# mandatory columns for non-strict diaries

STRICT_DIARIES_STATIC_COLS: Tuple[str] = ('activities', 'category',
                                          *SPATIAL_LEVELS)
# mandatory columns for strict diaries

STRICT_DIARIES_DYNAMIC_COLS: Tuple[str] = ('starttime', 'lasting')
# mandatory columns for strict diaries, that have digits as appendices

STRICT_DIARIES_OPTIONAL_COLS: Tuple[str] = ('weight',)
# optional columns for strict diaries

STRICT_DIARIES_TIME_COLS: Tuple[str] = ('starttime', 'lasting')
# dynamic columns, that have time data inside

STRICT_DIARIES_INGORE_CATEGORIES: Tuple[str] = ('t',)
# categories to be ignored, when checking categories presence

# %% FACILITIES

FACILITIES_SCHEMA: Dict[str, Callable] = SPATIAL_LEVELS_SCHEMA | {
    'capacity': int, 'index': int, 'info': str, 'facility': pd.StringDtype()
}

FACILITIES_COLUMNS: Tuple[str] = (*SPATIAL_LEVELS, 'activity', 'capacity',
                                  'index', 'info', 'facility', 'geometry')

CLUSTERS_COLUMNS: Tuple[str] = ('activity', 'geometry')

CLUSTERS_SCHEMA: Dict[str, Callable] = {'activity': str}

TRANSIT_POINTS_STATIC_COLUMNS: Tuple[str] = (*SPATIAL_LEVELS, 'info',
                                             'mode', 'facility', 'geometry')

TRANSIT_POINTS_SCHEMA: Dict[str, Callable] = SPATIAL_LEVELS_SCHEMA | {
    'facility': str, 'info': str, 'mode': str
    }

FREIGHT_POINTS_STATIC_COLUMNS: Tuple[str] = TRANSIT_POINTS_STATIC_COLUMNS

FREIGHT_POINTS_SCHEMA: Dict[str, Callable] = TRANSIT_POINTS_SCHEMA

CITYLOG_POINTS_COLUMNS: Tuple[str] = (*SPATIAL_LEVELS, 'base_type', 'base_name',
                                      'fleet_size', 'geometry')

CITYLOG_POINTS_SCHEMA: Dict[str, Callable] = SPATIAL_LEVELS_SCHEMA | {
    'base_type': str, 'base_name': str, 'fleet_size': int
    }

# %% CATEGORIES

CATEGORIES_COLUMNS: Tuple[str] = SPATIAL_LEVELS

CATEGORIES_SCHEMA: Dict[str, Callable] = SPATIAL_LEVELS_SCHEMA

# %% STAYING

STAYING_COLS: Tuple[str] = SPATIAL_LEVELS

STAYING_SCHEMA: Tuple[str] = SPATIAL_LEVELS_SCHEMA

# %% DISTANCES

DISTANCES_COLUMNS: Tuple[str] = SPATIAL_LEVELS

DISTANCES_STATISTIC_COLUMNS: Tuple[str] = ('mean', 'shape', 'scale')

DISTANCES_SCHEMA: Tuple[str] = SPATIAL_LEVELS_SCHEMA

DISTANCES_INGORE_ACTIVITIES: Tuple[str] = ('home', 'citylog')

# %% TIME COURSES

TIME_COURSES_COLUMNS: Tuple[str] = ('hour',)

TIME_COURSES_SCHEMA: Dict[str, Callable] = {'hour': int}

# %% ONEWAY FLOWS

ONEWAY_FLOWS_COLUMNS: Tuple[str] = (
    'from_activity', 'from_facility', 'to_activity', 'to_facility', 'mode', 'count'
)

ONEWAY_FLOWS_SCHEMA: Dict[str, Callable] = {
    'from_activity': str,
    'from_facility': str,
    'to_activity': str,
    'to_facility': str,
    'mode': str,
    'count': int
}

# %% TIMES

TIMES_COLUMNS: Tuple[str] = (*SPATIAL_LEVELS, 'activity',
                             'mu_lasting', 'sd_lasting',
                             'mu_start', 'sd_start',
                             'mu_end', 'sd_end')

TIMES_SCHEMA: Dict[str, Callable] = SPATIAL_LEVELS_SCHEMA | {
    'activity': str, 'mu_lasting': pd.to_timedelta, 'sd_lasting': pd.to_timedelta,
    'mu_start': pd.to_timedelta, 'sd_start': pd.to_timedelta, 'mu_end': pd.to_timedelta,
    'sd_end': pd.to_timedelta}

# %% MODAL SPLIT

MODAL_SPLIT_COLUMNS: Tuple[str] = (*SPATIAL_LEVELS, 'category')

MODAL_SPLIT_SCHEMA: Dict[str, Callable] = SPATIAL_LEVELS_SCHEMA | {
    'category': str}

# %% INDICES

INDICES_COLUMNS: Tuple[str] = ('activity', 'index', 'prob')

INDICES_SCHEMA: Dict[str, Callable] = {
    'activity': str, 'index': int, 'prob': str_to_float
    }

# %% RELATIONS

RELATIONS_COLUMNS: Tuple[str] = (*SPATIAL_LEVELS, 'prob', 'activity')

RELATIONS_SCHEMA: Dict[str, Callable] = SPATIAL_LEVELS_SCHEMA | {
        'prob': str_to_float, 'activity': str}

# %% CITY LOGISTICS

CITY_LOGISTICS_COLUMNS: Tuple[str] = ('service_type', 'service_start',
                                      'service_end', 'service_area_km',
                                      'has_base', 'vehs_number',
                                      'daily_vehkilometers', 'daily_trips',
                                      'one_ride_stops',
                                      'mean_stop_duration_min',
                                      'mean_base_cooldown_duration_min')

CITY_LOGISTICS_SCHEMA: Dict[str, Callable] = {
    "service_type": str,
    "service_start": pd.to_timedelta,
    "service_end": pd.to_timedelta,
    "service_area_km": str_to_float,
    "has_base": lambda x: bool(int(x)),
    "vehs_number": int,
    "daily_vehkilometers": str_to_float,
    "daily_trips": int,
    "one_ride_stops": int,
    "mean_stop_duration_min": str_to_float,
    "mean_base_cooldown_duration_min": str_to_float
    }

# %% STOPS

STOPS_COLUMNS: Tuple[str] = ('stop_lat', 'stop_lon')

STOPS_SCHEMA: Dict[str, Callable] = {
    'stop_lat': str_to_float, 'stop_lon': str_to_float
    }

# %% AGENTS

NO_CAR: Tuple[str] = ('ess', 'mss')

AGENTS_COLUMNS: Tuple[str] = (*SPATIAL_LEVELS, 'info', 'facility', 'x', 'y')

# %% MISC

ACTIVITY_CODE_LENGTH: int = 3

DEFAULT_QGIS_LOCATION_WINDOWS: str = r'C:\Program Files'

DEFAULT_QGIS_LOCATION_UNIX: str = '/usr/bin'

EXAMPLE_MATSIM_CONFIG_PATH: str = 'matsim/config.xml'

EXAMPLE_MATSIM_VEHICLES_PATH: str = 'matsim/vehicles.xml'
# relative to THIS file path

PT2MATSIM_CONFIG_NAME: str = 'pt2matsim.xml'

PT2MATSIM_NETWORK_NAME: str = 'network.xml'

PT2MATSIM_SCHEDULE_NAME: str = 'schedule.xml'

PT2MATSIM_VEHICLES_NAME: str = 'vehicles.xml'

PT2MATSIM_EXECUTABLE_PATH: str = '../bin/pt2matsim-22.3-shaded.jar'
# relative to THIS file path

CACHE_SETTINGS_PATH: str = str(Path.home() / '.kammat')

LOGGER_FORMAT: str = '%(asctime)s | %(levelname)s | %(name)s:%(module)s:%(lineno)d:%(funcName)s() - %(message)s'


# %% RUNTIME

STAGES_ARGUMENTS: Dict[str, List[str]] = {
    'network': [
        'shp_path',
        'nettype',
        'restrict_uturns',
        'ncores',
        'lane_connections_path',
        'lane_definitions_save_path',
        'internal_maneuvers',
        'edges_save_path',
        'nodes_save_path',
        'net_save_path',
        'existing',
        'launch'],
    'pt': [
        'gtfs_folder',
        'output_schedule_path',
        'output_vehicles_path',
        'number_of_threads',
        'net_path',
        'output_net_path',
        'launch'
    ],
    'population': [
        'gtfs_folder',
        'output_schedule_path',
        'xml_path',
        'csv_path',
        'pickle_path',
        'facilities_path',
        'categories_path',
        'diaries_path',
        'distances_path',
        'clusters_path',
        'citylog_points_path',
        'freight_points_path',
        'transit_points_path',
        'staying_path',
        'target_probabilities_path',
        'time_courses_path',
        'city_logistics_path',
        'times_path',
        'modal_split_path',
        'relations_path',
        'stops_path',
        'sample',
        'modal_split_save_path',
        'facilities_counts_save_path',
        'relational_matrices_save_directory',
        'ncores',
        'use_regr',
        'include_teleported',
        'existing',
        'launch'],
    'config': [
        'net_path',
        'population_path',
        'number_of_threads',
        'last_iteration',
        'output_config_path',
        'matsim_output_directory',
        'schedule_path',
        'vehicles_path',
        'lane_definitions_path',
        'write_events_interval',
        'disable_innovations_after_fraction',
        'mutation_range',
        'launch'],
    'model': [
        'executable_path', 'config_path', 'ram_limit', 'launch'],
    'analysis': [
        'events_path',
        'net_path',
        'output_counts_path',
        'output_turns_path',
        'output_net_counts_path',
        'schedule_path',
        'output_pt_counts_path',
        'output_pt_net_counts_path',
        'links_nodes_groups',
        'output_ribbon_diagrams_directory',
        'road_links_ids',
        'output_road_links_intensities_directory',
        'pt_links_ids',
        'output_pt_links_intensities_directory',
        'pt_lines_ids',
        'output_pt_lines_intensities_directory',
        'cordon_poly_path',
        'output_cordon_stats_path',
        'volume_poly_path',
        'output_volume_stats_path',
        'launch'],
    'comparison': [
        'orig_net_path',
        'edge_net_path',
        'net_counts_path',
        'network_intensities_path',
        'network_differences_save_path',
        'network_differences_stats_save_path',
        'intersection_intensities_path',
        'intersection_differences_save_path',
        'intersection_differences_stats_save_path',
        'difference_thresh',
        'diff_net_counts_save_path',
        'diff_pt_net_counts_save_path',
        'diff_pt_stops_counts_save_path',
        'prev_net_counts_path',
        'prev_pt_net_counts_path',
        'prev_pt_stops_counts_path',
        'pt_net_counts_path',
        'pt_stops_counts_path',
        'pt_net_counts_path',
        'pt_stops_counts_path',
        'launch'],
    'gis': [
        'qgis_path',
        'project_path',
        'input_facilities',
        'input_edges',
        'input_nodes',
        'output_road_counts',
        'output_pt_counts',
        'output_pt_stops',
        'output_cordons_stats',
        'output_volumes_stats',
        'comparison_rw_road_diffs',
        'comparison_rw_road_intersection_diffs',
        'launch'
    ]
}


class PathPointer:
    """
    Only to get this file's location
    """
    pass
