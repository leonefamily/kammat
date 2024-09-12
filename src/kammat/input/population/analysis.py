# -*- coding: utf-8 -*-
"""
Created on Tue Jan 24 15:43:30 2023

@author: dgrishchuk
"""

import re
import pickle
import logging
import pandas as pd
import geopandas as gpd
from pathlib import Path
from collections import defaultdict
from datetime import timedelta as td
from typing import List, Dict, Union, Tuple, Literal, Optional, Callable, Any


from kammat.input.population.agent import Agent
from kammat.defaults.variables import Variables
from kammat.defaults.constants import (
    MODES, ACTIVITY_CODE_LENGTH, CSV_STYLE
    )

Events = List[Dict[str, Union[Agent, td, float, str]]]
FacilitiesStats = Dict[str, Dict[str, Union[List[td], List[Agent], List[int]]]]

v = Variables()


def counts_to_percentage(
        counts_dict: Dict[str, Union[int, float]]
        ) -> Dict[str, float]:
    """
    # !!!
    Handle empty as well

    Parameters
    ----------
    counts_dict : Dict[str, Union[int, float]]
        DESCRIPTION.

    Returns
    -------
    Dict[str, float]

    """
    counts_sum = sum(counts_dict.values())
    return {
        k: v / counts_sum for k, v in counts_dict.items()
        }


def get_main_mode(
        modes: List[str],
        values: Union[List[Any], Tuple[Any]],
        datatype: Callable
        ) -> Optional[str]:
    """
    # !!!

    Parameters
    ----------
    modes : List[str]
        DESCRIPTION.
    values : Union[List[Any], Tuple[Any]]
        Must be summable
    datatype : Callable
        Must be summable

    Returns
    -------
    Optional[str]
        If values are empty, returns None

    """
    agent_modes = defaultdict(datatype)
    for mode, value in zip(modes, values):
        if mode in MODES:
            agent_modes[mode] += value
    if len(agent_modes):
        return max(agent_modes, key=agent_modes.get)


def get_modal_split(
        agents_list: List[Agent],
        method: Literal['all', 'main'] = 'all',
        main_mode_metrics: Literal['trips', 'lastings'] = 'trips',
        to_dataframe: bool = True
        ) -> Union[pd.DataFrame, Dict[str, float]]:
    """
    # !!!

    Parameters
    ----------
    agents_list : List[Agent]
        DESCRIPTION.
    method : Literal['all', 'main'], optional
        DESCRIPTION. The default is 'all'.
    main_mode_metrics : Literal['trips', 'lastings'], optional
        DESCRIPTION. The default is 'trips'.
    to_dataframe : bool, optional
        Whether to convert dict to a dataframe

    Returns
    -------
    Union[pd.DataFrame, Dict[str, float]]

    """

    modes_counts = defaultdict(int)

    if method == 'all':
        for agent in agents_list:
            for mode in agent.modes:
                if mode in MODES:
                    modes_counts[mode] += 1
    elif method == 'main':
        for agent in agents_list:
            if main_mode_metrics == 'trips':
                main_mode = get_main_mode(
                    agent.modes, getattr(agent, 'trips'), float
                    )
            elif main_mode_metrics == 'lastings':
                main_mode = get_main_mode(
                    agent.modes, getattr(agent, 'lastings'), td
                    )

            if main_mode in MODES:
                modes_counts[main_mode] += 1

    modal_split = counts_to_percentage(modes_counts)
    if not to_dataframe:
        return modal_split

    modal_split_df = pd.DataFrame(modal_split, index=[0]).transpose().reset_index()
    modal_split_df.columns = ['mode', 'value']
    return modal_split_df


