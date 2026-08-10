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

TIME_COURSES_MODES: Tuple[str] = ('car', 'truck', 'pt')
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
    'from_activity', 'from_facility', 'from_spatial_level', 'from_spatial_unit',
    'to_activity', 'to_facility', 'to_spatial_level', 'to_spatial_unit',
    'mode', 'count'
)

ONEWAY_FLOWS_SCHEMA: Dict[str, Callable] = {
    'from_activity': str,
    'from_facility': str,
    'from_spatial_level': str,
    'from_spatial_unit': str,
    'to_spatial_level': str,
    'to_spatial_unit': str,
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

PT2MATSIM_VEHICLES_CAPACITIES: Dict[str, int] = {
    'Tram': 270,
    'Trolleybus Service': 100,
    'Bus': 100,
    'Rail': 500,
    'Subway': 1000,
    'Cable car': 8
}

PT2MATSIM_EXECUTABLE_PATH: str = '../bin/pt2matsim-22.3-shaded.jar'
# relative to THIS file path

CACHE_SETTINGS_PATH: str = str(Path.home() / '.kammat')

LOGGER_FORMAT: str = '%(asctime)s | %(levelname)s | %(name)s:%(module)s:%(lineno)d:%(funcName)s() - %(message)s'


class PathPointer:
    """
    Only to get this file's location
    """
    pass