def get_events_from_agents_list(
        agents_list: List[Agent],
        skip_negative_time: bool = True
        ) -> Events:
    """
    # !!!

    Parameters
    ----------
    agents_list : List[Agent]
        DESCRIPTION.
    skip_negative_time : bool, optional
        DESCRIPTION. The default is True.

    Returns
    -------
    List[Dict[str, Union[Agent, td, float, str]]]
        DESCRIPTION.

    """
    events = []

    for agnum, agent in enumerate(agents_list):
        acts_count = len(agent.activities)
        for i in range(acts_count):
            if i != 0:
                event = {
                    'agent': agent,
                    'activity': agent.activities[i],
                    'type': 'arrival',
                    'time': agent.starttimes[i],
                    'facility': agent.facilities[i],
                    'mode': agent.modes[i - 1]
                    }
                events.append(event)
            if i != acts_count - 1:
                event = {
                    'agent': agent,
                    'activity': agent.activities[i],
                    'type': 'departure',
                    'time': agent.endtimes[i],
                    'facility': agent.facilities[i],
                    'mode': agent.modes[i]
                    }
                events.append(event)

    events.sort(key=lambda e: e['time'])
    if skip_negative_time:
        for evnum, event in enumerate(events):
            if event['time'] >= td(0):
                del events[:evnum]
                break
    return events


def agent_list_to_dict(
        agents_list: List[Agent]
        ) -> Dict[str, Agent]:
    """
    Only works correctly if agent.info is a unique string.

    Parameters
    ----------
    agents_list : List[Agent]
        List of agents

    Returns
    -------
    Dict[str, Agent]
        Dictionary of agents with their ``self.info`` as keys

    """
    ids = set()
    announced = set()
    agents_dict = {}
    for agent in agents_list:
        if agent.info in ids:
            if agent.info not in announced:
                logging.warning(
                    f'{agent.info} id occured more than once, '
                    'dictionary length will not be equal with list length'
                    )
                announced.add(agent.info)
        agents_dict[agent.info] = agent
        ids.add(agent.info)
    return agents_dict


def get_facilities_stats(
        events: Events
        ) -> FacilitiesStats:
    """
    Get dictionary of facilities stats out of event-like list.

    Keys:
        'effect' - list with values 1 and -1 meaning arrival or departure
        'visitors' - list of counts of agents being inside the facility
        'time' - list with time of events
        'agent' - list of references to agents

    Parameters
    ----------
    events : Events
        List of dictionary events

    Returns
    -------
    FacilitiesStats

    """
    facilities_stats = defaultdict(lambda: defaultdict(list))
    facilities_visitors = defaultdict(int)

    for event in events:
        effect = 1 if event['type'] == 'arrival' else -1
        facilities_visitors[event['facility']] += effect
        visitors = facilities_visitors[event['facility']]
        facilities_stats[event['facility']]['effect'].append(effect)
        facilities_stats[event['facility']]['visitors'].append(visitors)
        facilities_stats[event['facility']]['time'].append(event['time'])
        facilities_stats[event['facility']]['agent'].append(event['agent'])

    for d in facilities_stats:
        facilities_stats[d] = dict(facilities_stats[d])

    return dict(facilities_stats)


def get_facility_stats_plot(
        facilities_stats: FacilitiesStats,
        fid: str,
        kind: Literal['visitors_over_time'] = 'visitors_over_time'
        ) -> pd.DataFrame:

    plotdf = pd.DataFrame(facilities_stats[fid])
    plotdf['time'] = plotdf['time'].dt.total_seconds() / 3600  # hours
    plotdf.plot(x='time', y='visitors')  # over time

    facility_sources = [a.spatial_references[0]
                        for a in facilities_stats[fid]['agent']]
    pd.DataFrame(facility_sources)['area'].sort_values().hist()  # to areas


def set_facilties_counts(
        facilities_counts: Dict[str, Dict[str, int]],
        facilities: Dict[str, gpd.GeoDataFrame]
        ):
    """
    Populate columns 'count_own', 'count_nown' and 'count_all' with
    corresponding counts of visiting agents

    Parameters
    ----------
    facilities_counts : Dict[str, Dict[str, int]]
        Total visitor counts for facilities, 'own' and 'not_own'
    facilities : Dict[str, gpd.GeoDataFrame]
        Dictionary of facilities GeoDataFrames

    """

    for act in facilities:
        fids = facilities[act]['facility'].tolist()

        own_count = {
            fid: count for fid, count
            in facilities_counts['own'].items()
            if fid in fids
            }
        if own_count:
            own_ser = pd.Series(own_count, name='count_own')
            facilities[act] = facilities[act].merge(
                own_ser, how='left',
                left_on='facility', right_on=own_ser.index
                )
        else:
            facilities[act]['count_own'] = 0

        not_own_count = {
            fid: count for fid, count
            in facilities_counts['not_own'].items()
            if fid in fids
            }
        if not_own_count:
            not_own_ser = pd.Series(not_own_count, name='count_nown')
            facilities[act] = facilities[act].merge(
                not_own_ser, how='left',
                left_on='facility', right_on=not_own_ser.index
                )
        else:
            facilities[act]['count_nown'] = 0

        facilities[act]['count_all'] = (
            facilities[act]['count_own'].fillna(0) +
            facilities[act]['count_nown'].fillna(0)
            )


def write_facilities_with_counts(
        facilities: Dict[str, gpd.GeoDataFrame],
        output_file: Union[str, Path],
        drop_empty: bool = True
        ):
    """
    Dump facilities with counts into specified folder.
    Filenames are activity codes and .shp suffix.

    Parameters
    ----------
    facilities : Dict[str, gpd.GeoDataFrame]
        Dictionary of facilities GeoDataFrames
    output_file : Union[str, Path]
        Where to dump file
    drop_empty : bool, optional
        Write only rows, that have 'count_all' column above 0.
        The default is True.

    Raises
    ------
    ValueError
        If there is no 'count_all' column in some of facilities' GeoDataFrames

    """
    gdfs = []
    for act, gdf in facilities.items():
        gdf['activity'] = act
        if act not in v.special_acts:
            if 'count_all' not in gdf.columns:
                raise ValueError('Count were not set yet')
            if drop_empty:
                cleaned = gdf.drop(gdf['count_all'][gdf['count_all'] == 0].index)
                if len(cleaned):
                    gdfs.append(gdf)
                else:
                    logging.warning(
                        f'"{act}" facilities do not contain any visited points'
                        )
            else:
                gdfs.append(gdf)

    big_gdf = gpd.GeoDataFrame(
        pd.concat(gdfs, ignore_index=True), crs=gdfs[0].crs
        )
    big_gdf.to_file(output_file)


def get_facilities_counts(
        agents_list: List[Agent],
        ) -> Dict[str, Dict[str, int]]:
    """
    Get how many times each facility was visited. 'own' facility is which
    corresponds with agent's activity, 'not_own' has different type than
    activity (was chosen randomly). Only facilities that have at least 1
    visitor will be exported. Home activity is omitted.

    Parameters
    ----------
    agents_list : List[Agent]
        List of agents

    Returns
    -------
    Dict[str, Dict[str, int]]
        Keys are 'own' and 'not_own', subkeys are facilities ids

    """

    own_counts = defaultdict(int)
    not_own_counts = defaultdict(int)
    re_expr = r'^\b[a-z]{' + str(ACTIVITY_CODE_LENGTH) + '}'

    for agent in agents_list:
        seen = set()
        for i, act in enumerate(agent.activities):
            if act == v.acts['home']:
                continue
            fid = agent.facilities[i]
            act_fid = act, fid
            if act_fid in seen:
                continue
            f_act = re.search(re_expr, fid).group()
            if f_act == act:
                own_counts[fid] += 1
            else:
                not_own_counts[fid] += 1
    return {
        'own': dict(own_counts),
        'not_own': dict(not_own_counts)
        }


def pickle_agents_and_facilities(
        agents_lists: Dict[str, List[Agent]],
        facilities: Dict[str, gpd.GeoDataFrame],
        pickle_file_path: Union[str, Path]
        ):
    """
    Save agents and facilities for later use.

    Warning: consumes a lot of disk space

    Parameters
    ----------
    agents_lists : Dict[str, List[Agent]]
        All types of agents lists in a dictionary
    facilities : Dict[str, gpd.GeoDataFrame]
        Dictionary of facilities
    pickle_file_path : Union[str, Path]
        Save path for pickle object

    """
    with open(pickle_file_path, mode='wb') as pf:
        pickle.dump({
            'agents_lists': agents_lists,
            'facilities': facilities
            }, pf)


def unpickle_agents_and_facilities(
        pickle_file_path: Union[str, Path]
        ) -> Tuple[Dict[str, List[Agent]],
                   Dict[str, gpd.GeoDataFrame]]:
    """
    Load agents and facilities from a pickle object.

    Parameters
    ----------
    pickle_file_path : Union[str, Path]
        Save path for pickle object

    Returns
    -------
    Dict[str, List[Agent]]
        Dictionary of agents lists
    Dict[str, gpd.GeoDataFrame]]
        Dictionary of facilities

    """
    with open(pickle_file_path, mode='rb') as pf:
        data = pickle.load(pf)
    return data['agents_lists'], data['facilities']  # ???


def get_relational_matrices(
        agents_list: List[Agent],
        spatial_unit: str = 'area',
        start: td = td(0),
        end: td = td(1)
        ) -> Dict[str, Dict[Tuple[str], pd.DataFrame]]:
    relations = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    for agent in agents_list:
        visited_combs = set()
        pact, pfc, psu = None, None, None
        for act, stime, fc, su in zip(agent.activities,
                                      agent.starttimes,
                                      agent.facilities,
                                      agent.spatial_references):
            if pact is not None:
                comb = pfc, fc
                if comb not in visited_combs:
                    if start <= stime <= end:
                        rel = pact, act
                        srel = psu[spatial_unit], su[spatial_unit]
                        relations[rel][srel[0]][srel[1]] += 1
                        visited_combs.add(comb)
            pact, pfc, psu = act, fc, su

    rel_dfs_abs = {}
    for rel in relations:
        rel_df = pd.DataFrame.from_dict(relations[rel], orient='index')
        rel_df.index.name = spatial_unit
        rel_df.sort_index(axis=0, inplace=True)
        rel_df.sort_index(axis=1, inplace=True)
        rel_dfs_abs[rel] = rel_df

    rel_dfs_rel = {}
    for rel, rel_df in rel_dfs_abs.items():
        rel_dfs_rel[rel] = rel_df.div(rel_df.sum(axis=1), axis=0).copy()

    rel_mcs = {'absolute': rel_dfs_abs, 'relative': rel_dfs_rel}
    return rel_mcs


def write_relational_matrices(
        rel_mcs: Dict[str, Dict[Tuple[str], pd.DataFrame]],
        save_directory: Union[str, Path]
        ):
    """
    Write relations in folders with absolute and relative values.

    'absolute' and 'relative' folders are created within ``save_directory``

    Note: Due to problems with upper case letters in path (lower case gets
    overwritten by upper case), escort activities in path are enclosed
    in round braces, but are lower case. E.g. pair ('hom', 'WOR') will look
    like hom_(wor).csv in file name.

    Parameters
    ----------
    rel_mcs : Dict[str, Dict[Tuple[str], pd.DataFrame]]
        Relations matrices dictionary
    save_directory : Union[str, Path]
        Parent directory for created folders with tables

    """
    for kind, mcs in rel_mcs.items():
        parent = Path(save_directory) / kind
        parent.mkdir(parents=True, exist_ok=True)
        for rel, mx in mcs.items():
            rel0 = rel[0] if rel[0].islower() else f'({rel[0].lower()})'
            rel1 = rel[1] if rel[1].islower() else f'({rel[1].lower()})'
            mx.to_csv(parent.resolve() / f'{rel0}_{rel1}.csv', **CSV_STYLE)


def analyze_population_basic(
        agents_lists: Dict[str, List[Agent]],
        facilities: Dict[str, gpd.GeoDataFrame],
        modal_split_save_path: Union[str, Path],
        facilities_counts_save_directory: Union[str, Path],
        relational_matrices_save_directory: Union[str, Path],
        spatial_unit: str = 'area',
        start: td = td(0),
        end: td = td(2)
        ) -> Dict[str, pd.DataFrame]:
    modal_split_df = get_modal_split(
        agents_lists['regular'],
        method='all',
        main_mode_metrics='trips',
        to_dataframe=True
        )
    modal_split_df.to_csv(modal_split_save_path, **CSV_STYLE)

    agents_dict = agent_list_to_dict(agents_lists['regular'])
    if len(agents_dict) != len(agents_dict):
        logging.warning('Skipping events analysis')  # ???
    else:
        pass

    facilities_counts = get_facilities_counts(agents_lists['regular'])
    set_facilties_counts(facilities_counts, facilities)
    write_facilities_with_counts(facilities, facilities_counts_save_directory)

    rel_mcs = get_relational_matrices(
        agents_lists['regular'], spatial_unit, start, end
        )
    write_relational_matrices(rel_mcs, relational_matrices_save_directory)

    # after midnight travellers ?
    # hourly zones ?
